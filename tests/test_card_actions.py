from __future__ import annotations

import unittest

from core.card_actions import CardActionRouter, build_card_action_input
from core.models import AgentInput
from core.observability import EventWriterSettings, configure_structured_events
from core.router import WorkflowRouter


class CardActionRouterTest(unittest.TestCase):
    """验证卡片动作路由到内部 AgentInput 的核心行为。"""

    def setUp(self) -> None:
        """测试中关闭结构化事件落盘，避免污染本地运行日志。"""

        configure_structured_events(EventWriterSettings(structured_events_enabled=False))

    def test_refresh_pre_meeting_builds_agent_input(self) -> None:
        action_input = build_card_action_input(
            action="refresh_pre_meeting_brief",
            trace_id="trace_demo",
            event_id="evt_demo",
            operator_open_id="ou_demo",
            chat_id="oc_demo",
            open_message_id="om_demo",
            workflow_type="pre_meeting_brief",
            meeting_id="meeting_demo",
            calendar_event_id="event_demo",
            source_card="pre_meeting_brief",
        )

        result = CardActionRouter().route(action_input)

        self.assertEqual(result.status, "accepted")
        self.assertIsNotNone(result.agent_input)
        assert result.agent_input is not None
        self.assertEqual(result.agent_input.event_type, "card.refresh_pre_meeting")
        self.assertEqual(result.agent_input.payload["calendar_event_id"], "event_demo")
        self.assertEqual(result.agent_input.payload["chat_id"], "oc_demo")
        self.assertIn("calendar.list_events", result.agent_input.payload["required_tools"])

    def test_unknown_action_is_blocked(self) -> None:
        action_input = build_card_action_input(action="unknown_action", trace_id="trace_demo")

        result = CardActionRouter().route(action_input)

        self.assertEqual(result.status, "blocked")
        self.assertIn("暂不支持", result.message)

    def test_missing_action_is_blocked(self) -> None:
        action_input = build_card_action_input(action="", trace_id="trace_demo")

        result = CardActionRouter().route(action_input)

        self.assertEqual(result.status, "blocked")
        self.assertIn("缺少 action", result.message)

    def test_create_task_draft_requires_confirmation(self) -> None:
        action_input = build_card_action_input(action="create_task_draft", trace_id="trace_demo")

        result = CardActionRouter().route(action_input)

        self.assertEqual(result.status, "needs_confirmation")

    def test_send_summary_to_me_requires_confirmation(self) -> None:
        action_input = build_card_action_input(
            action="send_summary_to_me",
            trace_id="trace_demo",
            operator_open_id="ou_demo",
        )

        result = CardActionRouter().route(action_input)

        self.assertEqual(result.status, "needs_confirmation")
        self.assertEqual(result.metadata["operator_open_id"], "ou_demo")

    def test_refresh_pre_meeting_idempotency_fallback(self) -> None:
        action_input = build_card_action_input(
            action="refresh_pre_meeting_brief",
            trace_id="trace_demo",
            source_card="pre_meeting_brief",
            calendar_event_id="event_demo",
            created_at=1700000000,
        )

        result = CardActionRouter().route(action_input)

        self.assertIsNotNone(result.agent_input)
        assert result.agent_input is not None
        self.assertEqual(
            result.agent_input.payload["idempotency_key"],
            "card_action:pre_meeting_brief:event_demo:refresh_pre_meeting_brief:bucket:56666666",
        )

    def test_refresh_pre_meeting_uses_callback_event_id_for_idempotency(self) -> None:
        action_input = build_card_action_input(
            action="refresh_pre_meeting_brief",
            trace_id="trace_demo",
            event_id="evt_demo",
            source_card="pre_meeting_brief",
            calendar_event_id="event_demo",
        )

        result = CardActionRouter().route(action_input)

        self.assertIsNotNone(result.agent_input)
        assert result.agent_input is not None
        self.assertEqual(
            result.agent_input.payload["idempotency_key"],
            "card_action:pre_meeting_brief:event_demo:refresh_pre_meeting_brief:event:evt_demo",
        )

    def test_refresh_pre_meeting_ignores_legacy_fixed_button_idempotency_key(self) -> None:
        action_input = build_card_action_input(
            action="refresh_pre_meeting_brief",
            trace_id="trace_demo",
            event_id="evt_demo",
            source_card="pre_meeting_brief",
            calendar_event_id="event_demo",
            value={
                "idempotency_key": "card:pre_meeting_brief:event_demo:refresh_pre_meeting_brief",
            },
        )

        self.assertEqual(
            action_input.idempotency_key,
            "card_action:pre_meeting_brief:event_demo:refresh_pre_meeting_brief:event:evt_demo",
        )

    def test_workflow_router_supports_card_refresh_event(self) -> None:
        decision = WorkflowRouter().route(
            AgentInput(
                trigger_type="card_action",
                event_type="card.refresh_pre_meeting",
                payload={"calendar_event_id": "event_demo"},
                source="feishu_card",
            )
        )

        self.assertEqual(decision.status, "ready")
        self.assertEqual(decision.workflow_type, "pre_meeting_brief")
        self.assertIn("im.send_card", decision.required_tools)

    def test_post_meeting_confirm_action_builds_review_agent_input(self) -> None:
        action_input = build_card_action_input(
            action="confirm_create_task",
            trace_id="trace_m4",
            event_id="evt_m4",
            operator_open_id="ou_user",
            chat_id="oc_group",
            value={
                "item_id": "action_001",
                "review_session_id": "review_001",
                "meeting_id": "meeting_001",
                "minute_token": "minute_001",
            },
        )

        result = CardActionRouter().route(action_input)

        self.assertEqual(result.status, "accepted")
        self.assertIsNotNone(result.agent_input)
        assert result.agent_input is not None
        self.assertEqual(result.agent_input.event_type, "card.post_meeting_task_review")
        self.assertEqual(result.agent_input.payload["item_id"], "action_001")
        self.assertEqual(result.agent_input.payload["review_session_id"], "review_001")
        decision = WorkflowRouter().route(result.agent_input)
        self.assertEqual(decision.workflow_type, "post_meeting_followup")

    def test_start_risk_scan_builds_risk_agent_input(self) -> None:
        action_input = build_card_action_input(
            action="start_risk_scan",
            trace_id="trace_d3_risk",
            event_id="evt_d3_risk",
            operator_open_id="ou_user",
            chat_id="oc_group",
            source_card="post_meeting_summary",
            meeting_id="meeting_001",
            value={"minute_token": "minute_001"},
        )

        result = CardActionRouter().route(action_input)

        self.assertEqual(result.status, "accepted")
        self.assertIsNotNone(result.agent_input)
        assert result.agent_input is not None
        self.assertEqual(result.agent_input.event_type, "card.start_risk_scan")
        self.assertEqual(result.agent_input.payload["workflow_type"], "risk_scan")
        self.assertEqual(result.agent_input.payload["minute_token"], "minute_001")
        decision = WorkflowRouter().route(result.agent_input)
        self.assertEqual(decision.status, "ready")
        self.assertEqual(decision.workflow_type, "risk_scan")
        self.assertIn("tasks.list_my_tasks", decision.required_tools)

    def test_view_post_meeting_report_returns_controlled_message(self) -> None:
        action_input = build_card_action_input(
            action="view_post_meeting_report",
            trace_id="trace_report",
            value={"report_url": "https://example.com/report"},
        )

        result = CardActionRouter().route(action_input)

        self.assertEqual(result.status, "accepted")
        self.assertIsNone(result.agent_input)
        self.assertIn("https://example.com/report", result.message)


if __name__ == "__main__":
    unittest.main()
