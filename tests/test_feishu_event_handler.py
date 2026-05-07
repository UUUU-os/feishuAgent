from __future__ import annotations

import unittest

from adapters.feishu_event_handler import FeishuEventHandler, FeishuEventHandlerError
from core.card_actions import CardActionResult
from core.observability import EventWriterSettings, configure_structured_events


class FeishuEventHandlerTest(unittest.TestCase):
    """验证飞书回调 payload 解析和响应构造。"""

    def setUp(self) -> None:
        """测试中关闭结构化事件落盘，避免污染本地运行日志。"""

        configure_structured_events(EventWriterSettings(structured_events_enabled=False))

    def test_url_verification_returns_challenge(self) -> None:
        handler = FeishuEventHandler(verification_token="token_demo")

        response = handler.handle_verification(
            {
                "type": "url_verification",
                "token": "token_demo",
                "challenge": "challenge_demo",
            }
        )

        self.assertEqual(response, {"challenge": "challenge_demo"})

    def test_token_mismatch_raises(self) -> None:
        handler = FeishuEventHandler(verification_token="token_demo")

        with self.assertRaises(FeishuEventHandlerError):
            handler.parse_card_action(
                {
                    "header": {"event_type": "card.action.trigger", "token": "bad_token"},
                    "event": {"action": {"value": {"action": "refresh_pre_meeting_brief"}}},
                }
            )

    def test_parse_card_action_payload(self) -> None:
        handler = FeishuEventHandler()

        action_input = handler.parse_card_action(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt_demo",
                    "event_type": "card.action.trigger",
                },
                "event": {
                    "operator": {"open_id": "ou_demo"},
                    "context": {
                        "open_chat_id": "oc_demo",
                        "open_message_id": "om_demo",
                    },
                    "action": {
                        "value": {
                            "action": "refresh_pre_meeting_brief",
                            "workflow_type": "pre_meeting_brief",
                            "meeting_id": "meeting_demo",
                            "calendar_event_id": "event_demo",
                            "source_card": "pre_meeting_brief",
                        }
                    },
                },
            }
        )

        self.assertEqual(action_input.action, "refresh_pre_meeting_brief")
        self.assertEqual(action_input.event_id, "evt_demo")
        self.assertEqual(action_input.operator_open_id, "ou_demo")
        self.assertEqual(action_input.chat_id, "oc_demo")
        self.assertEqual(action_input.open_message_id, "om_demo")
        self.assertEqual(action_input.calendar_event_id, "event_demo")
        self.assertEqual(
            action_input.idempotency_key,
            "card_action:pre_meeting_brief:event_demo:refresh_pre_meeting_brief:event:evt_demo",
        )

    def test_missing_action_raises(self) -> None:
        handler = FeishuEventHandler()

        with self.assertRaises(FeishuEventHandlerError):
            handler.parse_card_action(
                {
                    "header": {"event_type": "card.action.trigger"},
                    "event": {"action": {"value": {}}},
                }
            )

    def test_build_callback_response_returns_toast(self) -> None:
        handler = FeishuEventHandler()

        response = handler.build_callback_response(
            CardActionResult(
                status="accepted",
                action="refresh_pre_meeting_brief",
                message="已收到",
                trace_id="trace_demo",
            )
        )

        self.assertEqual(response["toast"]["type"], "info")
        self.assertEqual(response["toast"]["content"], "已收到")


if __name__ == "__main__":
    unittest.main()
