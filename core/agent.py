from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Callable

from adapters.feishu_client import FeishuClient, OAuthTokenBundle
from adapters.feishu_tools import create_feishu_tool_registry
from config.loader import Settings
from core.agent_loop import MeetFlowAgentLoop
from core.context import WorkflowContextBuilder
from core.llm import GenerationSettings, LLMProvider, create_llm_provider
from core.knowledge import KnowledgeIndexStore, register_knowledge_tools
from core.logging import bind_trace_id, get_logger, reset_trace_id
from core.models import AgentDecision, AgentInput, AgentRunResult
from core.observability import configure_structured_events, duration_ms_since, emit_structured_event, safe_error_message
from core.policy import AgentPolicy
from core.router import WorkflowRouter
from core.storage import MeetFlowStorage
from core.tools import ToolRegistry
from core.workflows import WorkflowRunner, WorkflowSpec, build_default_workflow_runners


class MeetFlowAgentError(RuntimeError):
    """MeetFlow Agent 主入口异常。"""


@dataclass(slots=True)
class MeetFlowAgent:
    """MeetFlow 业务侧垂直 Agent 主入口。

    这个类负责把 T2.8-T2.13 的模块串起来：
    - WorkflowRouter：判断当前事件应该进入哪个业务工作流
    - WorkflowContextBuilder：把原始 payload 转成业务上下文
    - MeetFlowAgentLoop：让 LLM 在受控工具集中思考和调用工具
    - MeetFlowStorage：保存运行结果和幂等键
    """

    router: WorkflowRouter
    context_builder: WorkflowContextBuilder
    loop: MeetFlowAgentLoop
    storage: MeetFlowStorage | None = None
    policy: AgentPolicy | None = None
    workflow_runners: dict[str, WorkflowRunner] = field(default_factory=build_default_workflow_runners)
    enable_idempotency: bool = True
    logger: logging.Logger = field(init=False)

    def __post_init__(self) -> None:
        self.logger = get_logger("meetflow.agent")

    def run(
        self,
        agent_input: AgentInput,
        workflow_goal: str = "",
        generation_settings: GenerationSettings | None = None,
        allow_write: bool = False,
    ) -> AgentRunResult:
        """执行一次完整 MeetFlow Agent 运行。"""

        started_at = time.perf_counter()
        trace_id = bind_trace_id(agent_input.trace_id if agent_input.trace_id != "-" else None)
        agent_input.trace_id = trace_id
        self.logger.info(
            "MeetFlowAgent 开始执行 event_type=%s source=%s allow_write=%s",
            agent_input.event_type,
            agent_input.source,
            allow_write,
        )

        try:
            decision = self.router.route(agent_input)
            self._emit_workflow_started(agent_input=agent_input, decision=decision, allow_write=allow_write)
            self._emit_route_decision(trace_id=trace_id, decision=decision)
            if decision.status != "ready":
                result = self._build_terminal_result(
                    trace_id=trace_id,
                    decision=decision,
                    status=decision.status,
                    summary=decision.reason,
                )
                self._save_result(result)
                self._emit_workflow_finished(result=result, started_at=started_at)
                return result

            if self._is_duplicate(decision):
                result = self._build_terminal_result(
                    trace_id=trace_id,
                    decision=decision,
                    status="skipped",
                    summary=f"幂等键已处理，跳过重复执行：{decision.idempotency_key}",
                )
                self._save_result(result)
                self._emit_workflow_finished(result=result, started_at=started_at)
                return result

            context = self.context_builder.build(agent_input=agent_input, decision=decision)
            required_tools = self._filter_required_tools(
                required_tools=decision.required_tools,
                allow_write=allow_write,
            )
            runner = self._resolve_workflow_runner(decision)
            result = runner.run(
                context=context,
                decision=decision,
                loop=self.loop,
                required_tools=required_tools,
                workflow_goal=workflow_goal or decision.reason,
                generation_settings=generation_settings,
                storage=self.storage,
                allow_write=allow_write,
            )
            result.payload["decision"] = decision.to_dict()
            result.payload["effective_required_tools"] = required_tools

            self._mark_idempotency(decision, result)
            self._save_result(result)
            self._emit_workflow_finished(result=result, started_at=started_at)
            return result
        except Exception as error:  # noqa: BLE001 - 主入口需要兜底，避免真实事件静默丢失。
            self.logger.exception("MeetFlowAgent 执行失败")
            safe_message = safe_error_message(error)
            result = AgentRunResult(
                trace_id=trace_id,
                workflow_type="agent_error",
                status="failed",
                summary=f"MeetFlowAgent 执行失败：{safe_message}",
                final_answer=f"MeetFlowAgent 执行失败：{safe_message}",
                payload={"error_type": error.__class__.__name__, "error_message": safe_message},
                created_at=int(time.time()),
            )
            self._save_result(result)
            self._emit_workflow_failed(
                trace_id=trace_id,
                workflow_type=result.workflow_type,
                error=error,
                started_at=started_at,
            )
            return result
        finally:
            reset_trace_id()

    def _filter_required_tools(self, required_tools: list[str], allow_write: bool) -> list[str]:
        """根据写权限开关过滤本次暴露给 LLM 的工具。"""

        if allow_write:
            return list(required_tools)

        read_only_tools: list[str] = []
        for tool_name in required_tools:
            tool = self.loop.tool_registry.get(tool_name)
            if tool.read_only:
                read_only_tools.append(tool_name)
            else:
                self.logger.info("写工具未开放，已从本次工具集中移除 tool=%s", tool_name)
        return read_only_tools

    def _resolve_workflow_runner(self, decision: AgentDecision) -> WorkflowRunner:
        """读取当前工作流对应的确定性骨架。"""

        runner = self.workflow_runners.get(decision.workflow_type)
        if runner is not None:
            return runner
        return WorkflowRunner(
            spec=WorkflowSpec(
                workflow_type=decision.workflow_type,
                workflow_goal=decision.reason,
            )
        )

    def _is_duplicate(self, decision: AgentDecision) -> bool:
        """判断当前幂等键是否已经执行过。"""

        if not self.enable_idempotency or not self.storage or not decision.idempotency_key:
            return False
        return self.storage.is_idempotency_key_processed(decision.idempotency_key)

    def _mark_idempotency(self, decision: AgentDecision, result: AgentRunResult) -> None:
        """在成功或受控结束后记录幂等键。"""

        if not self.enable_idempotency or not self.storage or not decision.idempotency_key:
            return
        if result.status not in {"success", "max_iterations"}:
            return
        self.storage.record_idempotency_key(
            idempotency_key=decision.idempotency_key,
            workflow_name=decision.workflow_type,
            trace_id=result.trace_id,
        )

    def _save_result(self, result: AgentRunResult) -> None:
        """把 Agent 运行结果保存到本地存储。"""

        if not self.storage:
            return
        self.storage.save_workflow_result(result.to_workflow_result())

    def _build_terminal_result(
        self,
        trace_id: str,
        decision: AgentDecision,
        status: str,
        summary: str,
    ) -> AgentRunResult:
        """构造不进入 LLM Loop 的终态结果。"""

        return AgentRunResult(
            trace_id=trace_id,
            workflow_type=decision.workflow_type,
            status=status,
            summary=summary,
            final_answer=summary,
            payload={"decision": decision.to_dict()},
            created_at=int(time.time()),
        )

    def _emit_workflow_started(self, agent_input: AgentInput, decision: AgentDecision, allow_write: bool) -> None:
        """记录一次 Agent 工作流开始事件。"""

        payload = agent_input.payload
        emit_structured_event(
            "workflow_started",
            trace_id=agent_input.trace_id,
            workflow_type=decision.workflow_type,
            status=decision.status,
            source=agent_input.source,
            actor=agent_input.actor,
            event_type_input=agent_input.event_type,
            trigger_type=agent_input.trigger_type,
            allow_write=allow_write,
            idempotency_key=decision.idempotency_key,
            group_id=build_group_id(decision, payload),
            metadata={
                "project_id": payload.get("project_id", ""),
                "meeting_id": payload.get("meeting_id", ""),
                "calendar_event_id": payload.get("calendar_event_id", payload.get("event_id", "")),
                "minute_token": payload.get("minute_token", ""),
                "task_id": payload.get("task_id", ""),
            },
        )

    def _emit_route_decision(self, trace_id: str, decision: AgentDecision) -> None:
        """记录路由结果，便于复盘本次为什么进入某个工作流。"""

        emit_structured_event(
            "route_decision",
            trace_id=trace_id,
            workflow_type=decision.workflow_type,
            status=decision.status,
            confidence=decision.confidence,
            reason=decision.reason,
            required_tools=decision.required_tools,
            idempotency_key=decision.idempotency_key,
            extra=decision.extra,
        )

    def _emit_workflow_finished(self, result: AgentRunResult, started_at: float) -> None:
        """记录工作流受控结束事件。"""

        loop_state = result.loop_state
        emit_structured_event(
            "workflow_finished",
            trace_id=result.trace_id,
            workflow_type=result.workflow_type,
            status=result.status,
            duration_ms=duration_ms_since(started_at),
            iterations=loop_state.iteration if loop_state else 0,
            tool_call_count=len(loop_state.tool_results) if loop_state else 0,
            side_effects=result.side_effects,
            summary=result.summary,
        )

    def _emit_workflow_failed(
        self,
        trace_id: str,
        workflow_type: str,
        error: Exception,
        started_at: float,
    ) -> None:
        """记录主入口未受控异常。"""

        emit_structured_event(
            "workflow_failed",
            trace_id=trace_id,
            workflow_type=workflow_type,
            status="failed",
            duration_ms=duration_ms_since(started_at),
            error_type=error.__class__.__name__,
            error_message=safe_error_message(error),
            retryable=False,
        )


def build_group_id(decision: AgentDecision, payload: dict[str, object]) -> str:
    """按业务对象生成 trace 分组 ID。"""

    if decision.workflow_type == "pre_meeting_brief":
        value = payload.get("calendar_event_id") or payload.get("meeting_id") or payload.get("event_id")
        return f"meeting:{value}" if value else ""
    if decision.workflow_type == "post_meeting_followup":
        value = payload.get("minute_token") or payload.get("meeting_id")
        return f"minute:{value}" if value else ""
    if decision.workflow_type == "risk_scan":
        value = payload.get("task_id") or payload.get("project_id")
        return f"task:{value}" if value else ""
    return ""


def create_meetflow_agent(
    settings: Settings,
    llm_provider: LLMProvider | None = None,
    tool_registry: ToolRegistry | None = None,
    storage: MeetFlowStorage | None = None,
    policy: AgentPolicy | None = None,
    enable_idempotency: bool = True,
    user_token_callback: Callable[[OAuthTokenBundle], None] | None = None,
) -> MeetFlowAgent:
    """根据系统配置创建 MeetFlowAgent。

    这里是后续 CLI、事件订阅、定时任务的统一装配入口。
    """

    configure_structured_events(settings.observability)
    final_storage = storage or MeetFlowStorage(settings.storage)
    final_storage.initialize()

    client = FeishuClient(settings.feishu, user_token_callback=user_token_callback)
    final_tool_registry = tool_registry or create_feishu_tool_registry(
        client=client,
        default_chat_id=settings.feishu.default_chat_id,
    )
    if tool_registry is None:
        knowledge_store = KnowledgeIndexStore(
            settings.storage,
            embedding_settings=settings.embedding,
            reranker_settings=settings.reranker,
            search_settings=settings.knowledge_search,
        )
        knowledge_store.initialize()
        register_knowledge_tools(final_tool_registry, knowledge_store)
    final_llm_provider = llm_provider or create_llm_provider(settings.llm)
    final_policy = policy or AgentPolicy()

    return MeetFlowAgent(
        router=WorkflowRouter(),
        context_builder=WorkflowContextBuilder(
            storage=final_storage,
            default_project_id="meetflow",
        ),
        loop=MeetFlowAgentLoop(
            llm_provider=final_llm_provider,
            tool_registry=final_tool_registry,
            policy=final_policy,
            storage=final_storage,
        ),
        storage=final_storage,
        policy=final_policy,
        enable_idempotency=enable_idempotency,
    )
