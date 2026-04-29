from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from core.models import AgentDecision, AgentInput


class WorkflowRouterError(RuntimeError):
    """工作流路由器异常。"""


@dataclass(slots=True)
class RouteRule:
    """单条工作流路由规则。

    `event_type` 是触发事件类型，`workflow_type` 是目标业务工作流。
    `required_tools` 使用内部工具名，后续由 Tool Registry 映射为 LLM 可见工具名。
    """

    event_type: str
    workflow_type: str
    reason: str
    required_tools: list[str] = field(default_factory=list)
    confidence: float = 1.0
    status: str = "ready"


class WorkflowRouter:
    """业务工作流路由器。

    首版采用规则驱动：
    - 稳定、可解释，便于答辩
    - 避免 LLM 接管系统级路由
    - 让 LLM 只在具体业务场景内选择工具和生成结果
    """

    def __init__(self, rules: list[RouteRule] | None = None) -> None:
        self.rules_by_event_type = {
            rule.event_type: rule
            for rule in (rules or build_default_route_rules())
        }

    def route(self, agent_input: AgentInput) -> AgentDecision:
        """根据 AgentInput 输出 AgentDecision。"""

        event_type = agent_input.event_type.strip()
        rule = self.rules_by_event_type.get(event_type)
        if rule is None:
            return self._unsupported_decision(agent_input)

        workflow_type = self._resolve_workflow_type(agent_input, rule)
        required_tools = self._resolve_required_tools(agent_input, rule, workflow_type)
        idempotency_key = build_idempotency_key(
            workflow_type=workflow_type,
            agent_input=agent_input,
        )

        return AgentDecision(
            workflow_type=workflow_type,
            confidence=rule.confidence,
            reason=rule.reason,
            required_tools=required_tools,
            idempotency_key=idempotency_key,
            status=rule.status,
            extra={
                "event_type": event_type,
                "trigger_type": agent_input.trigger_type,
                "source": agent_input.source,
            },
        )

    def _resolve_workflow_type(self, agent_input: AgentInput, rule: RouteRule) -> str:
        """解析最终工作流类型。

        对 `message.command` 这类人工命令，允许 payload 显式指定 workflow_type。
        这样本地调试或飞书命令可以直接触发某条业务链路。
        """

        if agent_input.event_type != "message.command":
            return rule.workflow_type

        requested_workflow = str(agent_input.payload.get("workflow_type", "") or "").strip()
        if requested_workflow:
            return requested_workflow
        return rule.workflow_type

    def _resolve_required_tools(
        self,
        agent_input: AgentInput,
        rule: RouteRule,
        workflow_type: str,
    ) -> list[str]:
        """解析本次工作流允许暴露给 LLM 的工具名单。"""

        payload_tools = agent_input.payload.get("required_tools")
        if isinstance(payload_tools, list) and payload_tools:
            return [str(tool_name) for tool_name in payload_tools if tool_name]

        if agent_input.event_type == "message.command" and workflow_type in MANUAL_WORKFLOW_TOOLS:
            return MANUAL_WORKFLOW_TOOLS[workflow_type]

        return list(rule.required_tools)

    def _unsupported_decision(self, agent_input: AgentInput) -> AgentDecision:
        """未知事件返回 unsupported 决策，而不是抛异常中断。"""

        return AgentDecision(
            workflow_type="unsupported",
            confidence=0.0,
            reason=f"暂不支持事件类型：{agent_input.event_type}",
            required_tools=[],
            idempotency_key=build_idempotency_key(
                workflow_type="unsupported",
                agent_input=agent_input,
            ),
            status="unsupported",
            extra={
                "event_type": agent_input.event_type,
                "trigger_type": agent_input.trigger_type,
                "source": agent_input.source,
            },
        )


def build_default_route_rules() -> list[RouteRule]:
    """构建首版默认路由规则。"""

    return [
        RouteRule(
            event_type="meeting.soon",
            workflow_type="pre_meeting_brief",
            reason="会议即将开始，需要读取日历、关联文档和任务，生成会前背景卡。",
            required_tools=[
                "calendar.list_events",
                "knowledge.search",
                "knowledge.fetch_chunk",
                "docs.fetch_resource",
                "minutes.fetch_resource",
                "tasks.list_my_tasks",
                "im.send_card",
            ],
        ),
        RouteRule(
            event_type="minute.ready",
            workflow_type="post_meeting_followup",
            reason="妙记已生成，需要读取妙记内容，抽取行动项，并按策略创建任务或发送确认卡。",
            required_tools=[
                "minutes.fetch_resource",
                "docs.fetch_resource",
                "tasks.create_task",
                "im.send_card",
            ],
        ),
        RouteRule(
            event_type="risk.scan.tick",
            workflow_type="risk_scan",
            reason="定时风险巡检触发，需要读取任务状态并生成低噪声风险提醒。",
            required_tools=[
                "tasks.list_my_tasks",
                "calendar.list_events",
                "im.send_card",
            ],
        ),
        RouteRule(
            event_type="message.command",
            workflow_type="manual_qa",
            reason="收到人工命令，进入受控工具集内的手动问答或指定工作流。",
            required_tools=[
                "calendar.list_events",
                "docs.fetch_resource",
                "minutes.fetch_resource",
                "tasks.list_my_tasks",
            ],
            confidence=0.85,
        ),
    ]


MANUAL_WORKFLOW_TOOLS: dict[str, list[str]] = {
    "pre_meeting_brief": [
        "calendar.list_events",
        "knowledge.search",
        "knowledge.fetch_chunk",
        "docs.fetch_resource",
        "minutes.fetch_resource",
        "tasks.list_my_tasks",
        "im.send_card",
    ],
    "post_meeting_followup": [
        "minutes.fetch_resource",
        "docs.fetch_resource",
        "tasks.create_task",
        "im.send_card",
    ],
    "risk_scan": [
        "tasks.list_my_tasks",
        "calendar.list_events",
        "im.send_card",
    ],
    "manual_qa": [
        "calendar.list_events",
        "docs.fetch_resource",
        "minutes.fetch_resource",
        "tasks.list_my_tasks",
    ],
}


def build_idempotency_key(workflow_type: str, agent_input: AgentInput) -> str:
    """构造稳定幂等键。

    优先使用当前工作流最稳定的业务 ID；
    如果没有，则退回到 event_id；
    仍然没有时，对 payload 做短 hash，保证同类输入尽量稳定去重。
    """

    payload = agent_input.payload
    stable_id = payload.get("idempotency_key") or _select_stable_id(workflow_type, agent_input)

    if stable_id:
        return f"{workflow_type}:{stable_id}"

    payload_digest = hashlib.sha1(str(sorted(payload.items())).encode("utf-8")).hexdigest()[:12]
    time_bucket = agent_input.created_at or int(time.time())
    return f"{workflow_type}:{agent_input.event_type}:{time_bucket}:{payload_digest}"


def _select_stable_id(workflow_type: str, agent_input: AgentInput) -> str:
    """按工作流类型选择最适合作为幂等键的业务 ID。"""

    payload = agent_input.payload
    if workflow_type == "pre_meeting_brief":
        keys = ("meeting_id", "calendar_event_id", "event_id")
    elif workflow_type == "post_meeting_followup":
        keys = ("minute_token", "meeting_id", "calendar_event_id", "event_id")
    elif workflow_type == "risk_scan":
        keys = ("task_id", "project_id", "event_id")
    else:
        keys = ("event_id", "meeting_id", "minute_token", "task_id")

    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return agent_input.event_id


def build_agent_input(
    event_type: str,
    trigger_type: str = "manual",
    payload: dict[str, Any] | None = None,
    actor: str = "",
    source: str = "demo",
) -> AgentInput:
    """构造 AgentInput，方便脚本和后续测试复用。"""

    now = int(time.time())
    return AgentInput(
        trigger_type=trigger_type,
        event_type=event_type,
        payload=payload or {},
        actor=actor,
        source=source,
        event_id=str((payload or {}).get("event_id", "")),
        created_at=now,
    )
