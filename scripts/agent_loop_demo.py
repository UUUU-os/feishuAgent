from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/agent_loop_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import (
    AgentTool,
    DryRunLLMProvider,
    MeetFlowAgentLoop,
    ToolRegistry,
    WorkflowContextBuilder,
    WorkflowRouter,
    build_agent_input,
    configure_logging,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="演示 T2.13 MeetFlowAgentLoop：dry-run LLM + 本地工具完整循环。",
    )
    parser.add_argument("--event-type", default="meeting.soon", help="事件类型。")
    parser.add_argument("--meeting-id", default="meeting_loop_demo", help="会议 ID。")
    parser.add_argument("--max-iterations", type=int, default=4, help="最大 loop 轮数。")
    return parser.parse_args()


def main() -> int:
    """运行 Agent Loop demo。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)

    agent_input = build_agent_input(
        event_type=args.event_type,
        payload={
            "meeting_id": args.meeting_id,
            "project_id": "meetflow",
            "participants": [{"name": "李健文", "role": "owner"}],
        },
        source="agent_loop_demo",
    )
    decision = WorkflowRouter().route(agent_input)
    context = WorkflowContextBuilder(default_project_id="meetflow").build(
        agent_input=agent_input,
        decision=decision,
    )

    registry = _build_demo_registry()
    loop = MeetFlowAgentLoop(
        llm_provider=DryRunLLMProvider(),
        tool_registry=registry,
        max_iterations=args.max_iterations,
    )
    result = loop.run(
        context=context,
        required_tools=["demo.fetch_context"],
        workflow_goal="读取上下文摘要，并生成一条最终回复。",
    )

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _build_demo_registry() -> ToolRegistry:
    """构造一个只包含本地只读工具的注册器。"""

    registry = ToolRegistry()
    registry.register(
        AgentTool(
            internal_name="demo.fetch_context",
            llm_name="demo_fetch_context",
            description="读取一段本地上下文摘要，用于验证 Agent Loop 工具调用链路。",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=lambda **_: {
                "title": "Agent Loop Demo Context",
                "content": "本地 demo 工具执行成功，Agent Loop 已经完成工具调用。",
            },
            read_only=True,
        )
    )
    return registry


if __name__ == "__main__":
    raise SystemExit(main())
