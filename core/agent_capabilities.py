from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import BaseModel
from core.policy import AgentPolicy
from core.tools import ToolRegistry
from core.workflows import WorkflowRunner, build_default_workflow_runners


@dataclass(slots=True)
class AgentCapabilityReport(BaseModel):
    """D6 Agent 能力报告。

    这份报告把 MeetFlow 的 Context、Tool、Policy、Trace 四层能力
    整理成结构化数据，方便 Console、OpenClaw、评测和答辩材料复用。
    """

    version: str
    summary: str
    workflows: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    flow_diagram: str = ""


def build_agent_capability_report(
    workflow_runners: dict[str, WorkflowRunner] | None = None,
    tool_registry: ToolRegistry | None = None,
    policy: AgentPolicy | None = None,
) -> AgentCapabilityReport:
    """构建 D6 Agent 能力报告，不执行任何工具或外部副作用。"""

    runners = workflow_runners or build_default_workflow_runners()
    return AgentCapabilityReport(
        version="D6-agent-capability-v1",
        summary=(
            "MeetFlow Agent 通过 WorkflowRouter、WorkflowContextBuilder、"
            "MeetFlowAgentLoop、ToolRegistry、AgentPolicy 和 AgentTrace "
            "表达可解释的多步骤办公工作流。"
        ),
        workflows=build_workflow_section(runners),
        tools=build_tool_section(runners, tool_registry),
        policy=build_policy_section(policy or AgentPolicy()),
        trace=build_trace_section(),
        flow_diagram=build_agent_flow_diagram(),
    )


def build_workflow_section(workflow_runners: dict[str, WorkflowRunner]) -> list[dict[str, Any]]:
    """整理会前、会后、风险和手动问答的工作流边界。"""

    section: list[dict[str, Any]] = []
    for workflow_type, runner in workflow_runners.items():
        spec = runner.spec
        section.append(
            {
                "workflow_type": workflow_type,
                "workflow_goal": spec.workflow_goal,
                "allowed_tools": list(spec.allowed_tools),
                "context_inputs": infer_context_inputs(workflow_type),
                "evidence_sources": infer_evidence_sources(workflow_type),
                "validation_rules": list(spec.validation_rules),
                "stages": [
                    "WorkflowRouter",
                    "WorkflowContextBuilder",
                    "WorkflowRunner",
                    "MeetFlowAgentLoop",
                    "ToolRegistry",
                    "AgentPolicy",
                    "AgentTrace",
                ],
            }
        )
    return section


def build_tool_section(
    workflow_runners: dict[str, WorkflowRunner],
    tool_registry: ToolRegistry | None,
) -> list[dict[str, Any]]:
    """整理工具清单；有 ToolRegistry 时展示真实 LLM 名称和读写属性。"""

    workflow_map = build_tool_workflow_map(workflow_runners)
    if tool_registry is None:
        return [
            {
                "internal_name": name,
                "llm_name": name.replace(".", "_"),
                "read_only": not name.startswith(("im.", "tasks.create_task", "post_meeting.send")),
                "side_effect": infer_side_effect(name),
                "workflow_types": workflow_map[name],
            }
            for name in sorted(workflow_map)
        ]

    tools = []
    for tool in sorted(tool_registry.list_tools(), key=lambda item: item.internal_name):
        required = tool.parameters.get("required", [])
        tools.append(
            {
                "internal_name": tool.internal_name,
                "llm_name": tool.llm_name,
                "read_only": tool.read_only,
                "side_effect": tool.side_effect,
                "required_fields": list(required) if isinstance(required, list) else [],
                "workflow_types": workflow_map.get(tool.internal_name, []),
            }
        )
    return tools


def build_policy_section(policy: AgentPolicy) -> dict[str, Any]:
    """整理 AgentPolicy 的写操作边界。"""

    config = policy.config
    return {
        "allow_write_default": False,
        "require_idempotency_for_writes": config.require_idempotency_for_writes,
        "require_human_confirmation_for_tasks": config.require_human_confirmation_for_tasks,
        "require_task_owner": config.require_task_owner,
        "require_task_due_date": config.require_task_due_date,
        "min_action_item_confidence": config.min_action_item_confidence,
        "guarded_side_effects": ["create_task", "send_message"],
        "safety_rules": [
            "只读工具默认允许，写工具必须显式 allow_write。",
            "任务创建必须具备人工确认、负责人、截止时间、置信度和幂等键。",
            "风险提醒必须具备幂等键和降噪计数。",
            "Policy 拦截会进入 Trace，缺字段时保存可恢复 pending action。",
        ],
    }


def build_trace_section() -> dict[str, Any]:
    """整理 AgentTrace 和 intelligence_signals 的展示字段。"""

    return {
        "trace_fields": [
            "trace_id",
            "workflow_type",
            "context_summary",
            "assistant_plan",
            "tool_calls",
            "policy_decisions",
            "side_effects",
            "final_answer_summary",
            "status",
        ],
        "intelligence_signals": [
            "planned_step_count",
            "tool_call_count",
            "called_tools",
            "missing_required_tools",
            "blocked_tools",
            "needs_clarification",
            "used_tool_results",
            "next_best_action",
        ],
    }


def build_agent_flow_diagram() -> str:
    """生成可放入文档的 Mermaid Agent 流程图。"""

    return "\n".join(
        [
            "flowchart TD",
            "  A[OpenClaw / CLI / Console / Feishu Event] --> B[WorkflowRouter]",
            "  B --> C[WorkflowContextBuilder]",
            "  C --> D[WorkflowRunner]",
            "  D --> E[MeetFlowAgentLoop]",
            "  E --> F[ToolRegistry]",
            "  F --> G[AgentPolicy]",
            "  G --> H[FeishuClient / Knowledge / Storage]",
            "  H --> I[AgentTrace / Evaluation]",
        ]
    )


def infer_context_inputs(workflow_type: str) -> list[str]:
    """按工作流说明上下文来源。"""

    mapping = {
        "pre_meeting_brief": ["calendar_event_id", "meeting_id", "participants", "project_memory"],
        "post_meeting_followup": ["minute_token", "meeting_id", "participants", "human_review_candidates"],
        "risk_scan": ["task_id", "project_id", "task_mappings", "risk_notification_history"],
        "manual_qa": ["event_payload", "project_memory", "related_resources"],
    }
    return list(mapping.get(workflow_type, ["event_payload"]))


def infer_evidence_sources(workflow_type: str) -> list[str]:
    """按工作流说明证据来源。"""

    mapping = {
        "pre_meeting_brief": ["飞书日历", "知识库检索", "历史会议", "历史任务风险"],
        "post_meeting_followup": ["飞书妙记", "会议原文片段", "通讯录解析", "M4 Evidence Pack"],
        "risk_scan": ["飞书任务状态", "M4 task_mappings", "风险提醒降噪记录"],
        "manual_qa": ["用户输入", "受控工具结果", "项目记忆"],
    }
    return list(mapping.get(workflow_type, ["受控上下文"]))


def build_tool_workflow_map(workflow_runners: dict[str, WorkflowRunner]) -> dict[str, list[str]]:
    """建立工具到工作流的反向索引。"""

    mapping: dict[str, list[str]] = {}
    for workflow_type, runner in workflow_runners.items():
        for tool_name in runner.spec.allowed_tools:
            mapping.setdefault(tool_name, []).append(workflow_type)
    return mapping


def infer_side_effect(tool_name: str) -> str:
    """在没有真实工具注册表时，按名称推断副作用。"""

    if tool_name == "tasks.create_task":
        return "create_task"
    if tool_name.startswith("im.") or tool_name.endswith(".send_summary_card"):
        return "send_message"
    return "none"
