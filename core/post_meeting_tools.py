from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any

from adapters.feishu_client import FeishuClient, IdentityMode
from cards.post_meeting import (
    build_pending_action_items_card,
    build_pending_task_button_value,
    build_post_meeting_summary_card,
)
from core.confirmation_commands import load_json_object, write_json_object
from core.knowledge import KnowledgeIndexStore
from core.models import ActionItem, EvidenceRef, Resource, WorkflowContext
from core.post_meeting import (
    PostMeetingInput,
    build_post_meeting_artifacts_from_input,
    build_task_create_arguments,
    enrich_post_meeting_related_resources,
    is_group_owner_candidate,
    is_invalid_owner_candidate,
    merge_d3_review_fields,
)
from core.storage import MeetFlowStorage
from core.tools import AgentTool, ToolRegistry


def register_post_meeting_tools(
    registry: ToolRegistry,
    storage: MeetFlowStorage | None = None,
    knowledge_store: KnowledgeIndexStore | None = None,
    client: FeishuClient | None = None,
    default_chat_id: str = "",
    timezone: str = "Asia/Shanghai",
) -> None:
    """注册 M4 会后 Agent 工具。

    这些工具把 M4 的确定性能力暴露给 Agent Loop：模型可以选择何时构造
    artifacts、何时补充 RAG、何时准备任务参数，以及何时发卡或保存待确认
    registry。真正的写操作仍由 `ToolRegistry` 统一执行，并在执行前经过
    `AgentPolicy.authorize_tool_call()`。
    """

    registry.register(_build_post_meeting_build_artifacts_tool())
    registry.register(_build_post_meeting_enrich_related_knowledge_tool(knowledge_store))
    registry.register(_build_post_meeting_prepare_task_tool(timezone=timezone))
    registry.register(_build_post_meeting_send_summary_card_tool(client, default_chat_id=default_chat_id))
    registry.register(_build_post_meeting_save_pending_actions_tool(storage, client=client))


def _build_post_meeting_build_artifacts_tool() -> AgentTool:
    """把妙记资源或显式输入转换为 M4 artifacts。"""

    return AgentTool(
        internal_name="post_meeting.build_artifacts",
        description=(
            "根据妙记资源、纪要文本或 post_meeting_input 构造会后结构化 artifacts，"
            "包含 cleaned_transcript、meeting_summary、action_items、pending_action_items 和 card_payloads。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "post_meeting_input": {"type": "object", "description": "可选的 M4 输入结构。"},
                "minute_resource": {"type": "object", "description": "minutes.fetch_resource 返回的 Resource 结构。"},
                "raw_text": {"type": "string", "description": "纪要全文；优先级高于 minute_resource.content。"},
                "minute": {"type": "string", "description": "妙记 token 或 URL。"},
                "meeting_id": {"type": "string"},
                "calendar_event_id": {"type": "string"},
                "project_id": {"type": "string"},
                "topic": {"type": "string"},
                "source_url": {"type": "string"},
            },
            "required": [],
        },
        handler=lambda **arguments: build_post_meeting_artifacts_tool_result(arguments),
        read_only=True,
    )


def _build_post_meeting_enrich_related_knowledge_tool(
    knowledge_store: KnowledgeIndexStore | None,
) -> AgentTool:
    """注册会后 RAG 背景补充工具。"""

    return AgentTool(
        internal_name="post_meeting.enrich_related_knowledge",
        description=(
            "用 M3 知识库为 M4 artifacts 补充相关背景资料。只构造短 query 检索项目文档，"
            "不会把整篇妙记全文向量化。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "artifacts": {"type": "object", "description": "post_meeting.build_artifacts 返回的 artifacts。"},
                "top_n": {"type": "integer", "description": "最多返回去重后的相关资料数。"},
            },
            "required": ["artifacts"],
        },
        handler=lambda artifacts, top_n=5, **_: enrich_related_knowledge_tool_result(
            artifacts=artifacts,
            knowledge_store=knowledge_store,
            top_n=top_n,
        ),
        read_only=True,
    )


def _build_post_meeting_prepare_task_tool(timezone: str) -> AgentTool:
    """注册行动项转任务创建参数工具。"""

    default_timezone = timezone
    return AgentTool(
        internal_name="post_meeting.prepare_task",
        description=(
            "把人工确认后的 Action Item 转为 tasks.create_task 参数草案。assignee_ids 必须来自"
            " contact.get_current_user 或 contact.search_user，不能使用姓名文本冒充 open_id。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action_item": {"type": "object", "description": "M4 action item。"},
                "assignee_ids": {"type": "array", "items": {"type": "string"}, "description": "已解析的负责人 open_id。"},
                "context": {"type": "object", "description": "可选会议上下文。"},
                "timezone": {"type": "string", "description": "用于解析中文截止时间的时区。"},
            },
            "required": ["action_item"],
        },
        handler=lambda action_item, assignee_ids=None, context=None, timezone="", **_: prepare_task_tool_result(
            action_item=action_item,
            assignee_ids=assignee_ids or [],
            context=context or {},
            timezone=timezone or default_timezone,
        ),
        read_only=True,
    )


def _build_post_meeting_send_summary_card_tool(
    client: FeishuClient | None,
    default_chat_id: str,
) -> AgentTool:
    """注册会后总结卡发送工具。"""

    return AgentTool(
        internal_name="post_meeting.send_summary_card",
        description=(
            "发送 M4 会后总结卡。该工具固定发送 summary_card 到测试群，并使用机器人身份；"
            "待确认任务卡只能由会后总结卡的“查看任务卡”按钮触发发送。"
            "写操作必须携带 idempotency_key 并经过 AgentPolicy。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "artifacts": {"type": "object", "description": "M4 artifacts。"},
                "card_type": {"type": "string", "description": "兼容旧参数；本工具始终发送 summary_card。"},
                "receive_id": {"type": "string"},
                "receive_id_type": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "identity": {"type": "string", "description": "兼容旧参数；本工具始终使用 tenant/机器人身份。"},
            },
            "required": ["artifacts"],
        },
        handler=lambda artifacts, card_type="summary_card", receive_id="", receive_id_type="chat_id", idempotency_key="", identity="tenant", **_: send_post_meeting_card_tool_result(
            client=client,
            default_chat_id=default_chat_id,
            artifacts=artifacts,
            card_type=card_type,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            idempotency_key=idempotency_key,
            identity=identity,
        ),
        read_only=False,
        side_effect="send_message",
    )


def _build_post_meeting_save_pending_actions_tool(
    storage: MeetFlowStorage | None,
    client: FeishuClient | None,
) -> AgentTool:
    """注册待确认任务 registry 保存工具。"""

    return AgentTool(
        internal_name="post_meeting.save_pending_actions",
        description=(
            "保存 pending_action_items 到本地 registry，供卡片按钮回调、消息 watcher 和恢复脚本复用待确认上下文。"
            "写操作，必须携带 idempotency_key 并经过 AgentPolicy。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "artifacts": {"type": "object", "description": "M4 artifacts。"},
                "source": {"type": "object", "description": "来源信息，例如 chat_id、minute_token、trace_id。"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["artifacts"],
        },
        handler=lambda artifacts, source=None, idempotency_key="", **_: save_pending_actions_tool_result(
            storage=storage,
            client=client,
            artifacts=artifacts,
            source=source or {},
            idempotency_key=idempotency_key,
        ),
        read_only=False,
        side_effect="save_pending_actions",
    )


def build_post_meeting_artifacts_tool_result(arguments: dict[str, Any]) -> dict[str, Any]:
    """工具实现：构造 artifacts 并额外给 Agent 摘出待人工审核候选。"""

    workflow_input = post_meeting_input_from_arguments(arguments)
    artifacts = build_post_meeting_artifacts_from_input(workflow_input)
    return {
        "artifacts": artifacts.to_dict(),
        "auto_create_candidates": [item.to_dict() for item in artifacts.action_items if not item.needs_confirm],
        "human_review_candidates": [item.to_dict() for item in artifacts.pending_action_items],
        "pending_action_items": [item.to_dict() for item in artifacts.pending_action_items],
        "summary": {
            "topic": artifacts.meeting_summary.topic,
            "decision_count": len(artifacts.decisions),
            "open_question_count": len(artifacts.open_questions),
            "action_item_count": len(artifacts.action_items),
            "pending_action_item_count": len(artifacts.pending_action_items),
            "task_creation_requires_human_confirmation": True,
        },
    }


def enrich_related_knowledge_tool_result(
    artifacts: dict[str, Any],
    knowledge_store: KnowledgeIndexStore | None,
    top_n: int,
) -> dict[str, Any]:
    """工具实现：为 artifacts 补充相关知识；无知识库时返回可解释降级结果。"""

    if knowledge_store is None:
        return {
            "status": "skipped",
            "reason": "未装配 KnowledgeIndexStore，跳过会后背景资料召回。",
            "artifacts": artifacts,
            "related_knowledge": [],
        }
    rebuilt = build_post_meeting_artifacts_from_input(post_meeting_input_from_artifacts(artifacts))
    enriched = enrich_post_meeting_related_resources(rebuilt, knowledge_store=knowledge_store, top_n=int(top_n or 5))
    return {
        "status": enriched.extra.get("related_knowledge_status", "unknown"),
        "query": enriched.extra.get("related_knowledge_query", ""),
        "query_plan": enriched.extra.get("related_knowledge_query_plan", {}),
        "reason": enriched.extra.get("related_knowledge_reason", ""),
        "related_knowledge": enriched.extra.get("related_knowledge_hits", []),
        "artifacts": enriched.to_dict(),
    }


def prepare_task_tool_result(
    action_item: dict[str, Any],
    assignee_ids: list[Any],
    context: dict[str, Any],
    timezone: str,
) -> dict[str, Any]:
    """工具实现：把 Action Item 转成任务创建参数草案。"""

    task_arguments = build_task_create_arguments(
        action_item=action_item_from_dict(action_item),
        context=workflow_context_from_dict(context or {}),
        assignee_ids=[str(item) for item in (assignee_ids or []) if item],
        timezone=timezone or "Asia/Shanghai",
    )
    return {"task_arguments": task_arguments}


def send_post_meeting_card_tool_result(
    client: FeishuClient | None,
    default_chat_id: str,
    artifacts: dict[str, Any],
    card_type: str,
    receive_id: str,
    receive_id_type: str,
    idempotency_key: str,
    identity: str,
) -> dict[str, Any]:
    """工具实现：发送 M4 卡片；本地模式返回 dry-run 结构。"""

    artifacts = ensure_complete_post_meeting_artifacts(artifacts, client=client)
    artifacts = resolve_task_owner_candidates_for_artifacts(artifacts, client=client)
    card_payloads = artifacts.get("card_payloads") if isinstance(artifacts, dict) else {}
    if not isinstance(card_payloads, dict):
        card_payloads = {}
    # 这个工具名和 Agent 暴露语义都是“发送会后总结卡”。真实 D4 任务卡
    # 需要用户点击总结卡上的“查看任务卡”后由回调发送，不能让模型在主
    # 链路里直接选择 pending_card，否则会出现空任务卡、用户身份私聊等
    # 演示不可控行为。
    requested_card_type = card_type if card_type in {"summary_card", "pending_card"} else "summary_card"
    selected_card_type = "summary_card"
    card = card_payloads.get(selected_card_type)
    if not isinstance(card, dict):
        rebuilt = build_post_meeting_artifacts_from_input(post_meeting_input_from_artifacts(artifacts))
        card = rebuilt.card_payloads.get(selected_card_type, {})
    if not isinstance(card, dict) or not card:
        raise ValueError(f"未找到可发送的 M4 卡片 payload：{selected_card_type}")

    final_receive_id = receive_id if receive_id_type == "chat_id" and str(receive_id).startswith("oc_") else default_chat_id
    if client is None:
        return {
            "sent": False,
            "dry_run": True,
            "card_type": selected_card_type,
            "requested_card_type": requested_card_type,
            "receive_id": final_receive_id,
            "idempotency_key": idempotency_key,
            "card_title": card.get("header", {}).get("title", {}).get("content", ""),
        }
    if not final_receive_id:
        raise ValueError("发送会后卡片需要 receive_id 或默认测试群 default_chat_id")
    result = client.send_card_message(
        receive_id=final_receive_id,
        card=card,
        receive_id_type="chat_id",
        idempotency_key=idempotency_key,
        identity="tenant",
    )
    return {
        "sent": True,
        "card_type": selected_card_type,
        "requested_card_type": requested_card_type,
        "receive_id": final_receive_id,
        "idempotency_key": idempotency_key,
        "result": result,
    }


def save_pending_actions_tool_result(
    storage: MeetFlowStorage | None,
    client: FeishuClient | None,
    artifacts: dict[str, Any],
    source: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    """工具实现：保存待确认 Action Item 的本地恢复上下文。"""

    artifacts = ensure_complete_post_meeting_artifacts(artifacts, client=client)
    artifacts = resolve_task_owner_candidates_for_artifacts(artifacts, client=client)
    if storage is None:
        return {
            "saved": False,
            "dry_run": True,
            "reason": "未装配 MeetFlowStorage，跳过 registry 写入。",
            "idempotency_key": idempotency_key,
        }
    pending_items = artifacts.get("pending_action_items") if isinstance(artifacts, dict) else []
    if not isinstance(pending_items, list):
        pending_items = []
    values = [build_pending_task_button_value(action_item_from_dict(item)) for item in pending_items if isinstance(item, dict)]
    path = storage.db_path.parent / "post_meeting_pending_actions.json"
    save_pending_action_values_to_path(path=path, action_values=values, source=source)
    return {
        "saved": True,
        "path": str(path),
        "count": len(values),
        "item_ids": [value.get("item_id", "") for value in values],
        "idempotency_key": idempotency_key,
    }


def ensure_complete_post_meeting_artifacts(
    artifacts: dict[str, Any],
    client: FeishuClient | None,
) -> dict[str, Any]:
    """确保发卡/保存前拿到完整 M4 artifacts。

    真实 LLM 在多轮工具调用后，可能只把 workflow_input 或空的
    action_items/pending_action_items 传给写工具。写工具不能直接相信这个
    “空壳 artifacts”，否则会发出 0 结论/0 行动项的空会后卡。这里在发现
    artifacts 缺少结构化产物但仍有 minute_token 时，回源读取妙记并重新构建
    D3/D4 artifacts，保证自动监听和手动直发使用同一套确定性抽取逻辑。
    """

    if not isinstance(artifacts, dict):
        return artifacts
    if artifacts_has_post_meeting_content(artifacts):
        return artifacts
    minute_token = extract_minute_token_from_artifacts(artifacts)
    if not minute_token or client is None:
        return artifacts
    try:
        resource = client.fetch_minute_resource(minute=minute_token, include_artifacts=True, identity="user")
    except Exception:
        return artifacts
    workflow_input = artifacts.get("workflow_input") if isinstance(artifacts.get("workflow_input"), dict) else {}
    rebuilt = build_post_meeting_artifacts_from_input(
        post_meeting_input_from_arguments(
            {
                "minute_resource": resource.to_dict(),
                "minute": minute_token,
                "meeting_id": workflow_input.get("meeting_id") or minute_token,
                "calendar_event_id": workflow_input.get("calendar_event_id") or "",
                "project_id": workflow_input.get("project_id") or "meetflow",
                "topic": workflow_input.get("topic") or resource.title,
                "source_url": workflow_input.get("source_url") or resource.source_url,
            }
        )
    )
    rebuilt.extra.update(dict(artifacts.get("extra") or {}))
    merge_d3_review_fields(rebuilt)
    rebuilt.card_payloads["summary_card"] = build_post_meeting_summary_card(rebuilt)
    rebuilt.card_payloads["pending_card"] = build_pending_action_items_card(rebuilt)
    return rebuilt.to_dict()


def artifacts_has_post_meeting_content(artifacts: dict[str, Any]) -> bool:
    """判断 artifacts 是否已经包含可用于会后卡片的结构化内容。"""

    for key in ("action_items", "pending_action_items", "decisions", "risks", "evidence_pack"):
        value = artifacts.get(key)
        if isinstance(value, list) and value:
            return True
        if isinstance(value, dict) and value.get("items"):
            return True
    workflow_input = artifacts.get("workflow_input")
    return isinstance(workflow_input, dict) and bool(str(workflow_input.get("raw_text") or "").strip())


def extract_minute_token_from_artifacts(artifacts: dict[str, Any]) -> str:
    """从不完整 artifacts 中尽力提取妙记 token。"""

    workflow_input = artifacts.get("workflow_input") if isinstance(artifacts.get("workflow_input"), dict) else {}
    candidates = [
        workflow_input.get("minute_token"),
        workflow_input.get("source_id"),
        workflow_input.get("source_url"),
        artifacts.get("minute_token"),
        artifacts.get("source_id"),
        artifacts.get("source_url"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        if "/minutes/" in text:
            return text.rsplit("/minutes/", 1)[-1].split("?", 1)[0].split("#", 1)[0].strip("/")
        if text.startswith("obcn"):
            return text
    return ""


def resolve_task_owner_candidates_for_artifacts(
    artifacts: dict[str, Any],
    client: FeishuClient | None,
) -> dict[str, Any]:
    """在发卡/保存前把负责人候选名解析为真实飞书用户。

    妙记抽取出的 `owner` 只是文本候选。D4 的展示规则要求：只有通讯录能
    唯一确认到用户时，任务卡才展示负责人并携带 open_id；查不到、多人同名
    或候选本身是时间词/群体称呼时，都保持“待补充”。
    """

    if not isinstance(artifacts, dict):
        return artifacts
    resolved = copy.deepcopy(artifacts)
    if client is None:
        return resolved

    stats = {
        "attempted_count": 0,
        "resolved_count": 0,
        "not_found_count": 0,
        "ambiguous_count": 0,
        "invalid_count": 0,
        "error_count": 0,
    }
    cache: dict[str, dict[str, Any]] = {}
    for section in ("action_items", "pending_action_items"):
        items = resolved.get(section)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            resolution = resolve_task_owner_candidate(item, client=client, cache=cache)
            apply_task_owner_resolution(item, resolution)
            update_owner_resolution_stats(stats, resolution)

    extra = dict(resolved.get("extra") or {})
    extra["owner_resolution_summary"] = stats
    resolved["extra"] = extra
    return rebuild_post_meeting_artifacts_payloads(resolved)


def resolve_task_owner_candidate(
    item: dict[str, Any],
    client: FeishuClient,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """解析单条任务的负责人候选，返回可写入 `ActionItem.extra` 的结果。"""

    extra = dict(item.get("extra") or {})
    existing_open_id = str(extra.get("owner_open_id") or extra.get("assignee_open_id") or "").strip()
    owner_text = str(item.get("owner") or extra.get("owner_candidate") or "").strip()
    if existing_open_id:
        return {
            "status": "resolved",
            "source": str(extra.get("owner_resolution_source") or "existing_extra"),
            "owner_candidate": owner_text,
            "open_id": existing_open_id,
            "user_id": str(extra.get("owner_user_id") or ""),
            "display_name": str(extra.get("owner_display_name") or owner_text),
            "candidate_count": 1,
        }
    if not owner_text or is_group_owner_candidate(owner_text) or is_invalid_owner_candidate(owner_text):
        return {
            "status": "invalid_candidate" if owner_text else "missing",
            "source": "local_validation",
            "owner_candidate": owner_text,
            "candidate_count": 0,
        }
    if owner_text in cache:
        return dict(cache[owner_text])

    try:
        if owner_text in {"我", "本人", "自己"}:
            resolution = resolve_current_user_owner(client, owner_text)
        else:
            resolution = resolve_named_owner(client, owner_text)
    except Exception as error:  # noqa: BLE001 - 可选解析失败时保留原因并降级为待补充。
        resolution = {
            "status": "error",
            "source": "contact.search_user",
            "owner_candidate": owner_text,
            "candidate_count": 0,
            "error": str(error)[:240],
        }
    cache[owner_text] = dict(resolution)
    return resolution


def resolve_current_user_owner(client: FeishuClient, owner_text: str) -> dict[str, Any]:
    """解析“我/本人/自己”为当前登录用户。"""

    data = client.get_current_user_info()
    open_id = first_user_identifier(data, keys=("open_id", "user_id", "union_id", "id"))
    if not open_id:
        return {
            "status": "not_found",
            "source": "contact.get_current_user",
            "owner_candidate": owner_text,
            "candidate_count": 0,
        }
    return {
        "status": "resolved",
        "source": "contact.get_current_user",
        "owner_candidate": owner_text,
        "open_id": open_id,
        "user_id": str(data.get("user_id") or ""),
        "display_name": user_display_name(data) or owner_text,
        "candidate_count": 1,
    }


def resolve_named_owner(client: FeishuClient, owner_text: str) -> dict[str, Any]:
    """通过飞书通讯录解析姓名，只有唯一可信候选才算解析成功。"""

    data = client.search_users(query=owner_text, page_size=5, identity="user")
    candidates = normalize_user_candidates(data)
    if not candidates:
        return {
            "status": "not_found",
            "source": "contact.search_user",
            "owner_candidate": owner_text,
            "candidate_count": 0,
        }
    exact_candidates = [candidate for candidate in candidates if user_candidate_matches(owner_text, candidate)]
    selected = exact_candidates[0] if len(exact_candidates) == 1 else candidates[0] if len(candidates) == 1 else {}
    if not selected:
        return {
            "status": "ambiguous",
            "source": "contact.search_user",
            "owner_candidate": owner_text,
            "candidate_count": len(candidates),
            "candidate_names": [candidate.get("display_name", "") for candidate in candidates[:5]],
        }
    open_id = str(selected.get("open_id") or "").strip()
    if not open_id:
        return {
            "status": "not_found",
            "source": "contact.search_user",
            "owner_candidate": owner_text,
            "candidate_count": len(candidates),
        }
    return {
        "status": "resolved",
        "source": "contact.search_user",
        "owner_candidate": owner_text,
        "open_id": open_id,
        "user_id": str(selected.get("user_id") or ""),
        "display_name": str(selected.get("display_name") or owner_text),
        "candidate_count": len(candidates),
    }


def normalize_user_candidates(data: dict[str, Any]) -> list[dict[str, str]]:
    """兼容飞书搜索接口可能返回的候选列表字段名。"""

    raw_items = data.get("items") or data.get("users") or data.get("user_list") or []
    if not isinstance(raw_items, list):
        return []
    candidates: list[dict[str, str]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        open_id = first_user_identifier(raw, keys=("open_id", "user_id", "id"))
        if not open_id:
            continue
        candidates.append(
            {
                "open_id": open_id,
                "user_id": str(raw.get("user_id") or ""),
                "display_name": user_display_name(raw),
                "name": str(raw.get("name") or ""),
                "en_name": str(raw.get("en_name") or ""),
                "email": str(raw.get("email") or ""),
            }
        )
    return candidates


def user_candidate_matches(query: str, candidate: dict[str, str]) -> bool:
    """判断搜索结果是否和负责人文本精确匹配。"""

    normalized_query = normalize_user_match_text(query)
    return any(
        normalize_user_match_text(candidate.get(field, "")) == normalized_query
        for field in ("display_name", "name", "en_name", "email")
        if candidate.get(field)
    )


def normalize_user_match_text(value: str) -> str:
    """归一化姓名/邮箱匹配文本。"""

    return str(value or "").strip().lower().replace(" ", "")


def user_display_name(data: dict[str, Any]) -> str:
    """从飞书用户对象中提取可展示姓名。"""

    return str(
        data.get("name")
        or data.get("display_name")
        or data.get("en_name")
        or data.get("email")
        or ""
    ).strip()


def first_user_identifier(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    """从用户对象中读取第一个非空 ID。"""

    for key in keys:
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def apply_task_owner_resolution(item: dict[str, Any], resolution: dict[str, Any]) -> None:
    """把负责人解析结果写回 action item 字典。"""

    extra = dict(item.get("extra") or {})
    owner_candidate = str(resolution.get("owner_candidate") or item.get("owner") or "").strip()
    if owner_candidate:
        extra["owner_candidate"] = owner_candidate
    status = str(resolution.get("status") or "")
    extra["owner_resolution_status"] = status
    extra["owner_resolution_source"] = str(resolution.get("source") or "")
    extra["owner_resolution_candidate_count"] = int(resolution.get("candidate_count") or 0)
    if resolution.get("error"):
        extra["owner_resolution_error"] = str(resolution.get("error") or "")
    if status == "ambiguous":
        extra["owner_resolution_candidates"] = list(resolution.get("candidate_names") or [])
    if status == "resolved":
        display_name = str(resolution.get("display_name") or owner_candidate).strip()
        extra["owner_open_id"] = str(resolution.get("open_id") or "")
        if resolution.get("user_id"):
            extra["owner_user_id"] = str(resolution.get("user_id") or "")
        if display_name:
            extra["owner_display_name"] = display_name
            item["owner"] = display_name
        extra["missing_fields"] = remove_owner_missing_fields(extra.get("missing_fields"))
    item["extra"] = extra


def remove_owner_missing_fields(fields: Any) -> list[str]:
    """负责人已解析后，移除展示层不再需要的负责人缺字段标记。"""

    return [
        str(field)
        for field in list(fields or [])
        if str(field) not in {"owner", "owner_resolution"}
    ]


def update_owner_resolution_stats(stats: dict[str, int], resolution: dict[str, Any]) -> None:
    """累计负责人解析摘要，便于报告和排查。"""

    status = str(resolution.get("status") or "")
    if status in {"missing", "resolved"} and resolution.get("source") == "existing_extra":
        return
    if status not in {"missing", ""}:
        stats["attempted_count"] += 1
    if status == "resolved":
        stats["resolved_count"] += 1
    elif status == "not_found":
        stats["not_found_count"] += 1
    elif status == "ambiguous":
        stats["ambiguous_count"] += 1
    elif status == "invalid_candidate":
        stats["invalid_count"] += 1
    elif status == "error":
        stats["error_count"] += 1


def rebuild_post_meeting_artifacts_payloads(artifacts: dict[str, Any]) -> dict[str, Any]:
    """用解析后的 action items 重建 D4 分析包和卡片 payload。"""

    return rebuild_post_meeting_artifacts_object(artifacts).to_dict()


def rebuild_post_meeting_artifacts_object(artifacts: dict[str, Any]) -> Any:
    """从 artifacts 字典恢复对象，并重建 D3/D4 展示字段和卡片。"""

    rebuilt = build_post_meeting_artifacts_from_input(post_meeting_input_from_artifacts(artifacts))
    rebuilt.extra.update(dict(artifacts.get("extra") or {}))
    action_items = artifacts.get("action_items")
    pending_items = artifacts.get("pending_action_items")
    if isinstance(action_items, list) and action_items:
        rebuilt.action_items = [action_item_from_dict(item) for item in action_items if isinstance(item, dict)]
    if isinstance(pending_items, list) and pending_items:
        rebuilt.pending_action_items = [action_item_from_dict(item) for item in pending_items if isinstance(item, dict)]
    elif isinstance(action_items, list) and action_items:
        rebuilt.pending_action_items = [item for item in rebuilt.action_items if item.needs_confirm]
    merge_d3_review_fields(rebuilt)
    rebuilt.card_payloads["summary_card"] = build_post_meeting_summary_card(rebuilt)
    rebuilt.card_payloads["pending_card"] = build_pending_action_items_card(rebuilt)
    return rebuilt


def post_meeting_input_from_arguments(arguments: dict[str, Any]) -> PostMeetingInput:
    """从工具参数归一化 M4 输入。"""

    explicit_input = arguments.get("post_meeting_input")
    if isinstance(explicit_input, dict) and explicit_input:
        base = dict(explicit_input)
    else:
        base = {}

    minute_resource = arguments.get("minute_resource")
    resource = resource_from_dict(minute_resource) if isinstance(minute_resource, dict) else None
    raw_text = str(arguments.get("raw_text") or base.get("raw_text") or "")
    if not raw_text and resource:
        raw_text = resource.content

    related_resources = [resource] if resource else resources_from_list(base.get("related_resources"))
    minute = str(arguments.get("minute") or base.get("minute_token") or "")
    return PostMeetingInput(
        meeting_id=str(arguments.get("meeting_id") or base.get("meeting_id") or ""),
        calendar_event_id=str(arguments.get("calendar_event_id") or base.get("calendar_event_id") or ""),
        minute_token=minute,
        project_id=str(arguments.get("project_id") or base.get("project_id") or "meetflow"),
        topic=str(arguments.get("topic") or base.get("topic") or (resource.title if resource else "")),
        source_type=str(base.get("source_type") or (resource.resource_type if resource else "minute")),
        source_id=str(base.get("source_id") or (resource.resource_id if resource else minute)),
        source_url=str(arguments.get("source_url") or base.get("source_url") or (resource.source_url if resource else "")),
        raw_text=raw_text,
        participants=list(base.get("participants") or []),
        related_resources=related_resources,
        memory_snapshot=dict(base.get("memory_snapshot") or {}),
        raw_payload=dict(base.get("raw_payload") or {}),
        extra=dict(base.get("extra") or {}),
    )


def post_meeting_input_from_artifacts(artifacts: dict[str, Any]) -> PostMeetingInput:
    """从 artifacts 字典恢复 workflow_input。"""

    workflow_input = artifacts.get("workflow_input") if isinstance(artifacts, dict) else {}
    if not isinstance(workflow_input, dict):
        workflow_input = {}
    return post_meeting_input_from_arguments({"post_meeting_input": workflow_input})


def resource_from_dict(data: dict[str, Any]) -> Resource:
    """从工具 JSON 恢复 Resource。"""

    return Resource(
        resource_id=str(data.get("resource_id") or data.get("id") or ""),
        resource_type=str(data.get("resource_type") or data.get("type") or "minute"),
        title=str(data.get("title") or "未命名资源"),
        content=str(data.get("content") or data.get("text") or data.get("summary") or ""),
        source_url=str(data.get("source_url") or data.get("url") or ""),
        source_meta=dict(data.get("source_meta") or {}),
        updated_at=str(data.get("updated_at") or ""),
    )


def resources_from_list(items: Any) -> list[Resource]:
    """从 JSON 列表恢复 Resource 列表。"""

    if not isinstance(items, list):
        return []
    return [resource_from_dict(item) for item in items if isinstance(item, dict)]


def action_item_from_dict(data: dict[str, Any]) -> ActionItem:
    """从工具 JSON 恢复 ActionItem。"""

    evidence_refs = [
        EvidenceRef(
            source_type=str(ref.get("source_type") or ""),
            source_id=str(ref.get("source_id") or ""),
            source_url=str(ref.get("source_url") or ""),
            snippet=str(ref.get("snippet") or ""),
            updated_at=str(ref.get("updated_at") or ""),
        )
        for ref in list(data.get("evidence_refs") or [])
        if isinstance(ref, dict)
    ]
    return ActionItem(
        item_id=str(data.get("item_id") or ""),
        title=str(data.get("title") or ""),
        owner=str(data.get("owner") or ""),
        due_date=str(data.get("due_date") or ""),
        priority=str(data.get("priority") or "medium"),
        status=str(data.get("status") or "todo"),
        confidence=float(data.get("confidence") or 0.0),
        needs_confirm=bool(data.get("needs_confirm", False)),
        evidence_refs=evidence_refs,
        extra=dict(data.get("extra") or {}),
    )


def workflow_context_from_dict(data: dict[str, Any]) -> WorkflowContext | None:
    """恢复构造任务描述所需的最小 WorkflowContext。"""

    if not data:
        return None
    return WorkflowContext(
        workflow_type=str(data.get("workflow_type") or "post_meeting_followup"),
        trace_id=str(data.get("trace_id") or "-"),
        meeting_id=str(data.get("meeting_id") or ""),
        calendar_event_id=str(data.get("calendar_event_id") or ""),
        minute_token=str(data.get("minute_token") or ""),
        project_id=str(data.get("project_id") or "meetflow"),
    )


def save_pending_action_values_to_path(
    path: Path,
    action_values: list[dict[str, Any]],
    source: dict[str, Any],
) -> None:
    """保存待确认任务上下文到指定 registry 文件。"""

    if not action_values:
        return
    data = load_json_object(path)
    now = int(time.time())
    for value in action_values:
        item_id = str(value.get("item_id") or "").strip()
        if not item_id:
            continue
        existing = data.get(item_id, {})
        existing_value = dict(existing.get("value") or {}) if isinstance(existing, dict) else {}
        existing_value.update(value)
        data[item_id] = {
            "item_id": item_id,
            "value": existing_value,
            "source": dict(source or {}),
            "status": existing.get("status", "pending") if isinstance(existing, dict) else "pending",
            "created_at": existing.get("created_at", now) if isinstance(existing, dict) else now,
            "updated_at": now,
        }
    write_json_object(path, data)


def normalize_identity(identity: Any) -> IdentityMode | None:
    """规范化飞书身份。"""

    return identity if identity in {"user", "tenant"} else None
