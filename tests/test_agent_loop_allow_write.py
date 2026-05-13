from __future__ import annotations

import unittest

from core.agent_loop import MeetFlowAgentLoop, build_runtime_context_message
from core.llm import GenerationSettings, LLMProvider, LLMResponse
from core.models import AgentMessage, AgentToolCall, Event, WorkflowContext
from core.policy import AgentPolicy
from core.tools import AgentTool, ToolRegistry


class SequentialToolThenAnswerProvider(LLMProvider):
    """首轮请求工具、次轮返回最终答案的测试模型。"""

    def chat(
        self,
        messages: list[AgentMessage],
        tools=None,
        settings: GenerationSettings | None = None,
    ) -> LLMResponse:
        if any(message.role == "tool" for message in messages):
            return LLMResponse(
                content="done",
                finish_reason="stop",
                model=(settings.model if settings else "test-model"),
            )
        return LLMResponse(
            tool_calls=[
                AgentToolCall(
                    call_id="call_demo",
                    tool_name="im.send_card",
                    arguments={
                        "title": "demo",
                        "summary": "demo",
                        "idempotency_key": "write_demo_001",
                    },
                )
            ],
            finish_reason="tool_calls",
            model=(settings.model if settings else "test-model"),
        )


class MeetFlowAgentLoopAllowWriteTest(unittest.TestCase):
    """验证 allow_write 以单次运行参数传递，不在 loop 实例间串线。"""

    def setUp(self) -> None:
        self.executed_titles: list[str] = []
        registry = ToolRegistry()
        registry.register(
            AgentTool(
                internal_name="im.send_card",
                description="发送测试卡片。",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "idempotency_key": {"type": "string"},
                    },
                    "required": ["title", "summary", "idempotency_key"],
                },
                handler=self._send_card,
                read_only=False,
                side_effect="send_message",
            )
        )
        self.loop = MeetFlowAgentLoop(
            llm_provider=SequentialToolThenAnswerProvider(),
            tool_registry=registry,
            policy=AgentPolicy(),
        )
        self.context = WorkflowContext(
            workflow_type="pre_meeting_brief",
            trace_id="trace_demo",
            event=Event(
                event_id="evt_demo",
                event_type="card.refresh_pre_meeting",
                event_time="1700000000",
                source="feishu_card",
                actor="ou_demo",
                payload={},
                trace_id="trace_demo",
            ),
        )
        self.settings = GenerationSettings(model="test-model")

    def _send_card(self, title: str, summary: str, idempotency_key: str) -> dict[str, str]:
        self.executed_titles.append(title)
        return {
            "title": title,
            "summary": summary,
            "idempotency_key": idempotency_key,
        }

    def test_allow_write_is_scoped_per_run(self) -> None:
        first_result = self.loop.run(
            context=self.context,
            required_tools=["im.send_card"],
            generation_settings=self.settings,
            allow_write=False,
        )
        second_result = self.loop.run(
            context=self.context,
            required_tools=["im.send_card"],
            generation_settings=self.settings,
            allow_write=True,
        )

        self.assertEqual(first_result.status, "success")
        self.assertEqual(second_result.status, "success")
        self.assertEqual(first_result.loop_state.tool_results[0].status, "blocked")
        self.assertEqual(second_result.loop_state.tool_results[0].status, "success")
        self.assertEqual(self.executed_titles, ["demo"])
        self.assertIn("agent_trace", second_result.payload)
        self.assertIn("intelligence_signals", second_result.payload)
        self.assertEqual(second_result.payload["agent_trace"]["tool_calls"][0]["tool_name"], "im.send_card")
        self.assertEqual(second_result.payload["agent_trace"]["policy_decisions"][0]["status"], "allow")
        self.assertEqual(second_result.payload["intelligence_signals"]["called_tools"], ["im.send_card"])

    def test_runtime_context_includes_pre_meeting_card_payload_for_d2_auto_send(self) -> None:
        self.context.raw_context["pre_meeting_card_payload"] = {
            "title": "MeetFlow 测试会议 会前背景知识卡",
            "summary": "新版 D2 卡片摘要",
            "facts": [{"label": "核心背景知识", "value": "- 示例"}],
            "card": {"elements": [{"tag": "markdown", "content": "核心背景知识"}]},
        }

        message = build_runtime_context_message(self.context, "发送 D2 会前卡")

        self.assertIn("pre_meeting_card_payload", message)
        self.assertIn("MeetFlow 测试会议 会前背景知识卡", message)
        self.assertIn("核心背景知识", message)


if __name__ == "__main__":
    unittest.main()
