from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cards import build_pending_action_item_callback_card, build_pending_action_items_card
from config.loader import Settings
from core.card_actions import CardActionRouter, build_card_action_input
from core.confirmation_commands import (
    bind_pending_action_message,
    claim_pending_action_status,
    load_pending_action_value,
    load_pending_action_records,
    mark_pending_action_status,
    update_pending_action_value,
)
from core.models import ActionItem, AgentInput, AgentToolCall, Event, EvidenceRef, WorkflowContext
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
    agent_input: AgentInput | None = None

    def to_feishu_response(self, *, include_card: bool = True) -> dict[str, Any]:
        """转换为飞书卡片回调响应体。

        聚合任务卡点击后需要保留同一消息里的其它任务按钮，因此这里携带的
        `response_card` 必须是已经按 pending registry 重建过的整张卡片，而不是
        单条任务结果卡。这样飞书的立即全量更新也只会隐藏被点击任务的按钮。
        """

        toast_type = "success" if self.status == "success" else "error" if self.status == "error" else "info"
        response = {"toast": {"type": toast_type, "content": self.message}}
        if include_card and isinstance(self.response_card, dict) and self.response_card:
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

    sync_review_session_audit(storage=storage, settings=settings, action_value=action_value)
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
        updated_card = apply_callback_card_update(
            client=client,
            settings=settings,
            payload=payload,
            action_value=action_value,
            card=response_card,
        )
        sync_review_session_audit(storage=storage, settings=settings, action_value=action_value)
        if updated_card:
            response_card = updated_card
        state_guard.response_card = response_card
        return state_guard

    append_card_callback_log(settings, payload=payload, action_value=action_value, status="received")
    if action == "view_pending_tasks":
        return send_pending_tasks_card_from_summary_callback(
            action_value=action_value,
            payload=payload,
            settings=settings,
            client=client,
            storage=storage,
            policy=policy or AgentPolicy(),
        )
    if action == "start_risk_scan":
        return send_risk_scan_card_from_summary_callback(
            action_value=action_value,
            payload=payload,
            settings=settings,
            client=client,
            storage=storage,
            policy=policy or AgentPolicy(),
        )
    if action == "view_post_meeting_report":
        return send_post_meeting_report_card_from_summary_callback(
            action_value=action_value,
            payload=payload,
            settings=settings,
            client=client,
            storage=storage,
            policy=policy or AgentPolicy(),
        )
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
                updated_card = apply_callback_card_update(
                    client=client,
                    settings=settings,
                    payload=payload,
                    action_value=action_value,
                    card=response_card,
                )
                if updated_card:
                    response_card = updated_card
                state_guard.response_card = response_card
                return state_guard
        merged_action_value = merge_cached_action_value(settings, action_value)
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
        sync_review_session_audit(storage=storage, settings=settings, action_value=merged_action_value)
        append_card_callback_log(settings, payload=payload, action_value=action_value, status="rejected")
        updated_card = apply_callback_card_update(
            client=client,
            settings=settings,
            payload=payload,
            action_value=action_value,
            card=response_card,
        )
        if updated_card:
            response_card = updated_card
        return CardCallbackResult(
            status="success",
            message=f"已拒绝创建任务 {item_id}。",
            response_card=response_card,
        )
    if action == "edit_task_fields":
        result = handle_edit_task_fields(action_value=action_value, payload=payload, settings=settings, client=client)
        sync_review_session_audit(storage=storage, settings=settings, action_value=merge_cached_action_value(settings, action_value))
        return result
    return CardCallbackResult(status="ignored", message=f"暂不支持的卡片动作：{action}")


def handle_post_meeting_summary_quick_action(
    *,
    action_value: dict[str, Any],
    payload: dict[str, Any],
    settings: Settings,
) -> CardCallbackResult:
    """处理会后总结卡上的 D3 快捷按钮。

    “查看任务卡”已经有专用发送逻辑；这里复用通用 CardActionRouter 处理
    风险巡检和完整报告入口，保证 HTTP 回调和官方 SDK 长连接都能在 3 秒内
    返回成功 toast。风险巡检只生成受控 AgentInput，是否入队或异步执行由
    统一事件服务的 `--enqueue-agent/--execute-agent` 开关决定。
    """

    action = str(action_value.get("action") or "")
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    trace_id = first_non_empty_text(
        str(action_value.get("trace_id") or ""),
        str(header.get("event_id") or ""),
        f"post_meeting_summary_action:{int(time.time())}",
    )
    action_input = build_card_action_input(
        action=action,
        trace_id=trace_id,
        event_id=str(header.get("event_id") or event.get("event_id") or ""),
        operator_open_id=first_non_empty_text(
            str(operator.get("open_id") or ""),
            str(deep_get(operator, "operator_id", "open_id") or ""),
            str(deep_get(event, "operator_id", "open_id") or ""),
        ),
        chat_id=resolve_summary_action_receive_id(action_value=action_value, payload=payload, records=[], settings=settings),
        open_message_id=extract_callback_message_id(payload),
        workflow_type=str(action_value.get("workflow_type") or "post_meeting_followup"),
        meeting_id=str(action_value.get("meeting_id") or ""),
        calendar_event_id=str(action_value.get("calendar_event_id") or ""),
        source_card=str(action_value.get("source_card") or "post_meeting_summary"),
        idempotency_key=str(action_value.get("idempotency_key") or ""),
        value=action_value,
        raw_event=event,
        created_at=int(time.time()),
    )
    routed = CardActionRouter().route(action_input)
    append_card_callback_log(
        settings,
        payload=payload,
        action_value=action_value,
        status=f"{action}_routed",
        result={
            "status": routed.status,
            "message": routed.message,
            "has_agent_input": routed.agent_input is not None,
            "metadata": routed.metadata,
        },
    )
    status = "error" if routed.status in {"failed", "blocked"} else "success" if routed.status == "accepted" else "info"
    return CardCallbackResult(
        status=status,
        message=routed.message,
        data={
            "card_action": {
                "status": routed.status,
                "action": routed.action,
                "metadata": routed.metadata,
            }
        },
        agent_input=routed.agent_input,
    )


def send_pending_tasks_card_from_summary_callback(
    *,
    action_value: dict[str, Any],
    payload: dict[str, Any],
    settings: Settings,
    client: Any,
    storage: MeetFlowStorage,
    policy: AgentPolicy,
) -> CardCallbackResult:
    """点击会后总结卡的“查看任务卡”后，按当前会议发送聚合任务卡。

    D4 的任务卡可能很长，默认跟随总结卡一起发送会刷屏。这里把待确认任务先
    存在本地 registry；用户点击总结卡入口时，再从 registry 恢复同一妙记 /
    同一会话的任务，发送一张聚合待确认任务卡。
    """

    records = load_pending_action_records(settings)
    related_records, group_reason = find_pending_records_for_summary_action(
        records=records,
        action_value=action_value,
        payload=payload,
        settings=settings,
    )
    if not related_records:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="view_pending_tasks_not_found",
            result={"group_reason": group_reason},
        )
        return CardCallbackResult(status="info", message="当前会议没有待确认任务卡可发送。")

    existing_message_id = first_non_empty_text(*(record_source_message_id(record) for record in related_records))
    if existing_message_id:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="view_pending_tasks_already_sent",
            result={"message_id": existing_message_id, "related_record_count": len(related_records), "group_reason": group_reason},
        )
        return CardCallbackResult(status="success", message="任务卡已经发送过了，请查看当前会话中的 MeetFlow 待确认任务卡。")

    receive_id = resolve_summary_action_receive_id(action_value=action_value, payload=payload, records=related_records, settings=settings)
    if not receive_id:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="view_pending_tasks_missing_receive_id",
            result={"related_record_count": len(related_records), "group_reason": group_reason},
        )
        return CardCallbackResult(status="error", message="无法确定任务卡发送到哪个会话，请检查回调 payload 或默认测试群配置。")

    receive_id_type = first_non_empty_text(
        str(action_value.get("receive_id_type") or ""),
        *((record.get("source") or {}).get("receive_id_type") for record in related_records if isinstance(record.get("source"), dict)),
        "chat_id",
    )
    items = [action_item_from_pending_record(record) for record in related_records]
    topic = first_non_empty_text(
        *(record_value(record).get("meeting_topic") for record in related_records),
        *(record_value(record).get("topic") for record in related_records),
        str(action_value.get("topic") or ""),
    )
    artifacts = SimpleNamespace(
        meeting_summary=SimpleNamespace(topic=topic or "待识别会议"),
        pending_action_items=items,
        action_items=items,
        extra={},
    )
    card = build_pending_action_items_card(artifacts)
    context = workflow_context_from_callback_value(
        {
            **action_value,
            "action": "view_pending_tasks",
            "chat_id": receive_id,
            "meeting_id": first_non_empty_text(str(action_value.get("meeting_id") or ""), *(record_value(record).get("meeting_id") for record in related_records)),
            "minute_token": first_non_empty_text(str(action_value.get("minute_token") or ""), *(record_value(record).get("minute_token") for record in related_records)),
        }
    )
    from adapters import create_feishu_tool_registry  # noqa: PLC0415 - 避免 adapters/core 初始化循环。

    registry = create_feishu_tool_registry(client, default_chat_id=settings.feishu.default_chat_id)
    idempotency_key = build_view_pending_tasks_idempotency_key(
        action_value=action_value,
        records=related_records,
        receive_id=receive_id,
    )
    tool_result = execute_callback_tool_with_policy(
        registry=registry,
        policy=policy,
        context=context,
        tool_name="im.send_card",
        arguments={
            "title": card.get("header", {}).get("title", {}).get("content", "MeetFlow 待确认任务"),
            "summary": "MeetFlow 待确认任务卡",
            "card": card,
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "identity": "tenant",
            "idempotency_key": idempotency_key,
        },
        storage=storage,
    )
    if tool_result.status != "success":
        reason = tool_result.error_message or tool_result.content or "任务卡发送失败。"
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="view_pending_tasks_send_failed",
            result={"reason": reason, "tool_result": tool_result.to_dict()},
        )
        return CardCallbackResult(status="error", message=f"任务卡发送失败：{reason}")

    message_id = str(tool_result.data.get("message_id") or "")
    if message_id:
        for record in related_records:
            bind_pending_action_message(
                settings,
                item_id=str(record.get("item_id") or record_value(record).get("item_id") or ""),
                message_id=message_id,
                chat_id=receive_id,
            )
    append_card_callback_log(
        settings,
        payload=payload,
        action_value=action_value,
        status="view_pending_tasks_sent",
        result={
            "message_id": message_id,
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "related_record_count": len(related_records),
            "group_reason": group_reason,
        },
    )
    return CardCallbackResult(status="success", message="已发送 MeetFlow 待确认任务卡，请在当前会话中查看。")


def send_risk_scan_card_from_summary_callback(
    *,
    action_value: dict[str, Any],
    payload: dict[str, Any],
    settings: Settings,
    client: Any,
    storage: MeetFlowStorage,
    policy: AgentPolicy,
) -> CardCallbackResult:
    """点击“执行风险巡检”后，按同一会议任务直接发送 M5 风险巡检卡。

    这个入口对齐 `view_pending_tasks`：不依赖后台 Agent 是否启动，而是从
    pending registry 恢复同一批行动项，执行确定性风险规则后在当前会话发卡。
    """

    records = load_pending_action_records(settings)
    related_records, group_reason = find_pending_records_for_summary_action(
        records=records,
        action_value=action_value,
        payload=payload,
        settings=settings,
    )
    if not related_records:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="start_risk_scan_not_found",
            result={"group_reason": group_reason},
        )
        return CardCallbackResult(status="info", message="当前会议没有可巡检的会后任务，请先点击“查看任务卡”确认任务上下文。")

    receive_id = resolve_summary_action_receive_id(action_value=action_value, payload=payload, records=related_records, settings=settings)
    if not receive_id:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="start_risk_scan_missing_receive_id",
            result={"related_record_count": len(related_records), "group_reason": group_reason},
        )
        return CardCallbackResult(status="error", message="无法确定风险巡检卡发送到哪个会话，请检查回调 payload 或默认测试群配置。")

    receive_id_type = first_non_empty_text(
        str(action_value.get("receive_id_type") or ""),
        *((record.get("source") or {}).get("receive_id_type") for record in related_records if isinstance(record.get("source"), dict)),
        "chat_id",
    )
    items = [action_item_from_pending_record(record) for record in related_records]
    now = int(time.time())
    risk_settings = build_callback_risk_rule_settings(settings)

    from cards.risk_scan import build_risk_scan_card  # noqa: PLC0415 - 避免 cards/core 初始化循环。
    from core.risk_scan import (
        decide_risk_notification,
        enrich_risks_with_task_mappings,
        normalize_task_snapshots,
        scan_risks,
    )

    scan_result = scan_risks(
        tasks=normalize_task_snapshots(items),
        now=now,
        stale_update_days=int(risk_settings["stale_update_days"]),
        due_soon_hours=int(risk_settings["due_soon_hours"]),
    )
    scan_result = enrich_risks_with_task_mappings(scan_result=scan_result, storage=storage)
    notification_decision = decide_risk_notification(
        scan_result=scan_result,
        storage=storage,
        max_reminders_per_day=int(risk_settings["max_reminders_per_day"]),
        now=now,
    )
    if not scan_result.risks:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="start_risk_scan_no_risk",
            result={"scanned_count": scan_result.scanned_count, "group_reason": group_reason},
        )
        return CardCallbackResult(status="success", message=f"已完成风险巡检：扫描 {scan_result.scanned_count} 个任务，未发现风险。")

    card = build_risk_scan_card(decision=notification_decision, scan_result=scan_result)
    context = workflow_context_from_callback_value(
        {
            **action_value,
            "action": "start_risk_scan",
            "chat_id": receive_id,
            "workflow_type": "risk_scan",
            "meeting_id": first_non_empty_text(str(action_value.get("meeting_id") or ""), *(record_value(record).get("meeting_id") for record in related_records)),
            "minute_token": first_non_empty_text(str(action_value.get("minute_token") or ""), *(record_value(record).get("minute_token") for record in related_records)),
        }
    )
    context.workflow_type = "risk_scan"
    context.raw_context["decision"]["workflow_type"] = "risk_scan"

    from adapters import create_feishu_tool_registry  # noqa: PLC0415 - 避免 adapters/core 初始化循环。

    registry = create_feishu_tool_registry(client, default_chat_id=settings.feishu.default_chat_id)
    idempotency_key = build_summary_action_idempotency_key(
        action="start_risk_scan",
        action_value=action_value,
        records=related_records,
        receive_id=receive_id,
    )
    tool_result = execute_callback_tool_with_policy(
        registry=registry,
        policy=policy,
        context=context,
        tool_name="im.send_card",
        arguments={
            "title": card.get("header", {}).get("title", {}).get("content", "MeetFlow 风险巡检提醒"),
            "summary": "MeetFlow 会后任务风险巡检卡",
            "card": card,
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "identity": "tenant",
            "idempotency_key": idempotency_key,
            "risk_count": scan_result.risk_count,
            "notify_count": max(len(notification_decision.notify_risks), 1),
            "suppressed_count": len(notification_decision.suppressed_risks),
        },
        storage=storage,
    )
    if tool_result.status != "success":
        reason = tool_result.error_message or tool_result.content or "风险巡检卡发送失败。"
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="start_risk_scan_send_failed",
            result={"reason": reason, "tool_result": tool_result.to_dict(), "group_reason": group_reason},
        )
        return CardCallbackResult(status="error", message=f"风险巡检卡发送失败：{reason}")

    record_callback_risk_notifications(
        storage=storage,
        decision=notification_decision.to_dict(),
        scan_result=scan_result.to_dict(),
        recipient=receive_id,
        now=now,
    )
    message_id = str(tool_result.data.get("message_id") or "")
    append_card_callback_log(
        settings,
        payload=payload,
        action_value=action_value,
        status="start_risk_scan_sent",
        result={
            "message_id": message_id,
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "related_record_count": len(related_records),
            "risk_count": scan_result.risk_count,
            "notify_count": len(notification_decision.notify_risks),
            "suppressed_count": len(notification_decision.suppressed_risks),
            "group_reason": group_reason,
        },
    )
    return CardCallbackResult(status="success", message="已发送 MeetFlow 风险巡检卡，请在当前会话中查看。")


def send_post_meeting_report_card_from_summary_callback(
    *,
    action_value: dict[str, Any],
    payload: dict[str, Any],
    settings: Settings,
    client: Any,
    storage: MeetFlowStorage,
    policy: AgentPolicy,
) -> CardCallbackResult:
    """点击“查看完整报告”后，在当前会话发送报告入口卡。"""

    receive_id = resolve_summary_action_receive_id(action_value=action_value, payload=payload, records=[], settings=settings)
    if not receive_id:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="view_post_meeting_report_missing_receive_id",
        )
        return CardCallbackResult(status="error", message="无法确定完整报告卡发送到哪个会话，请检查回调 payload 或默认测试群配置。")

    receive_id_type = str(action_value.get("receive_id_type") or "chat_id")
    report_ref = first_non_empty_text(
        str(action_value.get("report_url") or ""),
        str(action_value.get("report_path") or ""),
        find_latest_post_meeting_report_path(settings=settings, action_value=action_value),
    )
    card = build_post_meeting_report_entry_card(action_value=action_value, report_ref=report_ref)
    context = workflow_context_from_callback_value(
        {
            **action_value,
            "action": "view_post_meeting_report",
            "chat_id": receive_id,
        }
    )

    from adapters import create_feishu_tool_registry  # noqa: PLC0415 - 避免 adapters/core 初始化循环。

    registry = create_feishu_tool_registry(client, default_chat_id=settings.feishu.default_chat_id)
    idempotency_key = build_summary_action_idempotency_key(
        action="view_post_meeting_report",
        action_value=action_value,
        records=[],
        receive_id=receive_id,
    )
    tool_result = execute_callback_tool_with_policy(
        registry=registry,
        policy=policy,
        context=context,
        tool_name="im.send_card",
        arguments={
            "title": card.get("header", {}).get("title", {}).get("content", "MeetFlow 完整复盘报告"),
            "summary": "MeetFlow 完整复盘报告入口",
            "card": card,
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "identity": "tenant",
            "idempotency_key": idempotency_key,
        },
        storage=storage,
    )
    if tool_result.status != "success":
        reason = tool_result.error_message or tool_result.content or "完整报告卡发送失败。"
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="view_post_meeting_report_send_failed",
            result={"reason": reason, "tool_result": tool_result.to_dict(), "report_ref": report_ref},
        )
        return CardCallbackResult(status="error", message=f"完整报告卡发送失败：{reason}")

    append_card_callback_log(
        settings,
        payload=payload,
        action_value=action_value,
        status="view_post_meeting_report_sent",
        result={
            "message_id": str(tool_result.data.get("message_id") or ""),
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "report_ref": report_ref,
        },
    )
    return CardCallbackResult(status="success", message="已发送 MeetFlow 完整复盘报告入口，请在当前会话中查看。")


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
    merged_action_value = merge_cached_action_value(settings, action_value)
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
            updated_card = apply_callback_card_update(
                client=client,
                settings=settings,
                payload=payload,
                action_value=action_value,
                card=response_card,
            )
            if updated_card:
                response_card = updated_card
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
        updated_card = apply_callback_card_update(
            client=client,
            settings=settings,
            payload=payload,
            action_value=action_value,
            card=response_card,
        )
        if updated_card:
            response_card = updated_card
        return CardCallbackResult(
            status="error",
            message=reason[:180],
            data={"tool_result": tool_result.to_dict()},
            response_card=response_card,
        )

    created_task = tool_result.data
    task_item = action_item_from_tool_data(created_task)
    mapping = build_task_mapping_payload(action_item, task_item, context=context)
    review_session_id = str(merged_action_value.get("review_session_id") or "").strip()
    if review_session_id:
        mapping["item_id"] = f"{mapping['item_id']}:{review_session_id}"
    storage.save_task_mapping(**mapping)
    mark_pending_action_status(
        settings,
        action_item.item_id,
        status="created",
        result={"status": "success", "message": f"已创建任务：{action_item.title}", "task_mapping": mapping},
    )
    sync_review_session_audit(storage=storage, settings=settings, action_value=merged_action_value)
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
    updated_card = apply_callback_card_update(
        client=client,
        settings=settings,
        payload=payload,
        action_value=action_value,
        card=response_card,
    )
    if updated_card:
        response_card = updated_card
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
            updated_card = apply_callback_card_update(
                client=client,
                settings=settings,
                payload=payload,
                action_value=action_value,
                card=response_card,
            )
            if updated_card:
                response_card = updated_card
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
            updated_card = apply_callback_card_update(
                client=client,
                settings=settings,
                payload=payload,
                action_value=action_value,
                card=response_card,
            )
            if updated_card:
                response_card = updated_card
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
        updated_card = apply_callback_card_update(
            client=client,
            settings=settings,
            payload=payload,
            action_value=action_value,
            card=response_card,
        )
        if updated_card:
            response_card = updated_card
    return CardCallbackResult(
        status="info",
        message=f"请在编辑态卡片中填写负责人或截止时间，再点击“确认创建”。",
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
    owner_field = sanitize_callback_text(action_value.get("owner_field"))
    due_date_field = sanitize_callback_text(action_value.get("due_date_field"))
    owner = first_non_empty_form_value(
        action_value.get("owner_override"),
        find_form_value_by_key(form_value, owner_field),
        find_form_value_by_key(form_value, "owner_override"),
        find_form_value_by_key(form_value, "owner_override_text"),
        find_form_value_by_prefix(form_value, "owner_override"),
        edit.get("owner"),
    )
    due_date = normalize_due_date_override(
        first_non_empty_form_value(
            action_value.get("due_date_override"),
            find_form_value_by_key(form_value, due_date_field),
            find_form_value_by_key(form_value, "due_date_override"),
            find_form_value_by_prefix(form_value, "due_date_override"),
            edit.get("due_date"),
        )
    )
    owner_open_id = first_non_empty_form_value(
        action_value.get("owner_open_id_override"),
        find_form_value_by_key(form_value, "owner_open_id_override"),
        find_form_value_by_prefix(form_value, "owner_open_id_override"),
        edit.get("owner_open_id"),
    )
    return {
        key: value
        for key, value in {"owner": owner, "due_date": due_date, "owner_open_id": owner_open_id}.items()
        if value
    }


def find_form_value_by_key(form_value: Any, key: str) -> Any:
    """递归读取飞书 schema 2.0 表单字段。

    飞书有时会把提交值包装成 `{form_name: {field_name: value}}`，不能只读
    `form_value[field_name]`，否则用户已经填写的负责人/截止时间会在后端丢失。
    """

    if not key or not isinstance(form_value, (dict, list)):
        return None
    if isinstance(form_value, list):
        for item in form_value:
            found = find_form_value_by_key(item, key)
            if found is not None:
                return found
        return None
    if key in form_value:
        return form_value[key]
    for value in form_value.values():
        found = find_form_value_by_key(value, key)
        if found is not None:
            return found
    return None


def find_form_value_by_prefix(form_value: Any, prefix: str) -> Any:
    """按字段名前缀兜底读取表单值。

    卡片字段会带 `__item_id` 后缀；当旧卡或 SDK 回调没有带回 owner_field /
    due_date_field 时，使用前缀仍能找到同一类输入框。
    """

    if not prefix or not isinstance(form_value, (dict, list)):
        return None
    if isinstance(form_value, list):
        for item in form_value:
            found = find_form_value_by_prefix(item, prefix)
            if found is not None:
                return found
        return None
    for key, value in form_value.items():
        if isinstance(key, str) and (key == prefix or key.startswith(f"{prefix}__")):
            return value
        found = find_form_value_by_prefix(value, prefix)
        if found is not None:
            return found
    return None


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
        return sanitize_callback_text(value)
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
    return sanitize_callback_text(value)


def sanitize_callback_text(value: Any) -> str:
    """清理卡片回调文本里的控制字符。

    用户从飞书卡片或外部文本复制内容时，偶尔会混入 NUL 等控制字符；这些字符
    继续进入子进程、SQLite 或飞书 API 时会触发 `embedded null byte` 一类异常。
    """

    text = str(value or "").strip()
    return "".join(ch for ch in text if ord(ch) >= 32 and ord(ch) != 127).strip()


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
                source_type=sanitize_callback_text(ref.get("source_type")),
                source_id=sanitize_callback_text(ref.get("source_id")),
                source_url=sanitize_callback_text(ref.get("source_url")),
                snippet=sanitize_callback_text(ref.get("snippet")),
                updated_at=sanitize_callback_text(ref.get("updated_at")),
            )
        )
    return ActionItem(
        item_id=sanitize_callback_text(action_value.get("item_id")),
        title=sanitize_callback_text(action_value.get("title") or "未命名任务"),
        owner=sanitize_callback_text(action_value.get("owner")),
        due_date=sanitize_callback_text(action_value.get("due_date")),
        priority=sanitize_callback_text(action_value.get("priority") or "medium"),
        confidence=float(action_value.get("confidence") or 0.0),
        needs_confirm=False,
        evidence_refs=evidence_refs,
        extra={"callback_action": sanitize_callback_text(action_value.get("action"))},
    )


def workflow_context_from_callback_value(action_value: dict[str, Any]) -> WorkflowContext:
    """从按钮 value 构造策略审核上下文。"""

    trace_id = f"post_meeting_card_callback:{int(time.time())}"
    review_session_id = str(action_value.get("review_session_id") or "").strip()
    idempotency_parts = [
        "post_meeting_card",
        str(action_value.get("minute_token") or ""),
        str(action_value.get("item_id") or ""),
    ]
    if review_session_id:
        idempotency_parts.append(review_session_id)
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
                "idempotency_key": ":".join(idempotency_parts),
            },
            "human_confirmation": {
                "confirmed": True,
                "source": "post_meeting_card_callback",
                "action": str(action_value.get("action") or ""),
                "item_id": str(action_value.get("item_id") or ""),
                "review_session_id": review_session_id,
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
) -> dict[str, Any] | None:
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
        return None
    if client is None or not hasattr(client, "update_card_message"):
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="card_update_skipped",
            result={"reason": "client_missing_update_card_message", "message_id": message_id},
        )
        return None
    try:
        card = build_aggregate_card_for_callback_update(
            settings=settings,
            payload=payload,
            action_value=action_value,
            fallback_card=card,
        )
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
        return card
    except Exception as error:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="card_update_failed",
            result={"message_id": message_id, "error": str(error)},
        )
        return None


def build_aggregate_card_for_callback_update(
    *,
    settings: Settings,
    payload: dict[str, Any],
    action_value: dict[str, Any],
    fallback_card: dict[str, Any],
) -> dict[str, Any]:
    """聚合任务卡点击后重建整张卡，避免单条结果卡替换掉其它按钮。

    飞书消息更新是 message 级别，不是组件级别。同一会议的所有待确认任务
    聚合在一条消息里时，如果仍用单条任务卡回写，就会让其它任务按钮全部消失。
    这里优先按同一 message_id 找出同卡片里的所有 pending action，并重建聚合卡；
    单条卡或 reaction 卡仍回退到原来的单条结果卡。
    """

    item_id = str(action_value.get("item_id") or "")
    message_id = resolve_callback_message_id(settings, payload, item_id)
    if not message_id:
        return fallback_card
    records = load_pending_action_records(settings)
    related_records, group_reason = find_related_pending_records_for_update(
        records=records,
        item_id=item_id,
        message_id=message_id,
    )
    if len(related_records) <= 1:
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="single_card_update_selected",
            result={
                "message_id": message_id,
                "item_id": item_id,
                "related_record_count": len(related_records),
                "group_reason": group_reason,
            },
        )
        return fallback_card
    append_card_callback_log(
        settings,
        payload=payload,
        action_value=action_value,
        status="aggregate_card_update_selected",
        result={
            "message_id": message_id,
            "item_id": item_id,
            "related_record_count": len(related_records),
            "group_reason": group_reason,
        },
    )
    items = [action_item_from_pending_record(record) for record in related_records]
    topic = first_non_empty_text(
        *(record_value(record).get("meeting_topic") for record in related_records),
        *(record_value(record).get("topic") for record in related_records),
    )
    artifacts = SimpleNamespace(
        meeting_summary=SimpleNamespace(topic=topic or "待识别会议"),
        pending_action_items=items,
        action_items=items,
        extra={},
    )
    return build_pending_action_items_card(artifacts)


def find_related_pending_records_for_update(
    *,
    records: dict[str, dict[str, Any]],
    item_id: str,
    message_id: str,
) -> tuple[list[dict[str, Any]], str]:
    """查找与本次按钮属于同一张聚合任务卡的 pending records。

    真实回调里 `message_id` / `open_message_id` 可能和发送接口返回的 ID 形态不同；
    因此先按绑定消息 ID 匹配，失败后再用当前任务的 `review_session_id` 兜底。
    """

    by_message = [
        record
        for record in records.values()
        if isinstance(record, dict) and message_id and record_source_message_id(record) == message_id
    ]
    if len(by_message) > 1:
        return by_message, "message_id"

    current_record = records.get(item_id)
    if not isinstance(current_record, dict):
        return by_message, "message_id_missing_current"
    review_session_id = extract_record_review_session_id(current_record)
    if review_session_id:
        by_session = [
            record
            for record in records.values()
            if isinstance(record, dict) and extract_record_review_session_id(record) == review_session_id
        ]
        if len(by_session) > 1:
            return by_session, "review_session_id"

    current_value = record_value(current_record)
    minute_token = str(current_value.get("minute_token") or "").strip()
    source = current_record.get("source") if isinstance(current_record.get("source"), dict) else {}
    chat_id = str(source.get("chat_id") or "").strip()
    if minute_token and chat_id:
        by_minute_chat = [
            record
            for record in records.values()
            if isinstance(record, dict)
            and str(record_value(record).get("minute_token") or "").strip() == minute_token
            and str((record.get("source") if isinstance(record.get("source"), dict) else {}).get("chat_id") or "").strip() == chat_id
        ]
        if len(by_minute_chat) > 1:
            return by_minute_chat, "minute_token_chat_id"

    return by_message or [current_record], "single"


def find_pending_records_for_summary_action(
    *,
    records: dict[str, dict[str, Any]],
    action_value: dict[str, Any],
    payload: dict[str, Any],
    settings: Settings,
) -> tuple[list[dict[str, Any]], str]:
    """按总结卡按钮上下文查找应发送的待确认任务。

    “查看任务卡”按钮来自会后总结卡，本身没有 `item_id`，因此不能复用任务
    按钮的 message_id 分组逻辑。这里按确认批次优先，其次按妙记 + 会话定位，
    保证同一会议点击后只发送对应的一张聚合任务卡。
    """

    review_session_id = str(action_value.get("review_session_id") or "").strip()
    if review_session_id:
        by_session = [
            record
            for record in records.values()
            if isinstance(record, dict) and extract_record_review_session_id(record) == review_session_id
        ]
        if by_session:
            return by_session, "review_session_id"

    minute_token = str(action_value.get("minute_token") or "").strip()
    meeting_id = str(action_value.get("meeting_id") or "").strip()
    chat_id = resolve_summary_action_receive_id(action_value=action_value, payload=payload, records=[], settings=settings)
    if minute_token and chat_id:
        by_minute_chat = [
            record
            for record in records.values()
            if isinstance(record, dict)
            and str(record_value(record).get("minute_token") or "").strip() == minute_token
            and str((record.get("source") if isinstance(record.get("source"), dict) else {}).get("chat_id") or "").strip() == chat_id
        ]
        if by_minute_chat:
            return by_minute_chat, "minute_token_chat_id"

    if meeting_id and chat_id:
        by_meeting_chat = [
            record
            for record in records.values()
            if isinstance(record, dict)
            and str(record_value(record).get("meeting_id") or "").strip() == meeting_id
            and str((record.get("source") if isinstance(record.get("source"), dict) else {}).get("chat_id") or "").strip() == chat_id
        ]
        if by_meeting_chat:
            return by_meeting_chat, "meeting_id_chat_id"

    if minute_token:
        by_minute = [
            record
            for record in records.values()
            if isinstance(record, dict) and str(record_value(record).get("minute_token") or "").strip() == minute_token
        ]
        if by_minute:
            return by_minute, "minute_token"

    return [], "not_found"


def resolve_summary_action_receive_id(
    *,
    action_value: dict[str, Any],
    payload: dict[str, Any],
    records: list[dict[str, Any]],
    settings: Settings,
) -> str:
    """确定“查看任务卡”按钮触发后新任务卡应发送到哪个会话。"""

    return first_non_empty_text(
        str(action_value.get("chat_id") or ""),
        extract_callback_chat_id(payload),
        *((record.get("source") if isinstance(record.get("source"), dict) else {}).get("chat_id") for record in records),
        getattr(settings.feishu, "default_chat_id", ""),
    )


def extract_callback_chat_id(payload: dict[str, Any]) -> str:
    """从飞书回调 payload 中提取当前会话 ID。"""

    event = payload.get("event")
    if isinstance(event, dict):
        context = event.get("context")
        if isinstance(context, dict):
            for key in ("open_chat_id", "chat_id"):
                value = str(context.get(key) or "").strip()
                if value:
                    return value
        for key in ("open_chat_id", "chat_id"):
            value = str(event.get(key) or "").strip()
            if value:
                return value
    return ""


def build_view_pending_tasks_idempotency_key(
    *,
    action_value: dict[str, Any],
    records: list[dict[str, Any]],
    receive_id: str,
) -> str:
    """生成查看任务卡发消息的幂等键。"""

    review_session_id = first_non_empty_text(
        str(action_value.get("review_session_id") or ""),
        *(extract_record_review_session_id(record) for record in records),
    )
    minute_token = first_non_empty_text(
        str(action_value.get("minute_token") or ""),
        *(record_value(record).get("minute_token") for record in records),
    )
    meeting_id = first_non_empty_text(
        str(action_value.get("meeting_id") or ""),
        *(record_value(record).get("meeting_id") for record in records),
    )
    key_parts = ["post_meeting", "view_pending_tasks", review_session_id or minute_token or meeting_id or "unknown", receive_id]
    return ":".join(str(part) for part in key_parts if str(part or "").strip())


def build_summary_action_idempotency_key(
    *,
    action: str,
    action_value: dict[str, Any],
    records: list[dict[str, Any]],
    receive_id: str,
) -> str:
    """生成 D3 总结卡快捷动作发消息的幂等键。"""

    review_session_id = first_non_empty_text(
        str(action_value.get("review_session_id") or ""),
        *(extract_record_review_session_id(record) for record in records),
    )
    minute_token = first_non_empty_text(
        str(action_value.get("minute_token") or ""),
        *(record_value(record).get("minute_token") for record in records),
    )
    meeting_id = first_non_empty_text(
        str(action_value.get("meeting_id") or ""),
        *(record_value(record).get("meeting_id") for record in records),
    )
    key_parts = ["post_meeting", action, review_session_id or minute_token or meeting_id or "unknown", receive_id]
    return ":".join(str(part) for part in key_parts if str(part or "").strip())


def build_callback_risk_rule_settings(settings: Settings) -> dict[str, int]:
    """读取回调风险巡检规则，测试配置缺字段时使用保守默认值。"""

    risk_rules = getattr(settings, "risk_rules", None)
    return {
        "stale_update_days": int(getattr(risk_rules, "stale_update_days", 3) or 3),
        "due_soon_hours": int(getattr(risk_rules, "due_soon_hours", 48) or 48),
        "max_reminders_per_day": int(getattr(risk_rules, "max_reminders_per_day", 20) or 20),
    }


def build_post_meeting_report_entry_card(action_value: dict[str, Any], report_ref: str) -> dict[str, Any]:
    """构造完整复盘报告入口卡。

    本地 Markdown 路径不能作为飞书按钮 URL 打开，所以这里用普通卡片文本
    显示路径；如果后续生成 http(s)/lark/feishu 链接，则以 Markdown 链接呈现。
    """

    meeting_id = sanitize_callback_text(action_value.get("meeting_id"))
    minute_token = sanitize_callback_text(action_value.get("minute_token"))
    report_text = render_report_ref_markdown(report_ref)
    lines = [
        "**完整复盘报告入口**",
        report_text,
    ]
    if meeting_id:
        lines.append(f"**会议 ID**：`{meeting_id}`")
    if minute_token:
        lines.append(f"**妙记 token**：`{minute_token}`")
    if not report_ref:
        lines.append("未在按钮 value 或本地报告目录中找到报告路径，请检查本次发卡脚本是否开启 `--report-dir`。")
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "MeetFlow 完整复盘报告"},
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(lines)},
        ],
    }


def render_report_ref_markdown(report_ref: str) -> str:
    """渲染报告引用，外链可点击，本地路径只展示。"""

    clean = sanitize_callback_text(report_ref)
    if not clean:
        return "**报告位置**：未找到"
    lowered = clean.lower()
    if lowered.startswith(("https://", "http://", "lark://", "feishu://")):
        return f"**报告链接**：[打开完整报告]({clean})"
    return f"**本地报告路径**：`{clean}`"


def find_latest_post_meeting_report_path(settings: Settings, action_value: dict[str, Any]) -> str:
    """按 minute_token / meeting_id 在本地报告目录里寻找最近的 M4 Markdown 报告。"""

    storage_root = Path(settings.storage.db_path).parent
    report_root = storage_root / "reports" / "m4"
    if not report_root.exists():
        return ""
    minute_token = sanitize_callback_text(action_value.get("minute_token"))
    meeting_id = sanitize_callback_text(action_value.get("meeting_id"))
    patterns: list[str] = []
    if minute_token:
        patterns.append(f"**/post_meeting_live_{minute_token}_*.md")
    if meeting_id:
        patterns.append(f"**/post_meeting_live_*{meeting_id}*.md")
    patterns.append("**/post_meeting_live_*.md")
    for pattern in patterns:
        candidates = [path for path in report_root.glob(pattern) if path.is_file()]
        if candidates:
            latest = max(candidates, key=lambda path: path.stat().st_mtime)
            try:
                return str(latest.relative_to(Path.cwd()))
            except ValueError:
                return str(latest)
    return ""


def record_callback_risk_notifications(
    *,
    storage: MeetFlowStorage,
    decision: dict[str, Any],
    scan_result: dict[str, Any],
    recipient: str,
    now: int,
) -> None:
    """真实发送风险卡后记录降噪历史。"""

    if not hasattr(storage, "record_risk_notification"):
        return
    suppressed_until = now + 24 * 60 * 60
    for risk in decision.get("notify_risks", []):
        if not isinstance(risk, dict):
            continue
        task = risk.get("task", {}) if isinstance(risk.get("task"), dict) else {}
        storage.record_risk_notification(
            risk_key=str(risk.get("dedupe_key", "")),
            task_id=str(risk.get("task_id", "")),
            risk_type=str(risk.get("risk_type", "")),
            severity=str(risk.get("severity", "")),
            status="notified",
            trace_id=f"post_meeting_card_callback:{now}",
            recipient=recipient,
            summary=str(risk.get("reason", "")),
            payload={
                "title": task.get("title", ""),
                "scan_result_summary": scan_result.get("summary", ""),
            },
            notified_at=now,
            suppressed_until=suppressed_until,
        )


def record_source_message_id(record: dict[str, Any]) -> str:
    """读取 pending registry record 绑定的飞书消息 ID。"""

    source = record.get("source")
    if not isinstance(source, dict):
        return ""
    return str(source.get("message_id") or "").strip()


def record_value(record: dict[str, Any]) -> dict[str, Any]:
    """读取 pending registry record 中的按钮 value。"""

    value = record.get("value")
    return dict(value) if isinstance(value, dict) else {}


def first_non_empty_text(*values: Any) -> str:
    """返回第一个非空文本。"""

    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def deep_get(data: Any, *keys: str) -> Any:
    """读取嵌套 dict 字段，兼容飞书回调里 operator_id 的多种包裹。"""

    current = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current


def action_item_from_pending_record(record: dict[str, Any]) -> ActionItem:
    """把 pending registry record 转成聚合卡可渲染的 ActionItem。"""

    value = record_value(record)
    status = str(record.get("status") or "pending")
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    extra = value.get("extra") if isinstance(value.get("extra"), dict) else {}
    card_status, card_status_kind, card_status_message = pending_record_card_status(status, result)
    evidence_refs = []
    for ref in list(value.get("evidence_refs") or []):
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
    merged_extra = dict(extra)
    merged_extra.update(
        {
            "card_status": card_status,
            "card_status_kind": card_status_kind,
            "card_status_message": card_status_message,
            "task_url": extract_task_url_from_record_result(result),
        }
    )
    return ActionItem(
        item_id=str(value.get("item_id") or record.get("item_id") or ""),
        title=str(value.get("title") or "未命名任务"),
        owner=str(value.get("owner") or ""),
        due_date=str(value.get("due_date") or ""),
        priority=str(value.get("priority") or "medium"),
        confidence=float(value.get("confidence") or 0.0),
        needs_confirm=True,
        evidence_refs=evidence_refs,
        extra=merged_extra,
    )


def pending_record_card_status(status: str, result: dict[str, Any]) -> tuple[str, str, str]:
    """把 pending registry 状态映射成卡片展示状态。"""

    message = str(result.get("message") or "").strip()
    if status == "created":
        return "created", "success", message or "已创建任务。"
    if status == "reject_create_task":
        return "reject_create_task", "info", message or "已拒绝创建，MeetFlow 不会再自动落地这条任务。"
    if status == "creating":
        return "creating", "info", message or "正在创建任务。"
    if status == "rejecting":
        return "rejecting", "info", message or "正在拒绝创建任务。"
    if status == "pending" and result and str(result.get("status") or "") not in {"", "success"}:
        return "error", "error", message or "处理失败，请补充字段后重试。"
    return "pending", "info", ""


def extract_task_url_from_record_result(result: dict[str, Any]) -> str:
    """从 registry result 中提取已创建任务链接。"""

    task_mapping = result.get("task_mapping")
    if isinstance(task_mapping, dict):
        for key in ("task_url", "url"):
            value = str(task_mapping.get(key) or "").strip()
            if value:
                return value
    return ""


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
    merged = merge_action_values_preserving_cached(cached, action_value)
    return merged


def merge_action_values_preserving_cached(cached: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """合并卡片按钮值，同时避免旧卡空字段覆盖用户已保存的修改。

    飞书卡片更新后，用户可能仍点击到一张 callback value 中 owner/due_date 为空
    的按钮；但 pending registry 可能已经保存过旧卡片编辑阶段填写的字段。
    这里让非空的新值覆盖旧值，空字符串/空列表/空字典不覆盖已有业务值。
    """

    merged = dict(cached or {})
    for key, value in dict(incoming or {}).items():
        if is_empty_callback_value(value) and not is_empty_callback_value(merged.get(key)):
            continue
        merged[key] = value
    return merged


def is_empty_callback_value(value: Any) -> bool:
    """判断 callback 字段是否等价于空。"""

    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def guard_pending_action_transition(settings: Settings, action_value: dict[str, Any], action: str) -> CardCallbackResult | None:
    """拦截已处理任务的重复点击，避免旧卡片继续改写状态。"""

    item_id = str(action_value.get("item_id") or "")
    if not item_id:
        return None
    record = load_pending_action_records(settings).get(item_id)
    if not isinstance(record, dict):
        return None
    current_session = extract_record_review_session_id(record)
    action_session = str(action_value.get("review_session_id") or "").strip()
    if current_session and action_session and current_session != action_session:
        return CardCallbackResult(status="info", message="这是一张旧的待确认卡，请使用群里最新发送的卡片。")
    return build_transition_guard_result(settings, item_id, str(record.get("status") or "pending"))


def extract_record_review_session_id(record: dict[str, Any]) -> str:
    """从 registry record 中读取确认会话 ID。"""

    value = record.get("value") if isinstance(record.get("value"), dict) else {}
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    return str(value.get("review_session_id") or source.get("review_session_id") or "").strip()


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


def sync_review_session_audit(
    *,
    storage: MeetFlowStorage,
    settings: Settings,
    action_value: dict[str, Any],
) -> None:
    """把 M4 卡片确认批次同步到 SQLite 审计表。

    真实群聊里同一妙记可能重复发卡。JSON registry 负责当前状态判断，
    SQLite review_sessions 负责把“这一批卡片确认到了哪一步”变成可查询事实。
    """

    review_session_id = str(action_value.get("review_session_id") or "").strip()
    if not review_session_id:
        return
    records = load_pending_action_records(settings)
    related_records = [
        record
        for record in records.values()
        if isinstance(record, dict) and extract_record_review_session_id(record) == review_session_id
    ]
    pending_count = sum(1 for record in related_records if str(record.get("status") or "pending") == "pending")
    created_count = sum(1 for record in related_records if str(record.get("status") or "") == "created")
    rejected_count = sum(1 for record in related_records if str(record.get("status") or "") == "reject_create_task")
    if related_records and pending_count == 0:
        status = "completed"
    else:
        status = "pending"
    storage.save_review_session(
        review_session_id=review_session_id,
        workflow_type="post_meeting_followup",
        meeting_id=str(action_value.get("meeting_id") or ""),
        minute_token=str(action_value.get("minute_token") or ""),
        chat_id=str(action_value.get("chat_id") or ""),
        status=status,
        pending_count=pending_count,
        created_count=created_count,
        rejected_count=rejected_count,
        payload={
            "item_id": action_value.get("item_id", ""),
            "latest_action": action_value.get("action", ""),
            "related_record_count": len(related_records),
        },
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
