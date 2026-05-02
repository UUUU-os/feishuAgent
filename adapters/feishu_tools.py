from __future__ import annotations

from typing import Any

from adapters.feishu_client import FeishuAPIError, FeishuClient, IdentityMode
from core.models import ActionItem
from core.tools import AgentTool, ToolRegistry


def create_feishu_tool_registry(
    client: FeishuClient,
    default_chat_id: str = "",
) -> ToolRegistry:
    """创建包含首批飞书工具的 Tool Registry。

    注意：这里只负责注册工具，不会主动调用飞书 API。
    真正执行发生在 `ToolRegistry.execute()` 收到 LLM 的 tool call 之后。
    """

    registry = ToolRegistry()
    registry.register(_build_calendar_list_events_tool(client))
    registry.register(_build_docs_fetch_resource_tool(client))
    registry.register(_build_minutes_fetch_resource_tool(client))
    registry.register(_build_tasks_list_my_tasks_tool(client))
    registry.register(_build_tasks_create_task_tool(client))
    registry.register(_build_contact_get_current_user_tool(client))
    registry.register(_build_contact_search_user_tool(client))
    registry.register(_build_im_send_text_tool(client, default_chat_id=default_chat_id))
    registry.register(_build_im_send_card_tool(client, default_chat_id=default_chat_id))
    return registry


def _build_calendar_list_events_tool(client: FeishuClient) -> AgentTool:
    """注册日历事件查询工具。"""

    return AgentTool(
        internal_name="calendar.list_events",
        description="查询指定时间范围内的飞书日历事件，返回统一 CalendarEvent 列表。",
        parameters={
            "type": "object",
            "properties": {
                "calendar_id": {"type": "string", "description": "日历 ID，主日历可传 primary。"},
                "start_time": {"type": "string", "description": "开始时间，Unix 秒级时间戳。"},
                "end_time": {"type": "string", "description": "结束时间，Unix 秒级时间戳。"},
                "identity": {"type": "string", "description": "飞书身份，可选 user 或 tenant。"},
            },
            "required": ["calendar_id", "start_time", "end_time"],
        },
        handler=lambda calendar_id, start_time, end_time, identity="user", **_: client.list_calendar_event_instances(
            calendar_id=calendar_id,
            start_time=start_time,
            end_time=end_time,
            identity=_normalize_identity(identity),
        ),
        read_only=True,
    )


def _build_docs_fetch_resource_tool(client: FeishuClient) -> AgentTool:
    """注册飞书文档读取工具。"""

    return AgentTool(
        internal_name="docs.fetch_resource",
        description="读取飞书文档内容，并转换为统一 Resource。",
        parameters={
            "type": "object",
            "properties": {
                "document": {"type": "string", "description": "飞书文档 URL、token 或 document_id。"},
                "doc_format": {"type": "string", "description": "文档格式：xml、markdown 或 text。"},
                "detail": {"type": "string", "description": "读取详细度：simple、with-ids 或 full。"},
                "scope": {"type": "string", "description": "读取范围：full、outline、range、keyword、section。"},
                "keyword": {"type": "string", "description": "scope=keyword 时使用的关键词。"},
                "identity": {"type": "string", "description": "飞书身份，可选 user 或 tenant。"},
            },
            "required": ["document"],
        },
        handler=lambda document, doc_format="markdown", detail="simple", scope="full", keyword="", identity="user", **_: client.fetch_document_resource(
            document=document,
            doc_format=doc_format,
            detail=detail,
            scope=scope,
            keyword=keyword,
            identity=_normalize_identity(identity),
        ),
        read_only=True,
    )


def _build_minutes_fetch_resource_tool(client: FeishuClient) -> AgentTool:
    """注册飞书妙记读取工具。"""

    return AgentTool(
        internal_name="minutes.fetch_resource",
        description="读取飞书妙记基础信息和 AI 产物，并转换为统一 Resource。",
        parameters={
            "type": "object",
            "properties": {
                "minute": {"type": "string", "description": "飞书妙记 URL 或 minute token。"},
                "include_artifacts": {"type": "boolean", "description": "是否尝试读取 summary/todos/chapters。"},
                "identity": {"type": "string", "description": "飞书身份，可选 user 或 tenant。"},
            },
            "required": ["minute"],
        },
        handler=lambda minute, include_artifacts=True, identity="user", **_: client.fetch_minute_resource(
            minute=minute,
            include_artifacts=include_artifacts,
            identity=_normalize_identity(identity),
        ),
        read_only=True,
    )


def _build_tasks_list_my_tasks_tool(client: FeishuClient) -> AgentTool:
    """注册当前用户任务读取工具。"""

    return AgentTool(
        internal_name="tasks.list_my_tasks",
        description="读取当前用户负责的飞书任务，并转换为统一 ActionItem 列表。",
        parameters={
            "type": "object",
            "properties": {
                "completed": {"type": "boolean", "description": "是否读取已完成任务。"},
                "page_size": {"type": "integer", "description": "单页数量，1 到 100。"},
                "page_limit": {"type": "integer", "description": "最多读取页数。"},
                "identity": {"type": "string", "description": "飞书身份，任务接口通常使用 user。"},
            },
            "required": [],
        },
        handler=lambda completed=False, page_size=50, page_limit=5, identity="user", **_: client.list_my_tasks(
            completed=completed,
            page_size=page_size,
            page_limit=page_limit,
            identity=_normalize_identity(identity),
        ),
        read_only=True,
    )


def _build_tasks_create_task_tool(client: FeishuClient) -> AgentTool:
    """注册飞书任务创建工具。"""

    return AgentTool(
        internal_name="tasks.create_task",
        description="创建飞书任务。写操作，后续 AgentPolicy 应先检查人工确认、负责人、截止时间和幂等键。",
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "任务标题。"},
                "description": {"type": "string", "description": "任务描述。"},
                "assignee_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "负责人 open_id 列表。",
                },
                "due_timestamp_ms": {"type": "string", "description": "截止时间，毫秒级时间戳。"},
                "confidence": {"type": "number", "description": "行动项置信度，AgentPolicy 用于辅助判断是否仍需补充确认。"},
                "evidence_refs": {"type": "array", "items": {}, "description": "会议证据引用，用于审计和任务描述，不直接透传飞书。"},
                "idempotency_key": {"type": "string", "description": "幂等键，避免重复创建。"},
                "identity": {"type": "string", "description": "飞书身份，任务创建通常使用 user。"},
            },
            "required": ["summary"],
        },
        handler=lambda summary, description="", assignee_ids=None, due_timestamp_ms="", idempotency_key="", identity="user", **_: client.create_task(
            summary=summary,
            description=description,
            assignee_ids=assignee_ids or [],
            due_timestamp_ms=due_timestamp_ms,
            idempotency_key=idempotency_key,
            identity=_normalize_identity(identity),
        ),
        read_only=False,
        side_effect="create_task",
    )


def _build_contact_get_current_user_tool(client: FeishuClient) -> AgentTool:
    """注册当前用户信息读取工具。

    这个工具让 LLM 能把“我”解析为当前登录用户的 open_id。
    """

    return AgentTool(
        internal_name="contact.get_current_user",
        description="读取当前登录飞书用户信息。当用户说“我/本人/自己”时，先调用它获取 open_id。",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=lambda **_: client.get_current_user_info(),
        read_only=True,
    )


def _build_contact_search_user_tool(client: FeishuClient) -> AgentTool:
    """注册飞书用户搜索工具。"""

    return AgentTool(
        internal_name="contact.search_user",
        description="按姓名、邮箱或手机号搜索飞书用户，返回候选用户信息和 open_id。用于把人员姓名解析为任务负责人 ID。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，例如姓名、邮箱或手机号。"},
                "page_size": {"type": "integer", "description": "返回数量，默认 20。"},
                "page_token": {"type": "string", "description": "分页 token。"},
                "identity": {"type": "string", "description": "飞书身份，通常使用 user。"},
            },
            "required": ["query"],
        },
        handler=lambda query, page_size=20, page_token="", identity="user", **_: client.search_users(
            query=query,
            page_size=page_size,
            page_token=page_token,
            identity=_normalize_identity(identity),
        ),
        read_only=True,
    )


def _build_im_send_text_tool(client: FeishuClient, default_chat_id: str) -> AgentTool:
    """注册飞书文本消息发送工具。"""

    return AgentTool(
        internal_name="im.send_text",
        description="发送飞书文本消息。写操作，通常用于通知或调试。",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "消息文本。"},
                "receive_id": {"type": "string", "description": "接收者 ID，默认使用配置中的测试群。"},
                "receive_id_type": {"type": "string", "description": "接收者 ID 类型，默认 chat_id。"},
                "idempotency_key": {"type": "string", "description": "消息幂等键，避免重复发送。"},
                "identity": {"type": "string", "description": "飞书身份，可选 user 或 tenant。"},
            },
            "required": ["text"],
        },
        handler=lambda text, receive_id="", receive_id_type="chat_id", idempotency_key="", identity="tenant", **_: client.send_text_message(
            receive_id=receive_id or default_chat_id,
            text=text,
            receive_id_type=receive_id_type,
            idempotency_key=idempotency_key,
            identity=_normalize_identity(identity),
        ),
        read_only=False,
        side_effect="send_message",
    )


def _build_im_send_card_tool(client: FeishuClient, default_chat_id: str) -> AgentTool:
    """注册飞书卡片消息发送工具。"""

    return AgentTool(
        internal_name="im.send_card",
        description=(
            "发送 MeetFlow 飞书卡片消息。写操作，通常用于会前背景卡、任务确认卡和风险提醒。"
            "请传 title、summary、facts，由工具构造稳定卡片；facts 中应包含可打开的原始资料链接。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "卡片标题。"},
                "summary": {"type": "string", "description": "卡片正文摘要。"},
                "facts": {"type": "array", "items": {}, "description": "卡片事实列表，可传字符串或包含 label/value 的对象。"},
                "receive_id": {"type": "string", "description": "接收者 ID，默认使用配置中的测试群。"},
                "receive_id_type": {"type": "string", "description": "接收者 ID 类型，默认 chat_id。"},
                "idempotency_key": {"type": "string", "description": "消息幂等键，避免重复发送。"},
                "identity": {"type": "string", "description": "飞书身份，可选 user 或 tenant。"},
            },
            "required": [],
        },
        handler=lambda title="", summary="", facts=None, card=None, receive_id="", receive_id_type="chat_id", idempotency_key="", identity="tenant", **_: send_card_with_fallback(
            client=client,
            receive_id=receive_id or default_chat_id,
            title=title,
            summary=summary,
            facts=facts,
            card=card,
            receive_id_type=receive_id_type,
            idempotency_key=idempotency_key,
            identity=_normalize_identity(identity),
        ),
        read_only=False,
        side_effect="send_message",
    )


def send_card_with_fallback(
    client: FeishuClient,
    receive_id: str,
    title: Any = "",
    summary: Any = "",
    facts: list[Any] | None = None,
    card: Any = None,
    receive_id_type: str = "chat_id",
    idempotency_key: str = "",
    identity: IdentityMode | None = None,
) -> dict[str, Any]:
    """发送卡片，并在模型传入不稳定 card 时回退到工具内置模板。

    真实模型有时会把运行时上下文里的卡片 JSON 改写成飞书接口不接受的形态。
    这里保留完整 card 的能力，但一旦飞书拒绝，就用 `title/summary/facts`
    构造最小稳定卡片，避免会前通知因为格式细节卡住。
    """

    normalized_title = str(title or "").strip()
    normalized_summary = str(summary or "").strip()
    normalized_facts = normalize_card_facts(facts or [])

    if isinstance(card, dict) and card:
        try:
            result = client.send_card_message(
                receive_id=receive_id,
                card=card,
                receive_id_type=receive_id_type,
                idempotency_key=idempotency_key,
                identity=identity,
            )
            if isinstance(result, dict):
                result.setdefault("card_delivery", "full_card")
            return result
        except FeishuAPIError as error:
            if not normalized_title or not normalized_summary:
                raise
            fallback_reason = str(error)
        else:
            fallback_reason = ""
    else:
        fallback_reason = ""

    if not normalized_title or not normalized_summary:
        raise ValueError("发送卡片需要 title/summary；若传 card，必须是飞书可接受的完整 interactive card JSON")

    fallback_card = client.build_meetflow_card(
        title=normalized_title,
        summary=normalized_summary,
        facts=normalized_facts,
    )
    result = client.send_card_message(
        receive_id=receive_id,
        card=fallback_card,
        receive_id_type=receive_id_type,
        idempotency_key=idempotency_key,
        identity=identity,
    )
    if isinstance(result, dict):
        result.setdefault("card_delivery", "fallback_card")
        if fallback_reason:
            result.setdefault("fallback_reason", fallback_reason)
    return result


def normalize_card_facts(facts: list[Any]) -> list[str]:
    """兼容旧字符串 facts 和 T3.7 的 label/value facts。"""

    normalized: list[str] = []
    for fact in facts:
        if isinstance(fact, dict):
            label = str(fact.get("label") or "").strip()
            value = str(fact.get("value") or "").strip()
            if label and value:
                normalized.append(f"{label}：{value}")
            elif value:
                normalized.append(value)
            continue
        if fact:
            normalized.append(str(fact))
    return normalized


def _normalize_identity(identity: Any) -> IdentityMode | None:
    """把 LLM 传入的身份字符串规范化。"""

    if identity in {"user", "tenant"}:
        return identity
    return None


def action_item_from_arguments(arguments: dict[str, Any]) -> ActionItem:
    """把工具参数转换为 ActionItem。

    当前函数预留给后续 AgentPolicy 或批量任务创建使用。
    """

    return ActionItem(
        item_id=str(arguments.get("item_id", "")),
        title=str(arguments.get("title", "")),
        owner=str(arguments.get("owner", "")),
        due_date=str(arguments.get("due_date", "")),
        confidence=float(arguments.get("confidence", 0.0) or 0.0),
        needs_confirm=bool(arguments.get("needs_confirm", False)),
        extra={"description": arguments.get("description", "")},
    )
