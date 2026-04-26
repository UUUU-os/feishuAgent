from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from core.models import AgentDecision, AgentInput, Event, Resource, WorkflowContext
from core.storage import MeetFlowStorage


class WorkflowContextError(RuntimeError):
    """工作流上下文构建异常。"""


@dataclass(slots=True)
class WorkflowContextBuilder:
    """工作流上下文构建器。

    负责把 `AgentInput + AgentDecision` 整理成 `WorkflowContext`。
    注意：这里不主动调用飞书 API，只解析已有 payload 和本地记忆，
    避免 Context Builder 变成隐式执行工具的地方。
    """

    storage: MeetFlowStorage | None = None
    default_project_id: str = "meetflow"

    def build(
        self,
        agent_input: AgentInput,
        decision: AgentDecision,
    ) -> WorkflowContext:
        """构建标准 WorkflowContext。"""

        payload = agent_input.payload
        project_id = extract_project_id(payload, default_project_id=self.default_project_id)
        return WorkflowContext(
            workflow_type=decision.workflow_type,
            trace_id=agent_input.trace_id,
            event=build_event_from_agent_input(agent_input),
            meeting_id=extract_meeting_id(payload),
            calendar_event_id=extract_calendar_event_id(payload),
            minute_token=extract_minute_token(payload),
            task_id=extract_task_id(payload),
            project_id=project_id,
            participants=extract_participants(payload),
            related_resources=extract_related_resources(payload),
            memory_snapshot=self._load_memory_snapshot(project_id),
            raw_context={
                "agent_input": agent_input.to_dict(),
                "decision": decision.to_dict(),
                "payload": payload,
            },
        )

    def _load_memory_snapshot(self, project_id: str) -> dict[str, Any]:
        """读取项目记忆快照。"""

        if not self.storage or not project_id:
            return {}
        memory = self.storage.load_project_memory(project_id)
        return memory or {}


def build_event_from_agent_input(agent_input: AgentInput) -> Event:
    """把 AgentInput 转换成统一 Event，便于后续调试和回放。"""

    return Event(
        event_id=agent_input.event_id or str(agent_input.payload.get("event_id", "")),
        event_type=agent_input.event_type,
        event_time=str(agent_input.created_at or int(time.time())),
        source=agent_input.source,
        actor=agent_input.actor,
        payload=agent_input.payload,
        trace_id=agent_input.trace_id,
    )


def extract_meeting_id(payload: dict[str, Any]) -> str:
    """从 payload 中提取会议 ID。"""

    return first_string(
        payload,
        "meeting_id",
        "meetingID",
        "meetingId",
        "calendar_event_id",
        "event_id",
        "eventId",
    )


def extract_calendar_event_id(payload: dict[str, Any]) -> str:
    """从 payload 中提取日历事件 ID。"""

    return first_string(
        payload,
        "calendar_event_id",
        "calendarEventId",
        "event_id",
        "eventId",
    )


def extract_minute_token(payload: dict[str, Any]) -> str:
    """从 payload 中提取妙记 token。"""

    return first_string(
        payload,
        "minute_token",
        "minuteToken",
        "minute_id",
        "minuteId",
        "token",
    )


def extract_task_id(payload: dict[str, Any]) -> str:
    """从 payload 中提取任务 ID。"""

    return first_string(
        payload,
        "task_id",
        "taskId",
        "task_guid",
        "guid",
    )


def extract_project_id(payload: dict[str, Any], default_project_id: str) -> str:
    """从 payload 中提取项目 ID，没有则使用默认项目。"""

    return first_string(
        payload,
        "project_id",
        "projectId",
        "space_id",
        "spaceId",
    ) or default_project_id


def extract_participants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从 payload 中提取参与人列表。"""

    raw_participants = (
        payload.get("participants")
        or payload.get("attendees")
        or payload.get("members")
        or []
    )
    if not isinstance(raw_participants, list):
        return []

    participants: list[dict[str, Any]] = []
    for item in raw_participants:
        if isinstance(item, dict):
            participants.append(item)
        elif item:
            participants.append({"name": str(item)})
    return participants


def extract_related_resources(payload: dict[str, Any]) -> list[Resource]:
    """从 payload 中提取已知相关资源。

    这里只转换 payload 中已经存在的资源线索，
    不主动调用文档、妙记或搜索接口。
    """

    raw_resources = payload.get("related_resources") or payload.get("resources") or []
    if not isinstance(raw_resources, list):
        return []

    resources: list[Resource] = []
    for item in raw_resources:
        if isinstance(item, Resource):
            resources.append(item)
        elif isinstance(item, dict):
            resources.append(resource_from_payload(item))
    return resources


def resource_from_payload(data: dict[str, Any]) -> Resource:
    """把 payload 中的资源字典转换为 Resource。"""

    return Resource(
        resource_id=first_string(data, "resource_id", "id", "document_id", "minute_token"),
        resource_type=first_string(data, "resource_type", "type") or "unknown",
        title=first_string(data, "title", "name") or "未命名资源",
        content=str(data.get("content", "") or data.get("summary", "") or ""),
        source_url=first_string(data, "source_url", "url", "link"),
        source_meta=data.get("source_meta", {}) if isinstance(data.get("source_meta"), dict) else {},
        updated_at=first_string(data, "updated_at", "update_time", "created_at"),
    )


def first_string(data: dict[str, Any], *keys: str) -> str:
    """按顺序读取第一个非空字符串字段。"""

    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        return str(value)
    return ""
