from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# 允许直接通过 `python3 scripts/agent_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLMSettings, load_settings
from core import (
    AgentMessage,
    AgentPolicy,
    AgentTool,
    AgentToolCall,
    DryRunLLMProvider,
    GenerationSettings,
    KnowledgeIndexStore,
    LLMConfigError,
    LLMProvider,
    LLMResponse,
    MeetFlowAgentLoop,
    MeetFlowStorage,
    ToolRegistry,
    WorkflowContextBuilder,
    WorkflowRouter,
    build_agent_input,
    configure_logging,
    create_llm_provider,
    register_knowledge_tools,
)
from core.agent import MeetFlowAgent, create_meetflow_agent
from scripts.meetflow_agent_live_test import (
    build_llm_settings,
    build_workflow_goal,
    enrich_required_tools,
    save_token_bundle,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="MeetFlow Agent 手动调试入口：打印决策、上下文、Loop，并可切换真实飞书。",
    )
    parser.add_argument("--event-type", default="meeting.soon", help="事件类型。")
    parser.add_argument("--workflow-type", default="", help="仅 message.command 下用于指定目标工作流。")
    parser.add_argument("--prompt", default="", help="本次 Agent 目标；不传则使用路由原因。")
    parser.add_argument("--backend", choices=["local", "feishu"], default="local", help="local 不访问飞书；feishu 真实调用飞书。")
    parser.add_argument("--llm-provider", default="scripted_debug", help="scripted_debug / dry-run / deepseek / settings。")
    parser.add_argument("--tool", action="append", default=[], help="显式开放工具，可传多次。")
    parser.add_argument("--calendar-id", default="primary", help="日历 ID。")
    parser.add_argument("--start-time", default="", help="Unix 秒级开始时间。")
    parser.add_argument("--end-time", default="", help="Unix 秒级结束时间。")
    parser.add_argument("--project-id", default="meetflow", help="项目 ID。")
    parser.add_argument("--meeting-id", default="", help="会议 ID。")
    parser.add_argument("--calendar-event-id", default="", help="日历事件 ID。")
    parser.add_argument("--minute-token", default="", help="妙记 token。")
    parser.add_argument("--document", default="", help="飞书文档 URL 或 token。")
    parser.add_argument("--task-id", default="", help="任务 ID。")
    parser.add_argument("--assignee-name", default="", help="调试用负责人姓名。")
    parser.add_argument("--model", default="", help="临时覆盖模型名。")
    parser.add_argument("--api-base", default="", help="临时覆盖模型 API base。")
    parser.add_argument("--api-key-env", default="", help="从指定环境变量读取 API Key。")
    parser.add_argument("--temperature", type=float, default=None, help="临时覆盖采样温度。")
    parser.add_argument("--max-tokens", type=int, default=None, help="临时覆盖最大输出 token 数。")
    parser.add_argument("--max-iterations", type=int, default=4, help="Agent Loop 最大轮数。")
    parser.add_argument("--allow-write", action="store_true", help="允许写工具经过 Policy 后执行。")
    parser.add_argument("--enable-idempotency", action="store_true", help="启用幂等去重。")
    parser.add_argument("--plan-only", action="store_true", help="只打印 AgentInput / AgentDecision / WorkflowContext，不运行 Loop。")
    parser.add_argument("--show-full", action="store_true", help="打印完整 AgentRunResult。")
    return parser.parse_args()


def main() -> int:
    """执行手动调试。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)

    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    payload = build_payload(args, settings.app.timezone)
    agent_input = build_agent_input(
        event_type=args.event_type,
        payload=payload,
        source="agent_demo",
    )
    router = WorkflowRouter()
    decision = router.route(agent_input)
    context = WorkflowContextBuilder(storage=storage, default_project_id=args.project_id).build(
        agent_input=agent_input,
        decision=decision,
    )

    print_section("AgentInput", agent_input.to_dict())
    print_section("AgentDecision", decision.to_dict())
    print_section("WorkflowContext", context.to_dict())

    if args.plan_only:
        print("\nplan-only 已结束，没有运行 LLM Loop，也没有调用任何工具。")
        return 0

    try:
        agent, generation = build_agent(args, settings, storage)
    except LLMConfigError as error:
        print(f"\nLLM 配置错误：{error}")
        return 2

    agent.loop.max_iterations = args.max_iterations
    result = agent.run(
        agent_input=agent_input,
        workflow_goal=build_goal(args, decision.reason, payload),
        generation_settings=generation,
        allow_write=args.allow_write,
    )
    print_loop_summary(result.to_dict(), show_full=args.show_full)
    return 0 if result.status in {"success", "max_iterations", "skipped"} else 1


def build_payload(args: argparse.Namespace, timezone: str) -> dict[str, object]:
    """构造用于调试的 AgentInput.payload。"""

    start_time, end_time = resolve_time_window(args, timezone)
    tools = enrich_required_tools(args.tool or default_tools_for_event(args.event_type))
    workflow_type = args.workflow_type or default_workflow_for_event(args.event_type)
    payload: dict[str, object] = {
        "workflow_type": workflow_type,
        "required_tools": tools,
        "calendar_id": args.calendar_id,
        "start_time": start_time,
        "end_time": end_time,
        "project_id": args.project_id,
        "idempotency_key": f"{args.calendar_id}:{start_time}:{end_time}",
    }
    optional_values = {
        "meeting_id": args.meeting_id,
        "calendar_event_id": args.calendar_event_id,
        "minute_token": args.minute_token,
        "minute": args.minute_token,
        "document": args.document,
        "task_id": args.task_id,
        "assignee_name": args.assignee_name,
    }
    for key, value in optional_values.items():
        if value:
            payload[key] = value
    return payload


def default_tools_for_event(event_type: str) -> list[str]:
    """为常见调试事件提供更安全的默认工具集。"""

    if event_type == "minute.ready":
        return ["minutes.fetch_resource", "tasks.create_task", "im.send_card"]
    if event_type == "risk.scan.tick":
        return ["tasks.list_my_tasks", "im.send_card"]
    if event_type == "message.command":
        return ["calendar.list_events"]
    return ["calendar.list_events", "tasks.list_my_tasks"]


def default_workflow_for_event(event_type: str) -> str:
    """为 message.command 之外的事件返回空字符串，交给路由规则决定。"""

    if event_type == "message.command":
        return "manual_qa"
    return ""


def resolve_time_window(args: argparse.Namespace, timezone: str) -> tuple[str, str]:
    """解析时间窗口，默认取今天。"""

    if args.start_time and args.end_time:
        return args.start_time, args.end_time
    tz = ZoneInfo(timezone or "Asia/Shanghai")
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    return str(int(today.timestamp())), str(int(tomorrow.timestamp()))


def build_goal(args: argparse.Namespace, route_reason: str, payload: dict[str, object]) -> str:
    """构造调试目标。"""

    prompt = args.prompt or route_reason
    return build_workflow_goal(prompt, payload)


def build_agent(
    args: argparse.Namespace,
    settings: object,
    storage: MeetFlowStorage,
) -> tuple[MeetFlowAgent, GenerationSettings]:
    """根据 backend / llm-provider 装配 Agent。"""

    if args.llm_provider == "scripted_debug":
        llm_settings = LLMSettings(
            provider="scripted-debug",
            model="scripted-debug",
            api_base="",
            api_key="",
            temperature=0.0,
            max_tokens=1000,
            reasoning_effort="",
        )
        provider: LLMProvider = ScriptedDebugProvider()
    elif args.llm_provider == "dry-run":
        llm_settings = LLMSettings(
            provider="dry-run",
            model="dry-run-model",
            api_base="",
            api_key="",
            temperature=0.0,
            max_tokens=1000,
            reasoning_effort="",
        )
        provider = DryRunLLMProvider()
    else:
        llm_settings = build_llm_settings(args, settings.llm)
        provider = create_llm_provider(llm_settings)

    if args.backend == "feishu":
        agent = create_meetflow_agent(
            settings=settings,
            llm_provider=provider,
            storage=storage,
            enable_idempotency=args.enable_idempotency,
            user_token_callback=lambda bundle: save_token_bundle(settings, bundle),
        )
    else:
        registry = build_local_registry()
        policy = AgentPolicy()
        agent = MeetFlowAgent(
            router=WorkflowRouter(),
            context_builder=WorkflowContextBuilder(storage=storage, default_project_id=args.project_id),
            loop=MeetFlowAgentLoop(
                llm_provider=provider,
                tool_registry=registry,
                policy=policy,
                storage=storage,
                max_iterations=args.max_iterations,
            ),
            storage=storage,
            policy=policy,
            enable_idempotency=args.enable_idempotency,
        )

    generation = GenerationSettings(
        model=llm_settings.model,
        temperature=llm_settings.temperature,
        max_tokens=llm_settings.max_tokens,
        reasoning_effort=llm_settings.reasoning_effort,
        timeout_seconds=90,
    )
    return agent, generation


def build_local_registry() -> ToolRegistry:
    """构造不会访问飞书的本地工具注册器。"""

    registry = ToolRegistry()
    registry.register(
        AgentTool(
            internal_name="calendar.list_events",
            description="本地模拟日历查询。",
            parameters={
                "type": "object",
                "properties": {
                    "calendar_id": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                },
                "required": ["calendar_id", "start_time", "end_time"],
            },
            handler=lambda **arguments: {
                "items": [
                    {
                        "summary": "MeetFlow Demo 周会",
                        "start_time": arguments.get("start_time"),
                        "end_time": arguments.get("end_time"),
                        "attendees": [{"display_name": "李健文"}],
                    }
                ],
                "count": 1,
            },
            read_only=True,
        )
    )
    registry.register(
        AgentTool(
            internal_name="contact.get_current_user",
            description="本地模拟获取当前用户。",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda **_: {"open_id": "ou_demo_current_user", "name": "李健文"},
            read_only=True,
        )
    )
    registry.register(
        AgentTool(
            internal_name="contact.search_user",
            description="本地模拟搜索用户。",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=lambda query, **_: {"items": [{"open_id": "ou_demo_user", "name": query}], "count": 1},
            read_only=True,
        )
    )
    registry.register(
        AgentTool(
            internal_name="tasks.list_my_tasks",
            description="本地模拟任务列表。",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda **_: {"items": [{"title": "准备演示材料", "status": "todo"}], "count": 1},
            read_only=True,
        )
    )
    registry.register(
        AgentTool(
            internal_name="tasks.create_task",
            description="本地模拟创建任务。",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "assignee_ids": {"type": "array", "items": {"type": "string"}},
                    "due_timestamp_ms": {"type": "string"},
                    "confidence": {"type": "number"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["summary"],
            },
            handler=lambda **arguments: {"created": True, "arguments": arguments},
            read_only=False,
            side_effect="create_task",
        )
    )
    registry.register(
        AgentTool(
            internal_name="im.send_card",
            description="本地模拟发送卡片。",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["title", "summary"],
            },
            handler=lambda **arguments: {"sent": True, "arguments": arguments},
            read_only=False,
            side_effect="send_message",
        )
    )
    registry.register(
        AgentTool(
            internal_name="docs.fetch_resource",
            description="本地模拟读取文档。",
            parameters={"type": "object", "properties": {"document": {"type": "string"}}, "required": ["document"]},
            handler=lambda document, **_: {"title": "Demo 文档", "content": f"文档 {document} 的模拟内容"},
            read_only=True,
        )
    )
    registry.register(
        AgentTool(
            internal_name="minutes.fetch_resource",
            description="本地模拟读取妙记。",
            parameters={"type": "object", "properties": {"minute": {"type": "string"}}, "required": ["minute"]},
            handler=lambda minute, **_: {"title": "Demo 妙记", "content": f"妙记 {minute} 的模拟内容"},
            read_only=True,
        )
    )
    settings = load_settings()
    knowledge_store = KnowledgeIndexStore(settings.storage, embedding_settings=settings.embedding)
    knowledge_store.initialize()
    register_knowledge_tools(registry, knowledge_store)
    return registry


class ScriptedDebugProvider(LLMProvider):
    """脚本化调试 Provider，根据可用工具稳定产生调用链。"""

    def chat(
        self,
        messages: list[AgentMessage],
        tools: list[Any] | None = None,
        settings: GenerationSettings | None = None,
    ) -> LLMResponse:
        """读取上下文后选择一个适合的工具调用。"""

        tool_messages = [message for message in messages if message.role == "tool"]
        if tool_messages and tool_messages[-1].metadata.get("tool_name") == "contact.get_current_user":
            return LLMResponse(
                finish_reason="tool_calls",
                model="scripted-debug",
                tool_calls=[
                    AgentToolCall(
                        call_id="debug_create_task",
                        tool_name="tasks_create_task",
                        arguments={
                            "summary": "整理会议纪要",
                            "assignee_ids": ["ou_demo_current_user"],
                            "due_timestamp_ms": str((int(time.time()) + 7200) * 1000),
                            "confidence": 0.95,
                        },
                    )
                ],
            )

        if tool_messages:
            return LLMResponse(
                content=f"scripted_debug 最终回复：{tool_messages[-1].content}",
                finish_reason="stop",
                model="scripted-debug",
            )

        user_content = next((message.content for message in messages if message.role == "user"), "")
        context_payload = extract_context_payload(user_content)
        available_tools = {tool.name for tool in tools or []}

        if "tasks_create_task" in available_tools and "contact_get_current_user" in available_tools:
            return LLMResponse(
                finish_reason="tool_calls",
                model="scripted-debug",
                tool_calls=[
                    AgentToolCall(
                        call_id="debug_current_user",
                        tool_name="contact_get_current_user",
                        arguments={},
                    )
                ],
            )

        if "knowledge_search" in available_tools:
            return LLMResponse(
                finish_reason="tool_calls",
                model="scripted-debug",
                tool_calls=[
                    AgentToolCall(
                        call_id="debug_knowledge_search",
                        tool_name="knowledge_search",
                        arguments={
                            "query": context_payload.get("query", "MeetFlow M3 会前知识卡片"),
                            "meeting_id": context_payload.get("meeting_id", ""),
                            "project_id": context_payload.get("project_id", "meetflow"),
                            "resource_types": ["doc", "minute", "task"],
                            "time_window": "recent_90_days",
                            "top_k": 3,
                        },
                    )
                ],
            )

        if "calendar_list_events" in available_tools:
            return LLMResponse(
                finish_reason="tool_calls",
                model="scripted-debug",
                tool_calls=[
                    AgentToolCall(
                        call_id="debug_calendar",
                        tool_name="calendar_list_events",
                        arguments={
                            "calendar_id": context_payload.get("calendar_id", "primary"),
                            "start_time": context_payload.get("start_time", ""),
                            "end_time": context_payload.get("end_time", ""),
                        },
                    )
                ],
            )

        return LLMResponse(content="scripted_debug 没有找到可调用工具。", finish_reason="stop", model="scripted-debug")


def extract_context_payload(user_content: str) -> dict[str, str]:
    """从 user message 中粗略提取调试参数。"""

    payload: dict[str, str] = {}
    for key in ("calendar_id", "start_time", "end_time", "project_id", "meeting_id", "query"):
        marker = f"- {key}:"
        for line in user_content.splitlines():
            if line.strip().startswith(marker):
                payload[key] = line.split(":", 1)[1].strip()
    return payload


def print_section(title: str, data: dict[str, object]) -> None:
    """打印调试区块。"""

    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def print_loop_summary(result: dict[str, object], show_full: bool) -> None:
    """打印 Agent Loop 调试结果。"""

    print_section("AgentRunResult" if show_full else "AgentRunSummary", result if show_full else summarize_result(result))


def summarize_result(result: dict[str, object]) -> dict[str, object]:
    """生成更适合终端阅读的结果摘要。"""

    loop_state = result.get("loop_state") if isinstance(result.get("loop_state"), dict) else {}
    return {
        "trace_id": result.get("trace_id"),
        "workflow_type": result.get("workflow_type"),
        "status": result.get("status"),
        "summary": result.get("summary"),
        "final_answer": result.get("final_answer"),
        "side_effects": result.get("side_effects"),
        "iterations": loop_state.get("iteration") if isinstance(loop_state, dict) else None,
        "tool_results": loop_state.get("tool_results", []) if isinstance(loop_state, dict) else [],
    }


if __name__ == "__main__":
    raise SystemExit(main())
