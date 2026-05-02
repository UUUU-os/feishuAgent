from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.logging import generate_trace_id
from core.models import AgentInput, BaseModel
from core.observability import duration_ms_since, emit_structured_event, safe_error_message


class CardActionError(RuntimeError):
    """卡片动作处理异常。"""


@dataclass(slots=True)
class CardActionInput(BaseModel):
    """飞书卡片按钮点击转换后的内部输入。

    这个模型屏蔽飞书原始回调字段差异，让核心路由只关心“谁在什么群里
    对哪张卡片点了什么动作”。后续真实执行仍然要进入 Agent 主链路和
    AgentPolicy，不能在回调入口里直接产生外部副作用。
    """

    action: str
    trace_id: str
    event_id: str = ""
    operator_open_id: str = ""
    chat_id: str = ""
    open_message_id: str = ""
    workflow_type: str = ""
    meeting_id: str = ""
    calendar_event_id: str = ""
    source_card: str = ""
    idempotency_key: str = ""
    value: dict[str, Any] = field(default_factory=dict)
    raw_event: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0


@dataclass(slots=True)
class CardActionResult(BaseModel):
    """卡片动作处理结果。

    `response_mode` 给飞书回调层使用：MVP 默认返回 toast。重动作可以先
    accepted，再由后台 Agent 发送新消息或更新卡片。
    """

    status: str
    action: str
    message: str
    trace_id: str
    response_mode: str = "toast"
    agent_input: AgentInput | None = None
    response_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class CardActionRouter:
    """卡片按钮动作路由器。

    第一版只把稳定按钮动作转换为内部 `AgentInput` 或受控提示，不在这里
    直接调用飞书写接口。这样群聊交互和现有 Agent Runtime 保持同一条
    安全边界。
    """

    def route(self, action_input: CardActionInput) -> CardActionResult:
        """路由卡片动作，并记录结构化观测事件。"""

        started_at = time.perf_counter()
        emit_structured_event(
            "card_action_routed",
            trace_id=action_input.trace_id,
            action=action_input.action,
            workflow_type=action_input.workflow_type,
            event_id=action_input.event_id,
            operator_open_id=action_input.operator_open_id,
            chat_id=action_input.chat_id,
            open_message_id=action_input.open_message_id,
            idempotency_key=action_input.idempotency_key,
            status="started",
        )

        try:
            result = self._route(action_input)
            emit_structured_event(
                "card_action_finished",
                trace_id=action_input.trace_id,
                action=action_input.action,
                workflow_type=action_input.workflow_type,
                event_id=action_input.event_id,
                operator_open_id=action_input.operator_open_id,
                chat_id=action_input.chat_id,
                open_message_id=action_input.open_message_id,
                idempotency_key=action_input.idempotency_key,
                status=result.status,
                response_mode=result.response_mode,
                duration_ms=duration_ms_since(started_at),
                message=result.message,
            )
            return result
        except Exception as error:  # noqa: BLE001 - 回调入口必须给出受控失败结果。
            safe_message = safe_error_message(error)
            emit_structured_event(
                "card_action_failed",
                trace_id=action_input.trace_id,
                action=action_input.action,
                workflow_type=action_input.workflow_type,
                event_id=action_input.event_id,
                operator_open_id=action_input.operator_open_id,
                chat_id=action_input.chat_id,
                open_message_id=action_input.open_message_id,
                idempotency_key=action_input.idempotency_key,
                status="failed",
                duration_ms=duration_ms_since(started_at),
                error_type=error.__class__.__name__,
                error_message=safe_message,
            )
            return CardActionResult(
                status="failed",
                action=action_input.action,
                message=f"卡片动作处理失败：{safe_message}",
                trace_id=action_input.trace_id,
            )

    def _route(self, action_input: CardActionInput) -> CardActionResult:
        """执行不带异常兜底的路由逻辑，方便测试具体分支。"""

        action = (action_input.action or "").strip()
        if not action:
            return CardActionResult(
                status="blocked",
                action="",
                message="卡片动作缺少 action，无法处理。",
                trace_id=action_input.trace_id,
            )
        if action == "refresh_pre_meeting_brief":
            return self._refresh_pre_meeting_brief(action_input)
        if action == "create_task_draft":
            return self._create_task_draft(action_input)
        if action == "send_summary_to_me":
            return self._send_summary_to_me(action_input)
        return CardActionResult(
            status="blocked",
            action=action,
            message=f"暂不支持的卡片动作：{action}",
            trace_id=action_input.trace_id,
        )

    def _refresh_pre_meeting_brief(self, action_input: CardActionInput) -> CardActionResult:
        """把“刷新会前背景”转换为 `pre_meeting_brief` AgentInput。"""

        idempotency_key = action_input.idempotency_key or build_card_action_idempotency_key(
            source_card=action_input.source_card or "pre_meeting_brief",
            calendar_event_id=action_input.calendar_event_id or action_input.meeting_id,
            action=action_input.action,
        )
        agent_input = AgentInput(
            trigger_type="card_action",
            event_type="card.refresh_pre_meeting",
            source="feishu_card",
            actor=action_input.operator_open_id,
            event_id=action_input.event_id,
            trace_id=action_input.trace_id,
            created_at=action_input.created_at or int(time.time()),
            payload={
                "workflow_type": "pre_meeting_brief",
                "meeting_id": action_input.meeting_id,
                "calendar_event_id": action_input.calendar_event_id,
                "event_id": action_input.calendar_event_id or action_input.meeting_id,
                "chat_id": action_input.chat_id,
                "open_message_id": action_input.open_message_id,
                "operator_open_id": action_input.operator_open_id,
                "source_card": action_input.source_card,
                "idempotency_key": idempotency_key,
                "required_tools": [
                    "calendar.list_events",
                    "knowledge.search",
                    "knowledge.fetch_chunk",
                    "docs.fetch_resource",
                    "minutes.fetch_resource",
                    "tasks.list_my_tasks",
                    "im.send_card",
                ],
            },
        )
        return CardActionResult(
            status="accepted",
            action=action_input.action,
            message="已收到，正在刷新会前背景。",
            trace_id=action_input.trace_id,
            agent_input=agent_input,
            metadata={"workflow_type": "pre_meeting_brief"},
        )

    def _create_task_draft(self, action_input: CardActionInput) -> CardActionResult:
        """生成待办草案的 MVP 响应。

        第一版只接受动作，不直接创建飞书任务。真正写入任务必须进入后续
        confirm 动作，并由 AgentPolicy 检查负责人、截止时间和幂等键。
        """

        return CardActionResult(
            status="needs_confirmation",
            action=action_input.action,
            message="已收到，待办草案能力会先生成预览，创建任务前还需要确认。",
            trace_id=action_input.trace_id,
            metadata={"workflow_type": action_input.workflow_type or "post_meeting_followup"},
        )

    def _send_summary_to_me(self, action_input: CardActionInput) -> CardActionResult:
        """发送给点击人的 MVP 响应。

        私聊发送属于写操作，第一版先返回确认提示，避免未经确认就对用户
        私聊发送内容。
        """

        return CardActionResult(
            status="needs_confirmation",
            action=action_input.action,
            message="已收到，私聊发送属于写操作，后续会在确认后只发送给点击人。",
            trace_id=action_input.trace_id,
            metadata={"operator_open_id": action_input.operator_open_id},
        )


def build_card_action_idempotency_key(source_card: str, calendar_event_id: str, action: str) -> str:
    """构造卡片动作幂等键，避免重复点击造成重复执行。"""

    normalized_source = str(source_card or "card").strip() or "card"
    normalized_event_id = str(calendar_event_id or "unknown").strip() or "unknown"
    normalized_action = str(action or "unknown").strip() or "unknown"
    return f"card:{normalized_source}:{normalized_event_id}:{normalized_action}"


def build_card_action_input(
    action: str,
    trace_id: str = "",
    event_id: str = "",
    operator_open_id: str = "",
    chat_id: str = "",
    open_message_id: str = "",
    workflow_type: str = "",
    meeting_id: str = "",
    calendar_event_id: str = "",
    source_card: str = "",
    idempotency_key: str = "",
    value: dict[str, Any] | None = None,
    raw_event: dict[str, Any] | None = None,
    created_at: int = 0,
) -> CardActionInput:
    """构造 `CardActionInput`，供 handler、demo 和测试复用。"""

    final_trace_id = trace_id or generate_trace_id()
    final_value = dict(value or {})
    final_source_card = source_card or str(final_value.get("source_card", "") or "")
    final_calendar_event_id = calendar_event_id or str(final_value.get("calendar_event_id", "") or "")
    final_meeting_id = meeting_id or str(final_value.get("meeting_id", "") or "")
    final_idempotency_key = idempotency_key or str(final_value.get("idempotency_key", "") or "")
    if not final_idempotency_key and action:
        final_idempotency_key = build_card_action_idempotency_key(
            source_card=final_source_card or "pre_meeting_brief",
            calendar_event_id=final_calendar_event_id or final_meeting_id,
            action=action,
        )

    return CardActionInput(
        action=str(action or "").strip(),
        trace_id=final_trace_id,
        event_id=str(event_id or "").strip(),
        operator_open_id=str(operator_open_id or "").strip(),
        chat_id=str(chat_id or "").strip(),
        open_message_id=str(open_message_id or "").strip(),
        workflow_type=workflow_type or str(final_value.get("workflow_type", "") or ""),
        meeting_id=final_meeting_id,
        calendar_event_id=final_calendar_event_id,
        source_card=final_source_card,
        idempotency_key=final_idempotency_key,
        value=final_value,
        raw_event=dict(raw_event or {}),
        created_at=created_at or int(time.time()),
    )
