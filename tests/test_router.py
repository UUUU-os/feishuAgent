from __future__ import annotations

import unittest

from core.models import AgentInput
from core.router import WorkflowRouter


class WorkflowRouterTest(unittest.TestCase):
    """验证路由层暴露给不同工作流的工具边界。"""

    def test_minute_ready_route_includes_contact_resolution_tools(self) -> None:
        decision = WorkflowRouter().route(
            AgentInput(
                trigger_type="event",
                event_type="minute.ready",
                payload={"minute_token": "minute_demo"},
                source="feishu",
            )
        )

        self.assertEqual(decision.workflow_type, "post_meeting_followup")
        self.assertIn("contact.get_current_user", decision.required_tools)
        self.assertIn("contact.search_user", decision.required_tools)

    def test_manual_post_meeting_route_includes_contact_resolution_tools(self) -> None:
        decision = WorkflowRouter().route(
            AgentInput(
                trigger_type="manual",
                event_type="message.command",
                payload={"workflow_type": "post_meeting_followup"},
                source="demo",
            )
        )

        self.assertEqual(decision.workflow_type, "post_meeting_followup")
        self.assertIn("contact.get_current_user", decision.required_tools)
        self.assertIn("contact.search_user", decision.required_tools)


if __name__ == "__main__":
    unittest.main()
