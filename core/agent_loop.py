from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from core.assistant_memory import build_clarification_question, create_pending_action_from_policy_decision
from core.eval_trace import (
    build_assistant_plan,
    build_trace_from_state,
    hash_arguments,
    sanitize_value,
    summarize_tool_result_data,
)
from core.llm import GenerationSettings, LLMProvider
from core.logging import get_logger
from core.models import AgentLoopState, AgentMessage, AgentRunResult, AgentToolResult, WorkflowContext
from core.observability import duration_ms_since, emit_structured_event, safe_error_message
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
    logger: logging.Logger = field(init=False)

    def __post_init__(self) -> None:
        self.logger = get_logger("meetflow.agent_loop")

    def run(
        self,
        context: WorkflowContext,
        required_tools: list[str],
        workflow_goal: str = "",
        generation_settings: GenerationSettings | None = None,
        allow_write: bool = False,
    ) -> AgentRunResult:
        """执行一次完整 Agent Loop。"""

        state = self._build_initial_state(
            context=context,
            required_tools=required_tools,
            workflow_goal=workflow_goal,
        )

        try:
            for iteration in range(1, self.max_iterations + 1):
                iteration_started_at = time.perf_counter()
                state.iteration = iteration
                self.logger.info(
                    "Agent Loop 开始一轮推理 trace_id=%s workflow=%s iteration=%s",
                    context.trace_id,
                    context.workflow_type,
                    iteration,
                )
                emit_structured_event(
                    "agent_loop_iteration_started",
                    trace_id=context.trace_id,
                    workflow_type=context.workflow_type,
                    iteration=iteration,
                    required_tools=required_tools,
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
                        allow_write=allow_write,
                    )
                    emit_structured_event(
                        "agent_loop_iteration_finished",
                        trace_id=context.trace_id,
                        workflow_type=context.workflow_type,
                        iteration=iteration,
                        status="tool_calls",
                        tool_call_count=len(response.tool_calls),
                        duration_ms=duration_ms_since(iteration_started_at),
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
                emit_structured_event(
                    "agent_loop_iteration_finished",
                    trace_id=context.trace_id,
                    workflow_type=context.workflow_type,
                    iteration=iteration,
                    status="final_answer",
                    finish_reason=response.finish_reason,
                    duration_ms=duration_ms_since(iteration_started_at),
                )
                return self._build_run_result(
                    context=context,
                    state=state,
                    status="success",
                    final_answer=response.content,
                )

            state.status = "max_iterations"
            state.stop_reason = "max_iterations"
            emit_structured_event(
                "agent_loop_max_iterations",
                trace_id=context.trace_id,
                workflow_type=context.workflow_type,
                max_iterations=self.max_iterations,
                tool_result_count=len(state.tool_results),
            )
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
                safe_error_message(error),
            )
            state.status = "failed"
            state.stop_reason = error.__class__.__name__
            return self._build_run_result(
                context=context,
                state=state,
                status="failed",
                final_answer=f"Agent Loop 执行失败：{safe_error_message(error)}",
                payload={"error_type": error.__class__.__name__, "error_message": safe_error_message(error)},
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
                "started_at": int(time.time()),
                "assistant_plan": build_assistant_plan(
                    workflow_type=context.workflow_type,
                    required_tools=required_tools,
                    workflow_goal=workflow_goal,
                ),
                "tool_call_traces": [],
                "policy_decisions": [],
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
        allow_write: bool,
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
            tool = self.tool_registry.get(tool_call.tool_name)
            schema_valid = True
            try:
                tool.validate_arguments(tool_call.arguments)
            except Exception:
                schema_valid = False
            if self.policy is not None:
                decision = self.policy.authorize_tool_call(
                    context=context,
                    tool=tool,
                    tool_call=tool_call,
                    allow_write=allow_write,
                    storage=self.storage,
                )
                emit_structured_event(
                    "policy_decision",
                    trace_id=context.trace_id,
                    workflow_type=context.workflow_type,
                    tool_name=tool.internal_name,
                    side_effect=tool.side_effect,
                    allow_write=allow_write,
                    status=decision.status,
                    reason=decision.reason,
                    required_fields=decision.required_fields,
                    idempotency_key=decision.idempotency_key,
                )
                state.extra.setdefault("policy_decisions", []).append(
                    {
                        "tool_name": tool.internal_name,
                        "side_effect": tool.side_effect,
                        "status": decision.status,
                        "reason": decision.reason,
                        "required_fields": list(decision.required_fields),
                        "idempotency_key_present": bool(decision.idempotency_key),
                        "allow_write": allow_write,
                    }
                )
                if not decision.is_allowed():
                    pending_action_id = ""
                    if decision.status == "needs_confirmation":
                        pending_action_id = self._persist_pending_action(
                            context=context,
                            tool_name=tool.internal_name,
                            tool_arguments=tool_call.arguments,
                            decision=decision,
                        )
                    now = int(time.time())
                    state.extra.setdefault("tool_call_traces", []).append(
                        {
                            "call_id": tool_call.call_id,
                            "tool_name": tool.internal_name,
                            "llm_tool_name": tool.llm_name,
                            "arguments": sanitize_value(tool_call.arguments),
                            "arguments_hash": hash_arguments(tool_call.arguments),
                            "schema_valid": schema_valid,
                            "status": decision.status,
                            "result_summary": {
                                "policy_status": decision.status,
                                "required_fields": list(decision.required_fields),
                                "pending_action_id": pending_action_id,
                            },
                            "started_at": now,
                            "finished_at": now,
                        }
                    )
                    state.append_tool_result(
                        AgentToolResult(
                            call_id=tool_call.call_id,
                            tool_name=tool.internal_name,
                            status=decision.status,
                            content=(
                                f"工具 {tool.internal_name} 被 AgentPolicy 拦截："
                                f"{decision.reason}"
                            ),
                            data={
                                "policy_decision": decision.to_dict(),
                                "pending_action_id": pending_action_id,
                            },
                            error_message=decision.reason,
                            started_at=int(time.time()),
                            finished_at=int(time.time()),
                        )
                    )
                    continue
                tool_call.arguments = decision.patched_arguments
                schema_valid = True
                try:
                    tool.validate_arguments(tool_call.arguments)
                except Exception:
                    schema_valid = False

            result = self.tool_registry.execute(tool_call)
            if len(result.content) > self.max_tool_result_chars:
                result.content = result.content[: self.max_tool_result_chars] + "\n...（工具结果已截断）"
            state.extra.setdefault("tool_call_traces", []).append(
                {
                    "call_id": result.call_id,
                    "tool_name": result.tool_name,
                    "llm_tool_name": tool.llm_name,
                    "arguments": sanitize_value(tool_call.arguments),
                    "arguments_hash": hash_arguments(tool_call.arguments),
                    "schema_valid": schema_valid,
                    "status": result.status,
                    "result_summary": summarize_tool_result_data(result.data),
                    "started_at": result.started_at,
                    "finished_at": result.finished_at,
                }
            )
            state.append_tool_result(result)

        state.pending_tool_calls = []

    def _persist_pending_action(
        self,
        *,
        context: WorkflowContext,
        tool_name: str,
        tool_arguments: dict[str, Any],
        decision: Any,
    ) -> str:
        """把需要人工补字段的工具调用落成可恢复动作。

        这里不执行任何外部副作用，只保存“刚才想做什么、缺什么、怎么恢复”。
        用户补充字段后，恢复路径仍会重新进入 Policy。
        """

        if self.storage is None:
            return ""
        raw_session = context.raw_context.get("assistant_session")
        session_id = ""
        if isinstance(raw_session, dict):
            session_id = str(raw_session.get("session_id") or "").strip()
        if not session_id:
            session_id = f"asst_{context.trace_id}"
        action = create_pending_action_from_policy_decision(
            context=context,
            session_id=session_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            decision=decision,
        )
        question = build_clarification_question(action)
        self.storage.save_pending_action(action)
        self.storage.save_clarification_question(question)
        emit_structured_event(
            "pending_action_saved",
            trace_id=context.trace_id,
            workflow_type=context.workflow_type,
            action_id=action.action_id,
            session_id=session_id,
            tool_name=tool_name,
            missing_fields=action.missing_fields,
            recovery_prompt=action.recovery_prompt,
        )
        return action.action_id

    def _build_run_result(
        self,
        context: WorkflowContext,
        state: AgentLoopState,
        status: str,
        final_answer: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentRunResult:
        """把 loop 状态转换为 AgentRunResult。"""

        side_effects = collect_side_effects(self.tool_registry, state)
        agent_trace = build_trace_from_state(
            context=context,
            state=state,
            status=status,
            final_answer=final_answer,
            side_effects=side_effects,
        )
        intelligence_signals = build_intelligence_signals(
            state=state,
            required_tools=list(state.extra.get("required_tools") or []),
        )
        return AgentRunResult(
            trace_id=context.trace_id,
            workflow_type=context.workflow_type,
            status=status,
            summary=build_result_summary(context.workflow_type, status, final_answer),
            final_answer=final_answer,
            side_effects=side_effects,
            loop_state=state,
            payload={
                "context": context.to_dict(),
                "assistant_plan": list(state.extra.get("assistant_plan") or []),
                "intelligence_signals": intelligence_signals,
                "agent_trace": agent_trace.to_dict(),
                **(payload or {}),
            },
            created_at=int(time.time()),
        )


def build_system_prompt(workflow_type: str, required_tools: list[str]) -> str:
    """构建 Agent Loop 的系统提示词。"""

    tools_text = "\n".join(f"- {tool}" for tool in required_tools) or "- 无"
    return (
        "你是 MeetFlow，一个飞书会议知识闭环垂直 Agent。\n"
        "你不是普通问答机器人，而是会议助手：需要理解会议上下文、选择工具、基于证据推进下一步。\n"
        "你必须先形成简短计划，再根据可用工具逐步补证据；不要编造不存在的飞书数据。\n"
        "如果缺负责人、截止时间、目标群或证据不足，要主动提出澄清问题，而不是盲目执行。\n"
        "如果工具失败，需要说明失败原因、保留已知事实，并给出可恢复的下一步建议。\n"
        "写操作只表示请求执行，后续会由 AgentPolicy 决定是否允许自动执行。\n"
        "最终回答必须包含：已确认事实、证据/工具来源、阻塞点、建议下一步。\n\n"
        f"当前工作流：{workflow_type}\n"
        f"本次允许使用的内部工具：\n{tools_text}"
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
    }
    pre_meeting_card_payload = context.raw_context.get("pre_meeting_card_payload")
    if isinstance(pre_meeting_card_payload, dict):
        # D2 会前卡片由确定性阶段生成，传给 LLM/调试模型时只作为受控发送参数，
        # 避免自动触发链路退回到通用 im.send_card 最小卡片。
        compact_context["pre_meeting_card_payload"] = pre_meeting_card_payload
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


def build_intelligence_signals(state: AgentLoopState, required_tools: list[str]) -> dict[str, Any]:
    """生成用于产品和评测的智能化行为信号。"""

    tool_traces = list(state.extra.get("tool_call_traces") or [])
    policy_decisions = list(state.extra.get("policy_decisions") or [])
    called_tools = [str(item.get("tool_name", "")) for item in tool_traces if isinstance(item, dict)]
    required_set = set(required_tools)
    called_set = set(called_tools)
    missing_required_tools = sorted(required_set - called_set)
    blocked_tools = [
        {
            "tool_name": item.get("tool_name", ""),
            "status": item.get("status", ""),
            "required_fields": item.get("required_fields", []),
        }
        for item in policy_decisions
        if isinstance(item, dict) and item.get("status") in {"blocked", "needs_confirmation"}
    ]
    return {
        "planned_step_count": len(state.extra.get("assistant_plan") or []),
        "tool_call_count": len(called_tools),
        "called_tools": called_tools,
        "missing_required_tools": missing_required_tools,
        "blocked_tools": blocked_tools,
        "needs_clarification": any(item.get("status") == "needs_confirmation" for item in policy_decisions if isinstance(item, dict)),
        "used_tool_results": any(result.is_success() for result in state.tool_results),
        "next_best_action": build_next_best_action(blocked_tools, missing_required_tools),
    }


def build_next_best_action(
    blocked_tools: list[dict[str, Any]],
    missing_required_tools: list[str],
) -> str:
    """根据运行轨迹给出下一步建议。"""

    if blocked_tools:
        first = blocked_tools[0]
        fields = first.get("required_fields") or []
        if fields:
            return "请补充 " + "、".join(str(field) for field in fields) + " 后继续。"
        return f"请确认工具 {first.get('tool_name', '')} 的执行条件后继续。"
    if missing_required_tools:
        return "建议补充调用缺失工具：" + "、".join(missing_required_tools)
    return "可以基于当前工具结果输出结论或进入下一步工作流。"
