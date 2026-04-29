from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from core.models import AgentInput, BaseModel
from core.router import build_agent_input


@dataclass(slots=True)
class PreMeetingTriggerPlan(BaseModel):
    """一次会前触发计划。

    它把“定时器看到的日历事件”和 MeetFlow 内部 `meeting.soon` 事件隔离开：
    定时器只负责判断窗口和构造 payload，真正执行仍然进入
    WorkflowRouter -> PreMeetingBriefWorkflow。
    """

    trigger_id: str
    event: dict[str, Any]
    agent_input: AgentInput
    idempotency_key: str
    due_in_seconds: int
    reason: str


def select_due_pre_meeting_events(
    events: list[dict[str, Any]],
    now_ts: int | None = None,
    minutes_before: int = 30,
    tolerance_seconds: int = 300,
) -> list[dict[str, Any]]:
    """筛选进入会前触发窗口的日历事件。"""

    now = int(now_ts or time.time())
    window_seconds = max(int(minutes_before), 0) * 60
    due_events: list[dict[str, Any]] = []
    for event in events:
        start_ts = parse_event_timestamp(event.get("start_time") or event.get("startTime") or event.get("start"))
        if start_ts <= 0:
            continue
        due_in = start_ts - now
        if window_seconds - tolerance_seconds <= due_in <= window_seconds + tolerance_seconds:
            item = dict(event)
            item["due_in_seconds"] = due_in
            due_events.append(item)
    return due_events


def build_pre_meeting_trigger_plan(
    event: dict[str, Any],
    project_id: str = "meetflow",
    source: str = "pre_meeting_scheduler",
) -> PreMeetingTriggerPlan:
    """把一条日历事件转换为可路由的 `meeting.soon` AgentInput。"""

    event_id = first_non_empty(event, "event_id", "calendar_event_id", "id") or "scheduled_event"
    meeting_id = first_non_empty(event, "meeting_id", "meetingId") or event_id
    calendar_event_id = first_non_empty(event, "calendar_event_id", "event_id", "id") or event_id
    payload = {
        **event,
        "workflow_type": "pre_meeting_brief",
        "project_id": project_id,
        "meeting_id": meeting_id,
        "calendar_event_id": calendar_event_id,
        "idempotency_key": f"pre_meeting_brief:{calendar_event_id}",
    }
    agent_input = build_agent_input(
        event_type="meeting.soon",
        trigger_type="schedule",
        payload=payload,
        source=source,
    )
    return PreMeetingTriggerPlan(
        trigger_id=f"meeting.soon:{calendar_event_id}",
        event=dict(event),
        agent_input=agent_input,
        idempotency_key=str(payload["idempotency_key"]),
        due_in_seconds=int(event.get("due_in_seconds") or 0),
        reason="会议进入会前触发窗口，准备生成会前背景卡。",
    )


def build_manual_pre_meeting_input(
    command_text: str,
    project_id: str = "meetflow",
    meeting_title: str = "",
    source: str = "manual_pre_meeting",
) -> AgentInput:
    """构造手动兜底入口的 AgentInput。"""

    title = meeting_title or infer_manual_meeting_title(command_text, project_id)
    payload = {
        "workflow_type": "pre_meeting_brief",
        "project_id": project_id,
        "meeting_id": f"manual:{project_id}:{stable_text_digest(title)}",
        "calendar_event_id": f"manual:{project_id}:{stable_text_digest(command_text)}",
        "summary": title,
        "description": command_text,
        "idempotency_key": f"manual_pre_meeting:{project_id}:{stable_text_digest(command_text)}",
    }
    return build_agent_input(
        event_type="message.command",
        trigger_type="manual",
        payload=payload,
        source=source,
    )


def parse_event_timestamp(value: Any) -> int:
    """解析日历事件中的秒级或毫秒级时间戳。"""

    text = str(value or "").strip()
    if not text or not text.isdigit():
        return 0
    number = int(text)
    return number // 1000 if number > 10_000_000_000 else number


def infer_manual_meeting_title(command_text: str, project_id: str) -> str:
    """从手动命令中提取一个可读会议标题。"""

    text = str(command_text or "").strip()
    if not text:
        return f"{project_id} 会前背景卡"
    return text.replace("生成", "").replace("会前卡片", "").strip() or f"{project_id} 会前背景卡"


def first_non_empty(data: dict[str, Any], *keys: str) -> str:
    """从字典中读取第一个非空字符串。"""

    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def stable_text_digest(text: str) -> str:
    """生成短文本稳定摘要，用于手动触发幂等键。"""

    import hashlib

    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:10]
