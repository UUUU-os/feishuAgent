from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/agent_policy_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import (
    AgentMessage,
    AgentPolicy,
    AgentTool,
    AgentToolCall,
    Event,
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    MeetFlowAgentLoop,
    ToolRegistry,
    WorkflowContext,
    configure_logging,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="演示 T2.15 AgentPolicy 自动化边界。")
    parser.add_argument(
        "--scenario",
        choices=["missing_task_fields", "valid_task", "write_disabled"],
        default="missing_task_fields",
        help="选择要演示的策略场景。",
    )
    return parser.parse_args()


def main() -> int:
    """运行 AgentPolicy demo。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)

    registry = build_demo_registry()
    provider = ScriptedWriteProvider(scenario=args.scenario)
    loop = MeetFlowAgentLoop(
        llm_provider=provider,
        tool_registry=registry,
        policy=AgentPolicy(),
        allow_write=args.scenario != "write_disabled",
        max_iterations=2,
    )
    result = loop.run(
        context=build_demo_context(),
        required_tools=["tasks.create_task", "im.send_card"],
        workflow_goal="验证写工具必须先经过 AgentPolicy。",
        generation_settings=GenerationSettings(model="scripted-policy"),
    )

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def build_demo_registry() -> ToolRegistry:
    """构造包含写工具的本地工具注册器。"""

    registry = ToolRegistry()
    registry.register(
        AgentTool(
            internal_name="tasks.create_task",
            llm_name="tasks_create_task",
            description="创建任务的本地演示工具。",
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
            llm_name="im_send_card",
            description="发送卡片的本地演示工具。",
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
    return registry


def build_demo_context() -> WorkflowContext:
    """构造带幂等键的工作流上下文。"""

    return WorkflowContext(
        workflow_type="post_meeting_followup",
        trace_id="policy_demo",
        event=Event(
            event_id="policy_demo_event",
            event_type="minute.ready",
            event_time=str(int(time.time())),
            source="agent_policy_demo",
            actor="",
            payload={},
            trace_id="policy_demo",
        ),
        project_id="meetflow",
        raw_context={
            "decision": {
                "workflow_type": "post_meeting_followup",
                "idempotency_key": "post_meeting_followup:policy_demo",
            }
        },
    )


class ScriptedWriteProvider(LLMProvider):
    """脚本化 LLM，用来稳定触发不同写工具策略场景。"""

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario

    def chat(
        self,
        messages: list[AgentMessage],
        tools: list[Any] | None = None,
        settings: GenerationSettings | None = None,
    ) -> LLMResponse:
        """第一轮请求工具，第二轮根据 tool message 输出最终回复。"""

        for message in reversed(messages):
            if message.role == "tool":
                return LLMResponse(
                    content=f"策略演示结束：{message.content}",
                    finish_reason="stop",
                    model="scripted-policy",
                )

        if self.scenario == "valid_task":
            return LLMResponse(
                finish_reason="tool_calls",
                model="scripted-policy",
                tool_calls=[
                    AgentToolCall(
                        call_id="policy_valid_task",
                        tool_name="tasks_create_task",
                        arguments={
                            "summary": "完成 T2.15 策略层",
                            "assignee_ids": ["ou_demo"],
                            "due_timestamp_ms": "1777296000000",
                            "confidence": 0.95,
                        },
                    )
                ],
            )

        if self.scenario == "write_disabled":
            return LLMResponse(
                finish_reason="tool_calls",
                model="scripted-policy",
                tool_calls=[
                    AgentToolCall(
                        call_id="policy_write_disabled",
                        tool_name="im_send_card",
                        arguments={"title": "风险提醒", "summary": "这是一次写工具拦截演示。"},
                    )
                ],
            )

        return LLMResponse(
            finish_reason="tool_calls",
            model="scripted-policy",
            tool_calls=[
                AgentToolCall(
                    call_id="policy_missing_task_fields",
                    tool_name="tasks_create_task",
                    arguments={
                        "summary": "缺少负责人和截止时间的行动项",
                        "confidence": 0.9,
                    },
                )
            ],
        )


if __name__ == "__main__":
    raise SystemExit(main())
