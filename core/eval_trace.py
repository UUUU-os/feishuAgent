from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from core.models import AgentLoopState, BaseModel, WorkflowContext


SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|secret|api[_-]?key|password|authorization|refresh|access[_-]?token)",
    re.IGNORECASE,
)
ID_KEY_PATTERN = re.compile(
    r"(open_id|union_id|user_id|chat_id|document_id|minute_token|calendar_event_id|task_id|receive_id)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ToolCallTrace(BaseModel):
    """工具调用轨迹。

    这个模型用于评估 Agent 是否真的具备“先理解、再选工具、再基于结果行动”的能力。
    参数只保留脱敏摘要和 hash，避免评测报告成为新的敏感数据面。
    """

    call_id: str
    tool_name: str
    llm_tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    arguments_hash: str = ""
    schema_valid: bool = True
    status: str = ""
    result_summary: dict[str, Any] = field(default_factory=dict)
    started_at: int = 0
    finished_at: int = 0


@dataclass(slots=True)
class PolicyDecisionTrace(BaseModel):
    """写操作安全策略轨迹。

    评测系统用它判断写操作是否经过 Policy、是否被正确拦截、
    是否具备幂等键和缺字段澄清信息。
    """

    tool_name: str
    side_effect: str = ""
    status: str = ""
    reason: str = ""
    required_fields: list[str] = field(default_factory=list)
    idempotency_key_present: bool = False
    allow_write: bool = False


@dataclass(slots=True)
class AgentTrace(BaseModel):
    """一次 Agent 运行的可评测轨迹。"""

    trace_id: str
    workflow_type: str
    case_id: str = ""
    input_summary: dict[str, Any] = field(default_factory=dict)
    route_decision: dict[str, Any] = field(default_factory=dict)
    context_summary: dict[str, Any] = field(default_factory=dict)
    assistant_plan: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    policy_decisions: list[PolicyDecisionTrace] = field(default_factory=list)
    side_effects: list[dict[str, Any]] = field(default_factory=list)
    final_answer_summary: str = ""
    status: str = ""
    started_at: int = 0
    finished_at: int = 0


def build_assistant_plan(
    workflow_type: str,
    required_tools: list[str],
    workflow_goal: str = "",
) -> list[dict[str, Any]]:
    """根据工作流和工具集生成显式执行计划。

    计划不会赋予任何执行权限，只用于约束 LLM 思考、审计和评测。
    """

    tool_set = set(required_tools)
    plan: list[dict[str, Any]] = [
        {
            "step": "理解当前会议/项目意图和缺失上下文",
            "expected_tool": "",
            "reason": "先判断是否需要补充信息，避免盲目写入或编造事实。",
        }
    ]
    if workflow_type == "pre_meeting_brief":
        if "calendar.list_events" in tool_set:
            plan.append(
                {
                    "step": "读取真实日历会议详情",
                    "expected_tool": "calendar.list_events",
                    "reason": "会前简报必须基于真实会议标题、时间和参与人。",
                }
            )
        if "knowledge.search" in tool_set:
            plan.append(
                {
                    "step": "检索当前会议相关知识证据",
                    "expected_tool": "knowledge.search",
                    "reason": "背景结论必须有证据来源，不能只靠模型猜测。",
                }
            )
    elif workflow_type == "post_meeting_followup":
        if "minutes.fetch_resource" in tool_set:
            plan.append(
                {
                    "step": "读取妙记并抽取会议结论和行动项",
                    "expected_tool": "minutes.fetch_resource",
                    "reason": "会后任务必须能追溯到妙记原文。",
                }
            )
        if "contact.get_current_user" in tool_set or "contact.search_user" in tool_set:
            plan.append(
                {
                    "step": "解析负责人身份",
                    "expected_tool": "contact.get_current_user/contact.search_user",
                    "reason": "负责人必须解析成飞书 open_id，不能编造。",
                }
            )
    elif workflow_type == "risk_scan":
        if "tasks.list_my_tasks" in tool_set:
            plan.append(
                {
                    "step": "读取任务状态并识别风险",
                    "expected_tool": "tasks.list_my_tasks",
                    "reason": "风险提醒必须基于真实任务状态。",
                }
            )

    if any(tool.startswith("im.") for tool in tool_set):
        plan.append(
            {
                "step": "在 Policy 允许后发送卡片或消息",
                "expected_tool": "im.send_card/im.send_text",
                "reason": "群消息属于外部副作用，必须经过写权限和幂等检查。",
            }
        )
    if workflow_goal:
        plan.append(
            {
                "step": "生成可解释最终回答和下一步建议",
                "expected_tool": "",
                "reason": "最终输出需要说明证据、阻塞点和建议动作。",
            }
        )
    return plan


def build_trace_from_state(
    context: WorkflowContext,
    state: AgentLoopState,
    status: str,
    final_answer: str,
    side_effects: list[dict[str, Any]],
) -> AgentTrace:
    """从 AgentLoopState 构造评测 trace。"""

    tool_call_traces = [
        ToolCallTrace(**item)
        for item in list(state.extra.get("tool_call_traces") or [])
        if isinstance(item, dict)
    ]
    policy_decision_traces = [
        PolicyDecisionTrace(**item)
        for item in list(state.extra.get("policy_decisions") or [])
        if isinstance(item, dict)
    ]
    return AgentTrace(
        trace_id=context.trace_id,
        workflow_type=context.workflow_type,
        input_summary=summarize_context(context),
        context_summary=summarize_context(context),
        assistant_plan=list(state.extra.get("assistant_plan") or []),
        tool_calls=tool_call_traces,
        policy_decisions=policy_decision_traces,
        side_effects=sanitize_value(side_effects),
        final_answer_summary=truncate_text(final_answer, 500),
        status=status,
        started_at=int(state.extra.get("started_at", 0) or 0),
        finished_at=int(time.time()),
    )


def summarize_context(context: WorkflowContext) -> dict[str, Any]:
    """生成可评测上下文摘要，避免保存完整敏感 payload。"""

    return {
        "workflow_type": context.workflow_type,
        "trace_id": context.trace_id,
        "has_meeting_id": bool(context.meeting_id),
        "has_calendar_event_id": bool(context.calendar_event_id),
        "has_minute_token": bool(context.minute_token),
        "has_task_id": bool(context.task_id),
        "project_id": mask_identifier(context.project_id) if context.project_id else "",
        "participant_count": len(context.participants),
        "related_resource_count": len(context.related_resources),
        "memory_keys": sorted(str(key) for key in context.memory_snapshot.keys()),
        "event_type": context.event.event_type if context.event else "",
        "source": context.event.source if context.event else "",
    }


def summarize_tool_result_data(data: dict[str, Any]) -> dict[str, Any]:
    """生成工具结果摘要，供评测使用。"""

    if not isinstance(data, dict):
        return {"type": type(data).__name__}
    summary: dict[str, Any] = {
        "keys": sorted(str(key) for key in data.keys())[:20],
    }
    if "count" in data:
        summary["count"] = data.get("count")
    items = data.get("items")
    if isinstance(items, list):
        summary["item_count"] = len(items)
        summary["item_keys"] = sorted(str(key) for key in items[0].keys())[:20] if items and isinstance(items[0], dict) else []
    return summary


def hash_arguments(arguments: dict[str, Any]) -> str:
    """计算工具参数 hash，用于对比而不泄露完整参数。"""

    sanitized = sanitize_value(arguments)
    payload = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def sanitize_value(value: Any) -> Any:
    """递归脱敏评测 trace 中的字段。"""

    if isinstance(value, BaseModel):
        return sanitize_value(value.to_dict())
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SENSITIVE_KEY_PATTERN.search(key_text):
                sanitized[key_text] = "***"
            elif ID_KEY_PATTERN.search(key_text):
                sanitized[key_text] = mask_identifier(str(item or ""))
            else:
                sanitized[key_text] = sanitize_value(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        if "access_token=" in value or "refresh_token=" in value:
            return "***"
        return truncate_text(value, 500)
    return value


def mask_identifier(value: str) -> str:
    """保留 ID 是否存在和短 hash，不暴露真实飞书 ID。"""

    if not value:
        return ""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"masked_{digest}"


def truncate_text(value: str, limit: int) -> str:
    """限制 trace 文本长度，避免报告过大。"""

    if len(value) <= limit:
        return value
    return value[:limit] + "...（已截断）"
