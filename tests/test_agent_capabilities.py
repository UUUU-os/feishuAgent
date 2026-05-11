from __future__ import annotations

import unittest

from core.agent_capabilities import build_agent_capability_report
from core.tools import AgentTool, ToolRegistry


class AgentCapabilityReportTest(unittest.TestCase):
    """验证 D6 Agent 能力报告能讲清 Context、Tool、Policy、Trace。"""

    def test_report_contains_workflow_tool_policy_and_trace(self) -> None:
        report = build_agent_capability_report()
        data = report.to_dict()
        workflow_types = {item["workflow_type"] for item in data["workflows"]}
        tool_names = {item["internal_name"] for item in data["tools"]}

        self.assertIn("pre_meeting_brief", workflow_types)
        self.assertIn("post_meeting_followup", workflow_types)
        self.assertIn("risk_scan", workflow_types)
        self.assertIn("tasks.list_my_tasks", tool_names)
        self.assertIn("im.send_card", tool_names)
        self.assertFalse(data["policy"]["allow_write_default"])
        self.assertTrue(data["policy"]["require_idempotency_for_writes"])
        self.assertIn("tool_calls", data["trace"]["trace_fields"])
        self.assertIn("policy_decisions", data["trace"]["trace_fields"])
        self.assertIn("AgentPolicy", data["flow_diagram"])

    def test_report_uses_real_tool_registry_metadata_when_provided(self) -> None:
        registry = ToolRegistry()
        registry.register(
            AgentTool(
                internal_name="tasks.create_task",
                description="创建测试任务。",
                parameters={
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "idempotency_key": {"type": "string"},
                    },
                    "required": ["summary", "idempotency_key"],
                },
                handler=lambda **_: {"ok": True},
                read_only=False,
                side_effect="create_task",
            )
        )

        report = build_agent_capability_report(tool_registry=registry)
        tool = report.to_dict()["tools"][0]

        self.assertEqual(tool["internal_name"], "tasks.create_task")
        self.assertEqual(tool["llm_name"], "tasks_create_task")
        self.assertFalse(tool["read_only"])
        self.assertEqual(tool["side_effect"], "create_task")
        self.assertEqual(tool["required_fields"], ["summary", "idempotency_key"])


if __name__ == "__main__":
    unittest.main()
