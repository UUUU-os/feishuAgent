from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from core.llm import GenerationSettings, LLMProvider
from core.logging import get_logger
from core.models import AgentLoopState, AgentMessage, AgentRunResult, AgentToolResult, WorkflowContext
from core.policy import AgentPolicy
from core.storage import MeetFlowStorage
from core.tools import ToolRegistry


class AgentLoopError(RuntimeError):
    """Agent Loop 执行异常。"""


@dataclass(slots=True)
class MeetFlowAgentLoop:
    """MeetFlow 垂直 Agent 的 LLM 工具调用主循环。

    这个类负责真正的 agent loop：
    - 构建 system / user 消息
    - 调用 LLMProvider
    - 执行模型返回的工具调用
    - 将工具结果继续喂回模型
    - 最终产出 AgentRunResult
    """

    llm_provider: LLMProvider
    tool_registry: ToolRegistry
    max_iterations: int = 6
    max_tool_result_chars: int = 4000
    policy: AgentPolicy | None = None
    storage: MeetFlowStorage | None = None
    allow_write: bool = False
    logger: logging.Logger = field(init=False)

    def __post_init__(self) -> None:
        self.logger = get_logger("meetflow.agent_loop")

    def run(
        self,
        context: WorkflowContext,
        required_tools: list[str],
        workflow_goal: str = "",
        generation_settings: GenerationSettings | None = None,
    ) -> AgentRunResult:
        """执行一次完整 Agent Loop。"""

        state = self._build_initial_state(
            context=context,
            required_tools=required_tools,
            workflow_goal=workflow_goal,
        )

        try:
            for iteration in range(1, self.max_iterations + 1):
                state.iteration = iteration
                self.logger.info(
                    "Agent Loop 开始一轮推理 trace_id=%s workflow=%s iteration=%s",
                    context.trace_id,
                    context.workflow_type,
                    iteration,
                )

                tool_definitions = self.tool_registry.get_definitions(required_tools)
                response = self.llm_provider.chat(
                    messages=state.messages,
                    tools=tool_definitions,
                    settings=generation_settings,
                )

                if response.should_execute_tools:
                    self._handle_tool_calls(
                        context=context,
                        state=state,
                        tool_calls=response.tool_calls,
                    )
                    continue

                state.status = "finished"
                state.stop_reason = response.finish_reason or "final_answer"
                state.append_message(
                    AgentMessage(
                        role="assistant",
                        content=response.content,
                        metadata={
                            "model": response.model,
                            "finish_reason": response.finish_reason,
                            "usage": response.usage,
                        },
                    )
                )
                return self._build_run_result(
                    context=context,
                    state=state,
                    status="success",
                    final_answer=response.content,
                )

            state.status = "max_iterations"
            state.stop_reason = "max_iterations"
            return self._build_run_result(
                context=context,
                state=state,
                status="max_iterations",
                final_answer="Agent Loop 已达到最大轮数，未生成最终答案。",
            )
        except Exception as error:  # noqa: BLE001 - Agent Loop 顶层需要统一包装异常结果。
            self.logger.error(
                "Agent Loop 执行失败 trace_id=%s workflow=%s error=%s",
                context.trace_id,
                context.workflow_type,
                error,
            )
            state.status = "failed"
            state.stop_reason = error.__class__.__name__
            return self._build_run_result(
                context=context,
                state=state,
                status="failed",
                final_answer=f"Agent Loop 执行失败：{error}",
                payload={"error_type": error.__class__.__name__, "error_message": str(error)},
            )

    def _build_initial_state(
        self,
        context: WorkflowContext,
        required_tools: list[str],
        workflow_goal: str,
    ) -> AgentLoopState:
        """构建初始 loop 状态和消息。"""

        state = AgentLoopState(
            loop_id=f"{context.trace_id}:{context.workflow_type}:{int(time.time())}",
            trace_id=context.trace_id,
            workflow_type=context.workflow_type,
            max_iterations=self.max_iterations,
            extra={
                "required_tools": required_tools,
                "workflow_goal": workflow_goal,
            },
        )
        state.append_message(
            AgentMessage(
                role="system",
                content=build_system_prompt(context.workflow_type, required_tools),
            )
        )
        state.append_message(
            AgentMessage(
                role="user",
                content=build_runtime_context_message(context, workflow_goal),
            )
        )
        return state

    def _handle_tool_calls(
        self,
        context: WorkflowContext,
        state: AgentLoopState,
        tool_calls: list[Any],
    ) -> None:
        """执行模型请求的工具调用，并把结果追加回消息列表。"""

        state.pending_tool_calls = list(tool_calls)
        state.append_message(
            AgentMessage(
                role="assistant",
                content="",
                tool_calls=list(tool_calls),
                metadata={"stage": "tool_calls_requested"},
            )
        )

        for tool_call in tool_calls:
            if self.policy is not None:
                tool = self.tool_registry.get(tool_call.tool_name)
                decision = self.policy.authorize_tool_call(
                    context=context,
                    tool=tool,
                    tool_call=tool_call,
                    allow_write=self.allow_write,
                    storage=self.storage,
                )
                if not decision.is_allowed():
                    state.append_tool_result(
                        AgentToolResult(
                            call_id=tool_call.call_id,
                            tool_name=tool.internal_name,
                            status=decision.status,
                            content=(
                                f"工具 {tool.internal_name} 被 AgentPolicy 拦截："
                                f"{decision.reason}"
                            ),
                            data={"policy_decision": decision.to_dict()},
                            error_message=decision.reason,
                            started_at=int(time.time()),
                            finished_at=int(time.time()),
                        )
                    )
                    continue
                tool_call.arguments = decision.patched_arguments

            result = self.tool_registry.execute(tool_call)
            if len(result.content) > self.max_tool_result_chars:
                result.content = result.content[: self.max_tool_result_chars] + "\n...（工具结果已截断）"
            state.append_tool_result(result)

        state.pending_tool_calls = []

    def _build_run_result(
        self,
        context: WorkflowContext,
        state: AgentLoopState,
        status: str,
        final_answer: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentRunResult:
        """把 loop 状态转换为 AgentRunResult。"""

        return AgentRunResult(
            trace_id=context.trace_id,
            workflow_type=context.workflow_type,
            status=status,
            summary=build_result_summary(context.workflow_type, status, final_answer),
            final_answer=final_answer,
            side_effects=collect_side_effects(self.tool_registry, state),
            loop_state=state,
            payload={
                "context": context.to_dict(),
                **(payload or {}),
            },
            created_at=int(time.time()),
        )


def build_system_prompt(workflow_type: str, required_tools: list[str]) -> str:
    """构建 Agent Loop 的系统提示词。"""

    tools_text = "\n".join(f"- {tool}" for tool in required_tools) or "- 无"
    base_prompt = (
        "你是 MeetFlow，一个飞书会议知识闭环垂直 Agent。\n"
        "你必须基于工具结果和上下文回答，不要编造不存在的飞书数据。\n"
        "如果需要外部信息，优先调用可用工具；如果工具失败，需要说明失败原因并给出降级建议。\n"
        "写操作只表示请求执行，后续会由 AgentPolicy 决定是否允许自动执行。\n\n"
        f"当前工作流：{workflow_type}\n"
        f"本次允许使用的内部工具：\n{tools_text}"
    )
    if workflow_type != "post_meeting_followup":
        return base_prompt
    return (
        f"{base_prompt}\n\n"
        "M4 会后 Agent 要求：\n"
        "- 先确认妙记/纪要来源，必要时调用 minutes.fetch_resource 读取真实内容。\n"
        "- 使用 post_meeting.build_artifacts 审阅关键结论、行动项和开放问题。\n"
        "- 需要背景资料时调用 post_meeting.enrich_related_knowledge 或 knowledge.search，query 只能来自会议主题、项目名、关键结论和行动项标题。\n"
        "- 不要在会后主链路请求 tasks.create_task；即使字段完整、高置信，也必须先发送/保存待确认任务。\n"
        "- 负责人为“我”时先调用 contact.get_current_user；负责人是姓名时先调用 contact.search_user；群体负责人进入待确认。\n"
        "- 缺负责人、缺截止时间、群体负责人、低置信或证据不足的行动项，应说明待补充原因。\n"
        "- 最终回答必须分别说明已发出的待确认、跳过原因，以及任何工具失败。"
    )


def build_runtime_context_message(context: WorkflowContext, workflow_goal: str) -> str:
    """把 WorkflowContext 转换成 LLM 可读的运行时上下文。"""

    compact_context = {
        "workflow_type": context.workflow_type,
        "meeting_id": context.meeting_id,
        "calendar_event_id": context.calendar_event_id,
        "minute_token": context.minute_token,
        "task_id": context.task_id,
        "project_id": context.project_id,
        "participants": context.participants,
        "related_resources": [resource.to_dict() for resource in context.related_resources],
        "memory_snapshot": context.memory_snapshot,
        "event": context.event.to_dict() if context.event else None,
        "raw_context": context.raw_context,
    }
    return (
        f"工作流目标：{workflow_goal or '请根据上下文完成当前工作流目标。'}\n\n"
        "运行时上下文 JSON：\n"
        f"{json.dumps(compact_context, ensure_ascii=False, indent=2)}"
    )


def collect_side_effects(tool_registry: ToolRegistry, state: AgentLoopState) -> list[dict[str, Any]]:
    """收集本次 loop 中已经执行过的写操作工具。"""

    side_effects: list[dict[str, Any]] = []
    for result in state.tool_results:
        if not result.is_success():
            continue
        try:
            tool = tool_registry.get(result.tool_name)
        except Exception:
            continue
        if tool.read_only:
            continue
        side_effects.append(
            {
                "tool_name": tool.internal_name,
                "side_effect": tool.side_effect,
                "call_id": result.call_id,
                "finished_at": result.finished_at,
            }
        )
    return side_effects


def build_result_summary(workflow_type: str, status: str, final_answer: str) -> str:
    """构造 AgentRunResult 的摘要。"""

    if final_answer:
        return final_answer[:120]
    return f"{workflow_type} finished with status={status}"
