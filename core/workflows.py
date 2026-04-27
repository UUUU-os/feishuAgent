from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.agent_loop import MeetFlowAgentLoop
from core.llm import GenerationSettings
from core.models import AgentDecision, AgentRunResult, WorkflowContext


class WorkflowRunnerError(RuntimeError):
    """工作流骨架执行异常。"""


@dataclass(slots=True)
class WorkflowSpec:
    """确定性工作流骨架的静态规格。

    这个规格描述当前工作流允许哪些工具、期望输出什么、是否允许写操作。
    它不是为了取代 Agent Loop，而是给 Agent Loop 划定可解释、可测试的业务边界。
    """

    workflow_type: str
    allowed_tools: list[str] = field(default_factory=list)
    workflow_goal: str = ""
    output_schema: dict[str, Any] = field(default_factory=dict)
    allow_write: bool = False
    validation_rules: list[str] = field(default_factory=list)

    def resolve_tools(self, requested_tools: list[str]) -> list[str]:
        """在路由工具集和工作流允许工具集之间取交集。

        如果规格没有声明 `allowed_tools`，说明这个工作流暂时沿用路由结果。
        这样可以兼容 M2.8 已经完成的调试链路，同时为 M3-M5 的细粒度工具边界预留位置。
        """

        if not self.allowed_tools:
            return list(requested_tools)
        allowed = set(self.allowed_tools)
        return [tool_name for tool_name in requested_tools if tool_name in allowed]


@dataclass(slots=True)
class WorkflowValidationResult:
    """工作流确定性校验结果。"""

    ok: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为审计友好的字典。"""

        return {
            "ok": self.ok,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(slots=True)
class WorkflowRunner:
    """确定性工作流骨架基类。

    Runner 负责固定流程阶段：
    - 准备上下文
    - 整理工具边界
    - 调用 Agent Loop 这个 LLM 槽位
    - 做确定性校验
    - 把骨架信息写入结果，方便审计和调试
    """

    spec: WorkflowSpec

    def run(
        self,
        context: WorkflowContext,
        decision: AgentDecision,
        loop: MeetFlowAgentLoop,
        required_tools: list[str],
        workflow_goal: str = "",
        generation_settings: GenerationSettings | None = None,
    ) -> AgentRunResult:
        """执行一次带骨架的工作流。"""

        started_at = int(time.time())
        self.prepare_context(context=context, decision=decision)
        effective_tools = self.spec.resolve_tools(required_tools)
        final_goal = self.build_workflow_goal(workflow_goal or decision.reason)
        result = loop.run(
            context=context,
            required_tools=effective_tools,
            workflow_goal=final_goal,
            generation_settings=generation_settings,
        )
        validation = self.validate_output(result)
        result.payload["workflow_runner"] = {
            "workflow_type": self.spec.workflow_type,
            "stages": [
                "prepare_context",
                "build_plan_or_query",
                "agent_loop",
                "validate_output",
                "persist_and_audit",
            ],
            "requested_tools": list(required_tools),
            "effective_tools": list(effective_tools),
            "workflow_goal": final_goal,
            "validation": validation.to_dict(),
            "started_at": started_at,
            "finished_at": int(time.time()),
        }
        return result

    def prepare_context(self, context: WorkflowContext, decision: AgentDecision) -> None:
        """准备工作流上下文。

        基类只记录骨架信息；具体工作流可以在这里构造检索计划、清洗输入等。
        """

        context.raw_context.setdefault("workflow_runner", {})
        context.raw_context["workflow_runner"].update(
            {
                "workflow_type": self.spec.workflow_type,
                "decision": decision.to_dict(),
            }
        )

    def build_workflow_goal(self, workflow_goal: str) -> str:
        """合成进入 Agent Loop 的目标描述。"""

        spec_goal = self.spec.workflow_goal.strip()
        if spec_goal and workflow_goal:
            return f"{spec_goal}\n\n本次具体目标：{workflow_goal}"
        return spec_goal or workflow_goal

    def validate_output(self, result: AgentRunResult) -> WorkflowValidationResult:
        """校验 Agent Loop 输出。

        M2.8 阶段先做最小校验：必须有最终回答或受控终态。
        M3-M5 可以在具体 Runner 中升级为结构化 schema 校验。
        """

        if result.status in {"success", "max_iterations"}:
            return WorkflowValidationResult(ok=True)
        return WorkflowValidationResult(
            ok=False,
            errors=[f"Agent Loop 状态不是成功或受控终态：{result.status}"],
        )


@dataclass(slots=True)
class PreMeetingBriefWorkflow(WorkflowRunner):
    """会前背景卡片工作流骨架。

    当前先落地确定性阶段和检索计划草案，M3 后续再接入真正的知识检索工具、
    `MeetingBrief` 结构化解析和卡片渲染。
    """

    def prepare_context(self, context: WorkflowContext, decision: AgentDecision) -> None:
        """构造会前检索计划草案，并写入上下文。"""

        WorkflowRunner.prepare_context(self, context=context, decision=decision)
        retrieval_query = build_retrieval_query_draft(context)
        context.raw_context["retrieval_query_draft"] = retrieval_query

    def build_workflow_goal(self, workflow_goal: str) -> str:
        """强化会前工作流的输出要求。"""

        base_goal = WorkflowRunner.build_workflow_goal(self, workflow_goal)
        return (
            f"{base_goal}\n\n"
            "会前工作流约束：\n"
            "- 先基于上下文判断是否需要调用工具补充证据。\n"
            "- 生成结论时必须说明来源或指出证据不足。\n"
            "- 不要把未验证资料写成确定性事实。\n"
            "- 如果只拿到候选资料，请明确标记为“可能相关资料”。"
        )

    def validate_output(self, result: AgentRunResult) -> WorkflowValidationResult:
        """会前工作流的最小确定性校验。"""

        base = WorkflowRunner.validate_output(self, result)
        warnings = list(base.warnings)
        errors = list(base.errors)
        if result.status == "success" and not result.final_answer.strip():
            errors.append("会前工作流没有生成最终回答。")
        if result.status == "success" and result.loop_state and not result.loop_state.tool_results:
            warnings.append("本次会前工作流没有调用任何工具，可能缺少外部证据。")
        return WorkflowValidationResult(ok=not errors, warnings=warnings, errors=errors)


@dataclass(slots=True)
class PostMeetingFollowupWorkflow(WorkflowRunner):
    """会后总结与任务落地工作流骨架。

    当前只固定会后流程边界，不提前实现完整 M4：
    - 拉取妙记和纪要清洗仍由后续工具/模块完成
    - Action Item 结构化解析后续再升级为严格 schema
    - 任务创建必须继续经过 AgentPolicy
    """

    def prepare_context(self, context: WorkflowContext, decision: AgentDecision) -> None:
        """构造会后处理计划草案，并写入上下文。"""

        WorkflowRunner.prepare_context(self, context=context, decision=decision)
        context.raw_context["post_meeting_plan"] = build_post_meeting_plan_draft(context)

    def build_workflow_goal(self, workflow_goal: str) -> str:
        """强化会后工作流的输出和安全要求。"""

        base_goal = WorkflowRunner.build_workflow_goal(self, workflow_goal)
        return (
            f"{base_goal}\n\n"
            "会后工作流约束：\n"
            "- 先获取或确认妙记/纪要来源，再抽取结论和 Action Items。\n"
            "- Action Item 必须包含事项、负责人、截止时间、置信度和证据引用；缺失字段要标记待确认。\n"
            "- 如果负责人是“我”或具体姓名，必须先通过通讯录工具解析 open_id，不能编造 assignee_ids。\n"
            "- 任务创建属于写操作，只能作为工具请求发起，最终必须经过 AgentPolicy。\n"
            "- 不要把低置信度或缺少证据的待办直接描述为已创建任务。"
        )

    def validate_output(self, result: AgentRunResult) -> WorkflowValidationResult:
        """会后工作流的最小确定性校验。"""

        base = WorkflowRunner.validate_output(self, result)
        warnings = list(base.warnings)
        errors = list(base.errors)
        if result.status == "success" and not result.final_answer.strip():
            errors.append("会后工作流没有生成最终回答。")
        if result.status == "success" and result.loop_state and not result.loop_state.tool_results:
            warnings.append("本次会后工作流没有调用任何工具，可能尚未读取妙记或上下文证据。")
        for side_effect in result.side_effects:
            if side_effect.get("side_effect") == "create_task":
                warnings.append("本次会后工作流触发了任务创建副作用，请确认 AgentPolicy 审核记录。")
        return WorkflowValidationResult(ok=not errors, warnings=warnings, errors=errors)


@dataclass(slots=True)
class RiskScanWorkflow(WorkflowRunner):
    """任务风险巡检工作流骨架。

    当前只固定 M5 的确定性边界：
    - 风险规则预筛和任务状态读取后续由具体工具实现
    - Agent 负责解释风险原因和生成提醒草案
    - 是否推送仍由幂等、降噪和 AgentPolicy 决定
    """

    def prepare_context(self, context: WorkflowContext, decision: AgentDecision) -> None:
        """构造风险巡检计划草案，并写入上下文。"""

        WorkflowRunner.prepare_context(self, context=context, decision=decision)
        context.raw_context["risk_scan_plan"] = build_risk_scan_plan_draft(context)

    def build_workflow_goal(self, workflow_goal: str) -> str:
        """强化风险巡检工作流的低噪声要求。"""

        base_goal = WorkflowRunner.build_workflow_goal(self, workflow_goal)
        return (
            f"{base_goal}\n\n"
            "风险巡检工作流约束：\n"
            "- 先基于任务状态、截止时间、更新时间和历史提醒判断是否真的需要提醒。\n"
            "- 风险提醒必须说明风险原因、建议动作和来源，不要制造噪声。\n"
            "- 对已提醒过或证据不足的风险，应输出观察或待确认，而不是重复推送。\n"
            "- 推送消息属于写操作，只能作为工具请求发起，最终必须经过 AgentPolicy 和幂等/降噪规则。"
        )

    def validate_output(self, result: AgentRunResult) -> WorkflowValidationResult:
        """风险巡检工作流的最小确定性校验。"""

        base = WorkflowRunner.validate_output(self, result)
        warnings = list(base.warnings)
        errors = list(base.errors)
        if result.status == "success" and not result.final_answer.strip():
            errors.append("风险巡检工作流没有生成最终回答。")
        if result.status == "success" and result.loop_state and not result.loop_state.tool_results:
            warnings.append("本次风险巡检没有调用任何任务读取工具，可能缺少任务状态证据。")
        for side_effect in result.side_effects:
            if side_effect.get("side_effect") == "send_message":
                warnings.append("本次风险巡检触发了消息发送副作用，请确认降噪和幂等记录。")
        return WorkflowValidationResult(ok=not errors, warnings=warnings, errors=errors)


def build_default_workflow_runners() -> dict[str, WorkflowRunner]:
    """构建默认工作流 Runner。

    当前为会前、会后、风险巡检都提供专用骨架。
    这些骨架只固定阶段和安全边界，不提前替代 M3-M5 的具体业务实现。
    """

    return {
        "pre_meeting_brief": PreMeetingBriefWorkflow(
            spec=WorkflowSpec(
                workflow_type="pre_meeting_brief",
                allowed_tools=[
                    "calendar.list_events",
                    "docs.fetch_resource",
                    "minutes.fetch_resource",
                    "tasks.list_my_tasks",
                    "im.send_card",
                ],
                workflow_goal="生成带来源约束的会前背景知识卡片草案。",
                output_schema={
                    "type": "object",
                    "description": "MeetingBrief 草案，后续 M3 会升级为严格结构。",
                },
                allow_write=False,
                validation_rules=[
                    "final_answer_required",
                    "evidence_or_uncertainty_required",
                ],
            )
        ),
        "post_meeting_followup": PostMeetingFollowupWorkflow(
            spec=WorkflowSpec(
                workflow_type="post_meeting_followup",
                allowed_tools=[
                    "minutes.fetch_resource",
                    "docs.fetch_resource",
                    "tasks.create_task",
                    "contact.get_current_user",
                    "contact.search_user",
                    "im.send_card",
                ],
                workflow_goal="生成会后总结和 Action Item 草案，写操作必须交给 Policy 审核。",
                output_schema={
                    "type": "object",
                    "description": "MeetingSummary + ActionItem[] 草案，后续 M4 会升级为严格结构。",
                },
                allow_write=False,
                validation_rules=[
                    "action_items_require_owner_due_date_or_needs_confirm",
                    "evidence_refs_required",
                    "write_operations_policy_required",
                ],
            )
        ),
        "risk_scan": RiskScanWorkflow(
            spec=WorkflowSpec(
                workflow_type="risk_scan",
                allowed_tools=[
                    "tasks.list_my_tasks",
                    "calendar.list_events",
                    "im.send_card",
                ],
                workflow_goal="生成低噪声风险巡检结果，避免重复提醒。",
                output_schema={
                    "type": "object",
                    "description": "RiskAlert[] 草案，后续 M5 会升级为严格结构。",
                },
                allow_write=False,
                validation_rules=[
                    "risk_reason_required",
                    "dedupe_before_notify",
                    "write_operations_policy_required",
                ],
            )
        ),
        "manual_qa": WorkflowRunner(
            spec=WorkflowSpec(
                workflow_type="manual_qa",
                workflow_goal="在受控工具集内回答用户问题，输出必须基于工具或上下文。",
            )
        ),
    }


def build_retrieval_query_draft(context: WorkflowContext) -> dict[str, Any]:
    """根据会前上下文生成检索计划草案。

    这里不执行真实 RAG 检索，只把 M3 需要的 query enrichment 输入准备出来。
    """

    event_payload = context.event.payload if context.event else {}
    meeting_title = first_non_empty(
        event_payload,
        "summary",
        "title",
        "meeting_title",
        "calendar_summary",
    )
    attachment_titles = [
        str(item.get("title") or item.get("name") or item.get("url") or "")
        for item in event_payload.get("attachments", [])
        if isinstance(item, dict)
    ]
    participant_names = [
        str(item.get("display_name") or item.get("name") or item.get("email") or "")
        for item in context.participants
        if isinstance(item, dict)
    ]
    candidate_queries = [
        value
        for value in [
            meeting_title,
            context.project_id,
            " ".join(attachment_titles),
            " ".join(participant_names[:5]),
        ]
        if value
    ]
    return {
        "meeting_id": context.meeting_id,
        "calendar_event_id": context.calendar_event_id,
        "project_id": context.project_id,
        "meeting_title": meeting_title,
        "participant_names": participant_names,
        "attachment_titles": attachment_titles,
        "resource_types": ["doc", "sheet", "minute", "task"],
        "time_window": "recent_90_days",
        "search_queries": candidate_queries,
        "confidence": 0.4 if not meeting_title else 0.7,
        "missing_context": [] if meeting_title else ["meeting_title"],
    }


def build_post_meeting_plan_draft(context: WorkflowContext) -> dict[str, Any]:
    """根据会后上下文生成处理计划草案。"""

    return {
        "meeting_id": context.meeting_id,
        "calendar_event_id": context.calendar_event_id,
        "minute_token": context.minute_token,
        "project_id": context.project_id,
        "expected_steps": [
            "fetch_minutes_or_summary",
            "clean_transcript",
            "extract_decisions_and_action_items",
            "validate_owner_due_date_evidence",
            "create_task_or_request_confirmation",
        ],
        "required_fields_for_task_creation": [
            "summary",
            "assignee_ids",
            "due_timestamp_ms",
            "confidence",
            "evidence_refs",
        ],
        "missing_context": [] if context.minute_token else ["minute_token"],
    }


def build_risk_scan_plan_draft(context: WorkflowContext) -> dict[str, Any]:
    """根据风险巡检上下文生成处理计划草案。"""

    return {
        "task_id": context.task_id,
        "project_id": context.project_id,
        "expected_steps": [
            "fetch_task_status",
            "apply_risk_rules",
            "check_recent_notifications",
            "generate_risk_alert_draft",
            "notify_or_skip",
        ],
        "risk_signals": [
            "overdue",
            "due_soon",
            "stale_update",
            "missing_owner",
            "blocked_dependency",
        ],
        "missing_context": [] if context.task_id or context.project_id else ["task_id_or_project_id"],
    }


def first_non_empty(data: dict[str, Any], *keys: str) -> str:
    """读取第一个非空字段。"""

    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return str(value)
    return ""
