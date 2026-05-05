from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.feishu_callback_dispatcher import FeishuCallbackDispatcher
from adapters.feishu_callback_payloads import build_callback_envelope, normalize_sdk_card_action_payload


class FeishuCallbackDispatcherTest(unittest.TestCase):
    """覆盖 HTTP fallback 与 SDK 长连接共用的回调分发层。"""

    def build_dispatcher(self) -> FeishuCallbackDispatcher:
        settings = SimpleNamespace(
            feishu=SimpleNamespace(
                event_verification_token="test-token",
                event_encrypt_key="",
            )
        )
        return FeishuCallbackDispatcher(
            settings=settings,  # type: ignore[arg-type]
            storage=SimpleNamespace(),  # type: ignore[arg-type]
            feishu_client=SimpleNamespace(),  # type: ignore[arg-type]
        )

    def test_http_challenge_response(self) -> None:
        dispatcher = self.build_dispatcher()
        result = dispatcher.dispatch_http_callback(
            {
                "type": "url_verification",
                "token": "test-token",
                "challenge": "challenge-demo",
            }
        )
        self.assertEqual(result.status, "challenge")
        self.assertEqual(result.body, {"challenge": "challenge-demo"})

    def test_http_pre_meeting_action_generates_agent_input(self) -> None:
        dispatcher = self.build_dispatcher()
        payload = {
            "header": {"event_type": "card.action.trigger", "event_id": "evt_m3", "token": "test-token"},
            "event": {
                "action": {
                    "value": {
                        "action": "refresh_pre_meeting_brief",
                        "workflow_type": "pre_meeting_brief",
                        "source_card": "pre_meeting",
                        "calendar_event_id": "calendar_test_001",
                        "meeting_id": "meeting_test_001",
                    }
                },
                "context": {"open_chat_id": "oc_test", "open_message_id": "om_test"},
            },
        }
        result = dispatcher.dispatch_http_callback(payload)
        self.assertIn(result.status, {"success", "skipped", "accepted"})
        self.assertIsNotNone(result.agent_input)
        self.assertEqual(result.agent_input.event_type, "card.refresh_pre_meeting")

    def test_sdk_post_meeting_confirm_routes_to_m4_handler(self) -> None:
        dispatcher = self.build_dispatcher()
        payload = {
            "event": {
                "operator": {
                    "value": {
                        "action": "confirm_create_task",
                        "item_id": "action_test_001",
                    }
                }
            }
        }
        with patch("core.feishu_callback_dispatcher.handle_post_meeting_card_callback") as mocked:
            mocked.return_value = SimpleNamespace(
                status="success",
                to_feishu_response=lambda: {"toast": {"type": "success", "content": "ok"}},
            )
            result = dispatcher.dispatch_sdk_card_action(payload)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.body["toast"]["type"], "success")
        mocked.assert_called_once()

    def test_sdk_payload_normalizes_operator_value(self) -> None:
        payload = {
            "event": {
                "operator": {
                    "value": {
                        "action": "edit_task_fields",
                        "item_id": "action_test_001",
                    }
                }
            }
        }
        normalized = normalize_sdk_card_action_payload(payload)
        envelope = build_callback_envelope(normalized, source="sdk_ws")
        self.assertEqual(envelope.action, "edit_task_fields")
        self.assertEqual(envelope.action_value["item_id"], "action_test_001")

    def test_unknown_action_returns_toast(self) -> None:
        dispatcher = self.build_dispatcher()
        result = dispatcher.dispatch_sdk_card_action(
            {
                "event": {
                    "action": {
                        "value": {
                            "action": "unknown_action",
                        }
                    }
                }
            }
        )
        self.assertEqual(result.status, "ignored")
        self.assertEqual(result.body["toast"]["type"], "info")


if __name__ == "__main__":
    unittest.main()
