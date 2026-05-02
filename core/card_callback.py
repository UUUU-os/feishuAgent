from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cards import build_pending_action_item_callback_card
from config.loader import Settings
from core.confirmation_commands import (
    claim_pending_action_status,
    load_pending_action_value,
    load_pending_action_records,
    mark_pending_action_status,
    update_pending_action_value,
)
from core.models import ActionItem, AgentToolCall, Event, EvidenceRef, WorkflowContext
from core.policy import AgentPolicy
from core.post_meeting import (
    build_task_create_arguments,
    build_task_mapping_payload,
    is_group_owner_candidate,
)
from core.storage import MeetFlowStorage


@dataclass(slots=True)
class CardCallbackResult:
    """飞书卡片回调处理结果。

    回调必须在 3 秒内给飞书返回响应，因此这里统一输出可直接序列化的 toast。
    真实写入失败也返回 error toast，而不是让飞书客户端等待超时报错。
    """

    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    response_card: dict[str, Any] | None = None

    def to_feishu_response(self) -> dict[str, Any]:
        """转换为飞书卡片回调响应体。"""

        toast_type = "success" if self.status == "success" else "error" if self.status == "error" else "info"
        response = {"toast": {"type": toast_type, "content": self.message}}
        if isinstance(self.response_card, dict) and self.response_card:
            response["card"] = {"type": "raw", "data": self.response_card}
        return response


def handle_post_meeting_card_callback(
    payload: dict[str, Any],
    settings: Settings,
    client: Any,
    storage: MeetFlowStorage,
    policy: AgentPolicy | None = None,
) -> CardCallbackResult:
    """处理 M4 待确认任务卡片按钮回调。

    按钮只传递用户意图和 Action Item 草案。确认创建时仍会解析负责人、转换
    截止时间，并再次通过 `AgentPolicy`，保证卡片点击不会绕过安全边界。
    """

    action_value = extract_card_action_value(payload)
    action = str(action_value.get("action") or "")
    if not action:
        return CardCallbackResult(status="ignored", message="未识别到卡片动作。")

    state_guard = guard_pending_action_transition(settings=settings, action_value=action_value, action=action)
    if state_guard is not None:
        response_card = build_card_from_callback_value(
            merge_cached_action_value(settings, action_value),
            mode="resolved",
            status_message=state_guard.message,
            status_kind="success" if state_guard.status == "success" else "info",
        )
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="duplicate_blocked",
            result={"message": state_guard.message, "status": state_guard.status},
        )
        apply_callback_card_update(
            client=client,
            settings=settings,
            payload=payload,
            action_value=action_value,
            card=response_card,
        )
        state_guard.response_card = response_card
        return state_guard

    append_card_callback_log(settings, payload=payload, action_value=action_value, status="received")
    if action == "confirm_create_task":
        return confirm_create_task_from_card(
            action_value=action_value,
            payload=payload,
            settings=settings,
            client=client,
            storage=storage,
            policy=policy or AgentPolicy(),
        )
    if action == "reject_create_task":
        item_id = str(action_value.get("item_id") or "")
        claimed, current_status = claim_pending_action_status(
            settings,
            item_id,
            "rejecting",
            allowed_statuses={"pending"},
            result={"status": "processing", "message": "正在拒绝创建任务。"},
        )
        if not claimed:
            state_guard = build_transition_guard_result(settings, item_id, current_status)
            if state_guard is not None:
                response_card = build_card_from_callback_value(
                    merge_cached_action_value(settings, action_value),
                    mode="resolved",
                    status_message=state_guard.message,
                    status_kind="success" if state_guard.status == "success" else "info",
                )
                apply_callback_card_update(
                    client=client,
                    settings=settings,
                    payload=payload,
                    action_value=action_value,
                    card=response_card,
                )
                state_guard.response_card = response_card
                return state_guard
        cached_value = load_pending_action_value(settings, item_id) or {}
        merged_action_value = dict(cached_value)
        merged_action_value.update(action_value)
        response_card = build_card_from_callback_value(
            merged_action_value,
            mode="resolved",
            status_message="已拒绝创建，MeetFlow 不会再自动落地这条任务。",
            status_kind="info",
        )
        mark_pending_action_status(
            settings,
            item_id,
            status="reject_create_task",
            result={"status": "success", "message": f"已拒绝创建任务 {item_id}。"},
        )
        append_card_callback_log(settings, payload=payload, action_value=action_value, status="rejected")
        apply_callback_card_update(
            client=client,
            settings=settings,
            payload=payload,
            action_value=action_value,
            card=response_card,
        )
        return CardCallbackResult(
            status="success",
            message=f"已拒绝创建任务 {item_id}。",
            response_card=response_card,
        )
    if action == "edit_task_fields":
        return handle_edit_task_fields(action_value=action_value, payload=payload, settings=settings, client=client)
    return CardCallbackResult(status="ignored", message=f"暂不支持的卡片动作：{action}")


def confirm_create_task_from_card(
    action_value: dict[str, Any],
    payload: dict[str, Any],
    settings: Settings,
    client: Any,
    storage: MeetFlowStorage,
    policy: AgentPolicy,
) -> CardCallbackResult:
    """从卡片回调中确认创建任务。"""

    item_id = str(action_value.get("item_id") or "")
    cached_value = load_pending_action_value(settings, item_id) or {}
    merged_action_value = dict(cached_value)
    merged_action_value.update(action_value)
    action_item = action_item_from_callback_value(merged_action_value)
    overrides = extract_edit_overrides(action_value)
    if overrides.get("owner"):
        action_item.owner = str(overrides["owner"])
    if overrides.get("due_date"):
        action_item.due_date = str(overrides["due_date"])
    context = workflow_context_from_callback_value(action_value)
    from adapters import create_feishu_tool_registry  # noqa: PLC0415 - 避免 adapters/core 初始化循环。

    registry = create_feishu_tool_registry(client, default_chat_id=settings.feishu.default_chat_id)
    if overrides.get("owner") or overrides.get("due_date"):
        update_pending_action_value(
            settings,
            item_id=action_item.item_id,
            updates={key: value for key, value in {"owner": action_item.owner, "due_date": action_item.due_date}.items() if value},
            status="pending",
        )
    claimed, current_status = claim_pending_action_status(
        settings,
        action_item.item_id,
        "creating",
        allowed_statuses={"pending"},
        result={"status": "processing", "message": f"正在创建任务：{action_item.title}"},
    )
    if not claimed:
        state_guard = build_transition_guard_result(settings, action_item.item_id, current_status)
        if state_guard is not None:
            response_card = build_card_from_callback_value(
                action_item_to_callback_value(action_item, context=context, action_value=merged_action_value),
                mode="resolved",
                status_message=state_guard.message,
                status_kind="success" if state_guard.status == "success" else "info",
            )
            apply_callback_card_update(
                client=client,
                settings=settings,
                payload=payload,
                action_value=action_value,
                card=response_card,
            )
            state_guard.response_card = response_card
            return state_guard
    assignee_ids = []
    owner_open_id = str(overrides.get("owner_open_id") or "").strip()
    if owner_open_id:
        assignee_ids = [owner_open_id]
    else:
        assignee_ids = resolve_owner_open_ids_for_callback(registry, action_item.owner)
    arguments = build_task_create_arguments(
        action_item=action_item,
        context=context,
        assignee_ids=assignee_ids,
        timezone=settings.app.timezone,
    )
    arguments["confidence"] = max(float(arguments.get("confidence", 0.0) or 0.0), 0.95)
    tool_result = execute_callback_tool_with_policy(
        registry=registry,
        policy=policy,
        context=context,
        tool_name="tasks.create_task",
        arguments=arguments,
        storage=storage,
    )
    if tool_result.status != "success":
        reason = tool_result.error_message or tool_result.content or "任务创建未通过策略或飞书接口失败。"
        response_card = build_card_from_callback_value(
            action_item_to_callback_value(action_item, context=context, action_value=merged_action_value),
            mode="edit",
            status_message=reason[:180],
            status_kind="error",
        )
        mark_pending_action_status(
            settings,
            action_item.item_id,
            status="pending",
            result={"status": tool_result.status, "message": reason, "tool_result": tool_result.to_dict()},
        )
        append_card_callback_log(settings, payload=payload, action_value=action_value, status="create_failed", result=tool_result.to_dict())
        apply_callback_card_update(
            client=client,
            settings=settings,
            payload=payload,
            action_value=action_value,
            card=response_card,
        )
        return CardCallbackResult(
            status="error",
            message=reason[:180],
            data={"tool_result": tool_result.to_dict()},
            response_card=response_card,
        )

    created_task = tool_result.data
    task_item = action_item_from_tool_data(created_task)
    mapping = build_task_mapping_payload(action_item, task_item, context=context)
    storage.save_task_mapping(**mapping)
    mark_pending_action_status(
        settings,
        action_item.item_id,
        status="created",
        result={"status": "success", "message": f"已创建任务：{action_item.title}", "task_mapping": mapping},
    )
    append_card_callback_log(
        settings,
        payload=payload,
        action_value=action_value,
        status="created",
        result={"tool_result": tool_result.to_dict(), "task_mapping": mapping},
    )
    response_card = build_card_from_callback_value(
        action_item_to_callback_value(action_item, context=context, action_value=merged_action_value),
        mode="resolved",
        status_message=f"已创建任务：{action_item.title}",
        status_kind="success",
        task_url=extract_task_url(created_task),
    )
    apply_callback_card_update(
        client=client,
        settings=settings,
        payload=payload,
        action_value=action_value,
        card=response_card,
    )
    return CardCallbackResult(
        status="success",
        message=f"已创建任务：{action_item.title}",
        data={"tool_result": tool_result.to_dict(), "task_mapping": mapping},
        response_card=response_card,
    )


def handle_edit_task_fields(action_value: dict[str, Any], payload: dict[str, Any], settings: Settings, client: Any | None = None) -> CardCallbackResult:
    """处理修改按钮。

    飞书按钮本身不能携带临时文本输入；如果后续卡片表单把 owner/due_date 放入
    form_value，这里会提示用户再次确认。当前先返回可操作指引，避免按钮超时。
    """

    item_id = str(action_value.get("item_id") or "")
    overrides = extract_edit_overrides(action_value)
    updates = {}
    if overrides.get("owner"):
        updates["owner"] = overrides["owner"]
    if overrides.get("due_date"):
        updates["due_date"] = overrides["due_date"]
    if updates:
        updated = update_pending_action_value(settings, item_id=item_id, updates=updates, status="pending")
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="edit_overrides_received",
            result={"updates": updates, "updated": bool(updated)},
        )
        cached_value = load_pending_action_value(settings, item_id) or {}
        response_card = build_card_from_callback_value(
            cached_value,
            mode="edit",
            status_message="字段已暂存，请继续修改或确认创建。",
            status_kind="success",
        )
        if client is not None:
            apply_callback_card_update(
                client=client,
                settings=settings,
                payload=payload,
                action_value=action_value,
                card=response_card,
            )
        if updated:
            return CardCallbackResult(
                status="success",
                message=f"已更新 {item_id} 的字段，请继续点击确认创建。",
                response_card=response_card,
            )
        merged_action_value = dict(action_value)
        merged_action_value.update(updates)
        response_card = build_card_from_callback_value(
            merged_action_value,
            mode="edit",
            status_message="字段已收到，请继续修改或确认创建。",
            status_kind="success",
        )
        if client is not None:
            apply_callback_card_update(
                client=client,
                settings=settings,
                payload=payload,
                action_value=action_value,
                card=response_card,
            )
        return CardCallbackResult(
            status="success",
            message=f"已收到 {item_id} 的修改字段，请继续点击确认创建。",
            response_card=response_card,
        )
    append_card_callback_log(settings, payload=payload, action_value=action_value, status="edit_requested")
    response_card = build_card_from_callback_value(
        load_pending_action_value(settings, item_id) or dict(action_value),
        mode="edit",
        status_message="请补充负责人或截止时间。",
        status_kind="info",
    )
    if client is not None:
        apply_callback_card_update(
            client=client,
            settings=settings,
            payload=payload,
            action_value=action_value,
            card=response_card,
        )
    return CardCallbackResult(
        status="info",
        message=f"请在编辑态卡片中填写负责人或截止时间，再点击“保存修改”或“确认创建”。",
        response_card=response_card,
    )


def extract_card_action_value(payload: dict[str, Any]) -> dict[str, Any]:
    """兼容飞书 v1/v2 卡片回调结构，提取 action.value。"""

    candidates = [
        payload.get("action", {}),
        payload.get("event", {}).get("action", {}) if isinstance(payload.get("event"), dict) else {},
        payload.get("event", {}).get("operator", {}) if isinstance(payload.get("event"), dict) else {},
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("value")
        if isinstance(value, dict):
            merged = dict(value)
            form_value = candidate.get("form_value")
            if isinstance(form_value, dict):
                merged["form_value"] = form_value
            input_value = candidate.get("input_value")
            if input_value is not None:
                merged["input_value"] = input_value
            return merged
    if isinstance(payload.get("value"), dict):
        return dict(payload["value"])
    return {}


def extract_edit_overrides(action_value: dict[str, Any]) -> dict[str, str]:
    """从回调 value 中读取修改字段。"""

    edit = action_value.get("edit")
    if not isinstance(edit, dict):
        edit = {}
    form_value = action_value.get("form_value")
    if not isinstance(form_value, dict):
        form_value = {}
    owner_field = str(action_value.get("owner_field") or "").strip()
    due_date_field = str(action_value.get("due_date_field") or "").strip()
    owner = first_non_empty_form_value(
        action_value.get("owner_override"),
        form_value.get(owner_field) if owner_field else None,
        form_value.get("owner_override"),
        form_value.get("owner_override_text"),
        edit.get("owner"),
    )
    due_date = normalize_due_date_override(
        first_non_empty_form_value(
            action_value.get("due_date_override"),
            form_value.get(due_date_field) if due_date_field else None,
            form_value.get("due_date_override"),
            edit.get("due_date"),
        )
    )
    owner_open_id = first_non_empty_form_value(
        action_value.get("owner_open_id_override"),
        form_value.get("owner_open_id_override"),
        edit.get("owner_open_id"),
    )
    return {
        key: value
        for key, value in {"owner": owner, "due_date": due_date, "owner_open_id": owner_open_id}.items()
        if value
    }


def first_non_empty_form_value(*values: Any) -> str:
    """从按钮 value / form_value 中提取第一个非空表单值。"""

    for value in values:
        normalized = normalize_form_field_value(value)
        if normalized:
            return normalized
    return ""


def normalize_form_field_value(value: Any) -> str:
    """把飞书卡片表单字段值归一化为字符串。"""

    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for item in value:
            normalized = normalize_form_field_value(item)
            if normalized:
                return normalized
        return ""
    if isinstance(value, dict):
        for key in ("value", "text", "date", "open_id", "user_id", "id", "option"):
            normalized = normalize_form_field_value(value.get(key))
            if normalized:
                return normalized
        return ""
    return str(value).strip()


def normalize_due_date_override(value: str) -> str:
    """把卡片控件返回的日期文本归一化成业务侧可解析的格式。"""

    raw = value.strip()
    if not raw:
        return ""
    full_date_match = re.match(r"^(?P<year>20\d{2})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})(?:\s+.*)?$", raw)
    if full_date_match:
        return (
            f"{int(full_date_match.group('year')):04d}-"
            f"{int(full_date_match.group('month')):02d}-"
            f"{int(full_date_match.group('day')):02d}"
        )
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    return raw


def action_item_from_callback_value(action_value: dict[str, Any]) -> ActionItem:
    """从按钮 value 还原最小 ActionItem。"""

    evidence_refs = []
    for ref in list(action_value.get("evidence_refs") or []):
        if not isinstance(ref, dict):
            continue
        evidence_refs.append(
            EvidenceRef(
                source_type=str(ref.get("source_type") or ""),
                source_id=str(ref.get("source_id") or ""),
                source_url=str(ref.get("source_url") or ""),
                snippet=str(ref.get("snippet") or ""),
                updated_at=str(ref.get("updated_at") or ""),
            )
        )
    return ActionItem(
        item_id=str(action_value.get("item_id") or ""),
        title=str(action_value.get("title") or "未命名任务"),
        owner=str(action_value.get("owner") or ""),
        due_date=str(action_value.get("due_date") or ""),
        priority=str(action_value.get("priority") or "medium"),
        confidence=float(action_value.get("confidence") or 0.0),
        needs_confirm=False,
        evidence_refs=evidence_refs,
        extra={"callback_action": str(action_value.get("action") or "")},
    )


def workflow_context_from_callback_value(action_value: dict[str, Any]) -> WorkflowContext:
    """从按钮 value 构造策略审核上下文。"""

    trace_id = f"post_meeting_card_callback:{int(time.time())}"
    event = Event(
        event_id=f"{trace_id}:event",
        event_type="card.action.trigger",
        event_time=str(int(time.time())),
        source="post_meeting_card_callback",
        actor="",
        payload=dict(action_value),
        trace_id=trace_id,
    )
    return WorkflowContext(
        workflow_type="post_meeting_followup",
        trace_id=trace_id,
        event=event,
        meeting_id=str(action_value.get("meeting_id") or ""),
        calendar_event_id=str(action_value.get("calendar_event_id") or ""),
        minute_token=str(action_value.get("minute_token") or ""),
        project_id=str(action_value.get("project_id") or "meetflow"),
        raw_context={
            "decision": {
                "workflow_type": "post_meeting_followup",
                "idempotency_key": f"post_meeting_card:{action_value.get('minute_token') or ''}:{action_value.get('item_id') or ''}",
            },
            "human_confirmation": {
                "confirmed": True,
                "source": "post_meeting_card_callback",
                "action": str(action_value.get("action") or ""),
                "item_id": str(action_value.get("item_id") or ""),
            },
        },
    )


def resolve_owner_open_ids_for_callback(registry: Any, owner: str) -> list[str]:
    """把负责人文本解析为 open_id。"""

    owner_text = owner.strip()
    if not owner_text or is_group_owner_candidate(owner_text):
        return []
    if owner_text in {"我", "本人", "自己"}:
        result = registry.execute(AgentToolCall(call_id="callback_resolve_current_user", tool_name="contact_get_current_user", arguments={}))
        open_id = str(result.data.get("open_id") or result.data.get("user_id") or "")
        return [open_id] if open_id else []

    result = registry.execute(
        AgentToolCall(
            call_id=f"callback_resolve_owner:{owner_text}",
            tool_name="contact_search_user",
            arguments={"query": owner_text, "page_size": 5, "identity": "user"},
        )
    )
    items = result.data.get("items") or result.data.get("users") or []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            open_id = str(item.get("open_id") or item.get("user_id") or item.get("id") or "")
            if open_id:
                return [open_id]
    return []


def execute_callback_tool_with_policy(
    registry: Any,
    policy: AgentPolicy,
    context: WorkflowContext,
    tool_name: str,
    arguments: dict[str, Any],
    storage: MeetFlowStorage,
) -> Any:
    """通过 ToolRegistry + AgentPolicy 执行回调写操作。"""

    tool = registry.get(tool_name)
    tool_call = AgentToolCall(
        call_id=f"post_meeting_card_callback:{tool.llm_name}:{int(time.time() * 1000)}",
        tool_name=tool.llm_name,
        arguments=arguments,
    )
    decision = policy.authorize_tool_call(
        context=context,
        tool=tool,
        tool_call=tool_call,
        allow_write=True,
        storage=storage,
    )
    if not decision.is_allowed():
        from core.models import AgentToolResult

        return AgentToolResult(
            call_id=tool_call.call_id,
            tool_name=tool.internal_name,
            status=decision.status,
            content=f"工具 {tool.internal_name} 被 AgentPolicy 拦截：{decision.reason}",
            data={"policy_decision": decision.to_dict()},
            error_message=decision.reason,
            started_at=int(time.time()),
            finished_at=int(time.time()),
        )
    tool_call.arguments = decision.patched_arguments
    return registry.execute(tool_call)


def append_card_callback_log(
    settings: Settings,
    payload: dict[str, Any],
    action_value: dict[str, Any],
    status: str,
    result: dict[str, Any] | None = None,
) -> None:
    """把卡片回调处理记录写入本地 JSONL，便于真实联调追踪。"""

    path = Path(settings.storage.db_path).parent / "card_callbacks.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "created_at": int(time.time()),
        "status": status,
        "action": action_value.get("action", ""),
        "item_id": action_value.get("item_id", ""),
        "minute_token": action_value.get("minute_token", ""),
        "payload_event_id": payload.get("header", {}).get("event_id", "") if isinstance(payload.get("header"), dict) else "",
        "result": result or {},
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def apply_callback_card_update(
    client: Any,
    settings: Settings,
    payload: dict[str, Any],
    action_value: dict[str, Any],
    card: dict[str, Any],
) -> bool:
    """把回调后的新卡片直接写回原消息。

    真实飞书客户端里，`card.action.trigger` 的响应如果同时携带复杂 `card`
    替换，有兼容性差异，容易表现为红色错误 toast。这里改为显式调用消息更新
    接口：toast 只负责提示，卡片状态由后端主动更新。
    """

    message_id = resolve_callback_message_id(settings, payload, str(action_value.get("item_id") or ""))
    if not message_id:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="card_update_skipped",
            result={"reason": "missing_message_id"},
        )
        return False
    if client is None or not hasattr(client, "update_card_message"):
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="card_update_skipped",
            result={"reason": "client_missing_update_card_message", "message_id": message_id},
        )
        return False
    try:
        # 这些卡片是机器人消息，应使用 tenant 身份更新；如果这里抛异常，就会把
        # 整个按钮回调打成飞书前端的红色失败提示，因此必须吞掉更新异常。
        update_result = client.update_card_message(message_id=message_id, card=card, identity="tenant")
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="card_update_succeeded",
            result={"message_id": message_id, "update_result": update_result},
        )
        return True
    except Exception as error:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="card_update_failed",
            result={"message_id": message_id, "error": str(error)},
        )
        return False


def resolve_callback_message_id(settings: Settings, payload: dict[str, Any], item_id: str) -> str:
    """选择最适合用于消息更新接口的消息 ID。

    飞书按钮回调里常同时出现 `open_message_id` 和 `message_id`。实际更新接口
    `PATCH /im/v1/messages/{message_id}` 需要的是消息 ID，因此优先使用发送时
    已绑定到本地 registry 的 `message_id`；只有缺少绑定时，才回退到回调里
    的 `message_id` / `open_message_id`。
    """

    bound_message_id = find_bound_message_id(settings, item_id)
    if bound_message_id:
        return bound_message_id
    return extract_callback_message_id(payload)


def extract_callback_message_id(payload: dict[str, Any]) -> str:
    """从卡片回调 payload 中提取 open_message_id / message_id。"""

    event = payload.get("event")
    if isinstance(event, dict):
        context = event.get("context")
        if isinstance(context, dict):
            for key in ("message_id", "open_message_id"):
                value = str(context.get(key) or "").strip()
                if value:
                    return value
    header = payload.get("header")
    if isinstance(header, dict):
        for key in ("message_id", "open_message_id"):
            value = str(header.get(key) or "").strip()
            if value:
                return value
    return ""


def find_bound_message_id(settings: Settings, item_id: str) -> str:
    """从本地 pending registry 中查找消息绑定。"""

    if not item_id:
        return ""
    record = load_pending_action_records(settings).get(item_id)
    if not isinstance(record, dict):
        return ""
    source = record.get("source")
    if not isinstance(source, dict):
        return ""
    return str(source.get("message_id") or "").strip()


def merge_cached_action_value(settings: Settings, action_value: dict[str, Any]) -> dict[str, Any]:
    """把 registry 中的 value 与本次按钮值合并。"""

    item_id = str(action_value.get("item_id") or "")
    cached = load_pending_action_value(settings, item_id) or {}
    merged = dict(cached)
    merged.update(action_value)
    return merged


def guard_pending_action_transition(settings: Settings, action_value: dict[str, Any], action: str) -> CardCallbackResult | None:
    """拦截已处理任务的重复点击，避免旧卡片继续改写状态。"""

    item_id = str(action_value.get("item_id") or "")
    if not item_id:
        return None
    record = load_pending_action_records(settings).get(item_id)
    if not isinstance(record, dict):
        return None
    return build_transition_guard_result(settings, item_id, str(record.get("status") or "pending"))


def build_transition_guard_result(settings: Settings, item_id: str, current_status: str) -> CardCallbackResult | None:
    """按当前处理状态生成重复点击拦截结果。"""

    record = load_pending_action_records(settings).get(item_id)
    if not isinstance(record, dict):
        return None
    title = str((record.get("value") or {}).get("title") or item_id)
    if current_status == "created":
        return CardCallbackResult(status="success", message=f"该任务已创建：{title}。")
    if current_status == "reject_create_task":
        return CardCallbackResult(status="success", message=f"该任务已拒绝创建：{title}。")
    if current_status == "creating":
        return CardCallbackResult(status="info", message=f"该任务正在创建中：{title}。")
    if current_status == "rejecting":
        return CardCallbackResult(status="info", message=f"该任务正在拒绝处理中：{title}。")
    return None


def action_item_from_tool_data(data: dict[str, Any]) -> ActionItem:
    """从工具返回数据中还原最小 ActionItem，便于保存 task_mapping。"""

    if "item_id" in data and "title" in data:
        return ActionItem(
            item_id=str(data.get("item_id") or ""),
            title=str(data.get("title") or ""),
            owner=str(data.get("owner") or ""),
            due_date=str(data.get("due_date") or ""),
            status=str(data.get("status") or "todo"),
        )
    return ActionItem(
        item_id=str(data.get("guid") or data.get("task_id") or ""),
        title=str(data.get("summary") or ""),
        status=str(data.get("status") or "todo"),
    )


def build_card_from_callback_value(
    action_value: dict[str, Any],
    *,
    mode: str,
    status_message: str,
    status_kind: str,
    task_url: str = "",
) -> dict[str, Any]:
    """把回调 value 重建成可回写给飞书的卡片。

    飞书按钮回调允许直接返回替换后的卡片；但真实客户端兼容性不稳定，因此这里
    统一把本地 pending registry 中的最小上下文重建为新版 schema 2.0 卡片，
    再走消息更新接口，让状态更新留在群消息里。
    """

    topic = extract_topic_from_action_value(action_value)
    return build_pending_action_item_callback_card(
        action_value,
        topic=topic,
        mode=mode,
        status_message=status_message,
        status_kind=status_kind,
        task_url=task_url,
    )


def extract_topic_from_action_value(action_value: dict[str, Any]) -> str:
    """尽量从按钮 value 中恢复会议主题。"""

    for key in ("meeting_topic", "topic"):
        value = str(action_value.get(key) or "").strip()
        if value:
            return value
    return ""


def action_item_to_callback_value(
    action_item: ActionItem,
    *,
    context: WorkflowContext,
    action_value: dict[str, Any],
) -> dict[str, Any]:
    """把 ActionItem 重新转成按钮回调 value，便于卡片刷新复用。"""

    value = dict(action_value)
    value.update(
        {
            "item_id": action_item.item_id,
            "title": action_item.title,
            "owner": action_item.owner,
            "due_date": action_item.due_date,
            "priority": action_item.priority,
            "confidence": action_item.confidence,
            "meeting_id": context.meeting_id,
            "calendar_event_id": context.calendar_event_id,
            "minute_token": context.minute_token,
            "project_id": context.project_id,
            "evidence_refs": [ref.to_dict() for ref in list(action_item.evidence_refs or [])[:3]],
        }
    )
    return value


def extract_task_url(created_task: dict[str, Any]) -> str:
    """从任务创建结果中提取跳转链接。"""

    if not isinstance(created_task, dict):
        return ""
    extra = created_task.get("extra")
    if isinstance(extra, dict):
        return str(extra.get("url") or "")
    return str(created_task.get("url") or "")
