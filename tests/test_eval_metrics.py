from __future__ import annotations

import unittest

from core.eval_metrics import (
    evaluate_agent_trace,
    score_allow_write_gate,
    score_policy_compliance,
    score_tool_call_f1,
    score_tool_order,
)
from core.eval_trace import AgentTrace, PolicyDecisionTrace, ToolCallTrace


class EvalMetricsTest(unittest.TestCase):
    """验证 Agent 轨迹核心评测指标。"""

    def test_tool_call_f1(self) -> None:
        score = score_tool_call_f1(
            actual=["calendar.list_events", "knowledge.search"],
            expected=["calendar.list_events", "knowledge.search", "im.send_card"],
        )

        self.assertAlmostEqual(score, 0.8)

    def test_tool_order_score(self) -> None:
        score = score_tool_order(
            actual=["minutes.fetch_resource", "contact.search_user", "tasks.create_task"],
            constraints=[
                {"before": "minutes.fetch_resource", "after": "tasks.create_task"},
                {"before": "contact.search_user", "after": "tasks.create_task"},
            ],
        )

        self.assertEqual(score, 1.0)

    def test_policy_scores(self) -> None:
        trace = build_trace()

        self.assertEqual(score_policy_compliance(trace), 1.0)
        self.assertEqual(score_allow_write_gate(trace), 1.0)

    def test_evaluate_agent_trace(self) -> None:
        result = evaluate_agent_trace(
            case_id="demo",
            trace=build_trace(),
            expected={
                "must_call_tools": ["minutes.fetch_resource", "tasks.create_task"],
                "tool_order_constraints": [
                    {"before": "minutes.fetch_resource", "after": "tasks.create_task"}
                ],
                "min_tool_call_f1": 1.0,
            },
        )

        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.score, 0.9)


def build_trace() -> AgentTrace:
    """构造一条最小 Agent trace。"""

    return AgentTrace(
        trace_id="trace_demo",
        workflow_type="post_meeting_followup",
        tool_calls=[
            ToolCallTrace(
                call_id="call_minutes",
                tool_name="minutes.fetch_resource",
                status="success",
            ),
            ToolCallTrace(
                call_id="call_task",
                tool_name="tasks.create_task",
                status="needs_confirmation",
            ),
        ],
        policy_decisions=[
            PolicyDecisionTrace(
                tool_name="tasks.create_task",
                side_effect="create_task",
                status="needs_confirmation",
                idempotency_key_present=True,
                allow_write=True,
            )
        ],
        status="success",
    )


if __name__ == "__main__":
    unittest.main()
