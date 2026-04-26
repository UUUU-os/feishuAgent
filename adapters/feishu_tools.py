from __future__ import annotations

from typing import Any

from adapters.feishu_client import FeishuClient, IdentityMode
from core import ActionItem
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
        description="创建飞书任务。写操作，后续 AgentPolicy 应先检查置信度、负责人和幂等键。",
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
                "identity": {"type": "string", "description": "飞书身份，可选 user 或 tenant。"},
            },
            "required": ["text"],
        },
        handler=lambda text, receive_id="", receive_id_type="chat_id", identity="tenant", **_: client.send_text_message(
            receive_id=receive_id or default_chat_id,
            text=text,
            receive_id_type=receive_id_type,
            identity=_normalize_identity(identity),
        ),
        read_only=False,
        side_effect="send_message",
    )


def _build_im_send_card_tool(client: FeishuClient, default_chat_id: str) -> AgentTool:
    """注册飞书卡片消息发送工具。"""

    return AgentTool(
        internal_name="im.send_card",
        description="发送 MeetFlow 飞书卡片消息。写操作，通常用于会前背景卡、任务确认卡和风险提醒。",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "卡片标题。"},
                "summary": {"type": "string", "description": "卡片正文摘要。"},
                "facts": {"type": "array", "items": {"type": "string"}, "description": "卡片事实列表。"},
                "receive_id": {"type": "string", "description": "接收者 ID，默认使用配置中的测试群。"},
                "receive_id_type": {"type": "string", "description": "接收者 ID 类型，默认 chat_id。"},
                "identity": {"type": "string", "description": "飞书身份，可选 user 或 tenant。"},
            },
            "required": ["title", "summary"],
        },
        handler=lambda title, summary, facts=None, receive_id="", receive_id_type="chat_id", identity="tenant", **_: client.send_card_message(
            receive_id=receive_id or default_chat_id,
            card=client.build_meetflow_card(title=title, summary=summary, facts=facts or []),
            receive_id_type=receive_id_type,
            identity=_normalize_identity(identity),
        ),
        read_only=False,
        side_effect="send_message",
    )


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
