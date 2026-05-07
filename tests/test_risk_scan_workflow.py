from __future__ import annotations

import unittest

from core.models import AgentDecision, AgentLoopState, AgentRunResult, AgentToolResult, Event, WorkflowContext
from core.observability import EventWriterSettings, configure_structured_events
from core.workflows import RiskScanWorkflow, WorkflowSpec


class RiskScanWorkflowTest(unittest.TestCase):
    """验证 RiskScanWorkflow 能从任务工具结果生成确定性风险产物。"""

    def setUp(self) -> None:
        """测试中关闭结构化事件落盘。"""

        configure_structured_events(EventWriterSettings(structured_events_enabled=False))

    def test_post_process_generates_risk_payload(self) -> None:
        now = 1_700_000_000
        workflow = RiskScanWorkflow(spec=WorkflowSpec(workflow_type="risk_scan"))
        context = WorkflowContext(
            workflow_type="risk_scan",
            trace_id="trace_demo",
            event=Event(
                event_id="evt_demo",
                event_type="risk.scan.tick",
                event_time=str(now),
                source="test",
                actor="",
                payload={},
                trace_id="trace_demo",
            ),
            raw_context={
                "payload": {
                    "risk_rules": {
                        "stale_update_days": 3,
                        "due_soon_hours": 24,
                        "max_reminders_per_day": 5,
                    }
                }
            },
        )
        result = AgentRunResult(
            trace_id="trace_demo",
            workflow_type="risk_scan",
            status="success",
            final_answer="已读取任务。",
            loop_state=AgentLoopState(
                loop_id="loop_demo",
                trace_id="trace_demo",
                workflow_type="risk_scan",
                tool_results=[
                    AgentToolResult(
                        call_id="call_tasks",
                        tool_name="tasks.list_my_tasks",
                        status="success",
                        data={
                            "items": [
                                {
                                    "item_id": "task_overdue",
                                    "title": "逾期任务",
                                    "owner": "张三",
                                    "due_date": str(now - 3600),
                                    "status": "todo",
                                    "extra": {"task_id": "task_overdue", "updated_at": str(now - 3600)},
                                }
                            ],
                            "count": 1,
                        },
                    )
                ],
            ),
        )

        workflow.post_process_result(
            result=result,
            context=context,
            decision=AgentDecision(
                workflow_type="risk_scan",
                confidence=1.0,
                reason="测试",
                required_tools=["tasks.list_my_tasks"],
                status="ready",
            ),
        )

        self.assertIn("risk_scan", result.payload)
        self.assertEqual(result.payload["risk_scan"]["scan_result"]["risk_count"], 1)
        self.assertTrue(result.payload["risk_scan"]["notification_decision"]["should_notify"])
        self.assertIn("card_payload", result.payload["risk_scan"])

    def test_validate_warns_without_tool_result(self) -> None:
        workflow = RiskScanWorkflow(spec=WorkflowSpec(workflow_type="risk_scan"))
        result = AgentRunResult(
            trace_id="trace_demo",
            workflow_type="risk_scan",
            status="success",
            final_answer="没有工具结果。",
            loop_state=AgentLoopState(loop_id="loop_demo", trace_id="trace_demo", workflow_type="risk_scan"),
        )

        validation = workflow.validate_output(result)

        self.assertTrue(validation.ok)
        self.assertTrue(validation.warnings)


if __name__ == "__main__":
    unittest.main()
