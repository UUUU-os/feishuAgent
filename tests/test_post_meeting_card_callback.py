from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cards.post_meeting import build_pending_action_item_button_card, build_pending_action_items_card
from core.card_callback import handle_post_meeting_card_callback, normalize_due_date_override
from core.confirmation_commands import bind_pending_action_message, load_pending_action_records, mark_pending_action_status, save_pending_action_values
from core.models import ActionItem, AgentToolResult, EvidenceRef
from core.policy import AgentPolicy
from core.post_meeting import parse_due_date_to_timestamp_ms
from core.storage import MeetFlowStorage


class FakeFeishuClient:
    """模拟消息卡片更新接口。"""

    def __init__(self) -> None:
        self.updated_cards: list[dict[str, object]] = []

    def update_card_message(self, message_id: str, card: dict[str, object], identity: str | None = None) -> dict[str, object]:
        self.updated_cards.append({"message_id": message_id, "card": card, "identity": identity})
        return {"message_id": message_id}


class FakeTool:
    """最小工具对象，满足 ToolRegistry / AgentPolicy 联调。"""

    def __init__(self, internal_name: str, llm_name: str, read_only: bool = True, side_effect: str = "none") -> None:
        self.internal_name = internal_name
        self.llm_name = llm_name
        self.read_only = read_only
        self.side_effect = side_effect


class FakeRegistry:
    """模拟卡片回调中会用到的通讯录和任务工具。"""

    def __init__(self) -> None:
        self._tools = {
            "tasks.create_task": FakeTool("tasks.create_task", "tasks_create_task", read_only=False, side_effect="create_task"),
            "contact.search_user": FakeTool("contact.search_user", "contact_search_user"),
            "contact.get_current_user": FakeTool("contact.get_current_user", "contact_get_current_user"),
        }

    def get(self, tool_name: str) -> FakeTool:
        return self._tools[tool_name]

    def execute(self, tool_call):  # noqa: ANN001 - 与项目现有 ToolRegistry 接口保持一致
        if tool_call.tool_name == "contact_search_user":
            return AgentToolResult(
                call_id=tool_call.call_id,
                tool_name="contact.search_user",
                status="success",
                content="ok",
                data={"items": [{"open_id": "ou_test_assignee"}]},
            )
        if tool_call.tool_name == "contact_get_current_user":
            return AgentToolResult(
                call_id=tool_call.call_id,
                tool_name="contact.get_current_user",
                status="success",
                content="ok",
                data={"open_id": "ou_current_user"},
            )
        if tool_call.tool_name == "tasks_create_task":
            summary = str(tool_call.arguments.get("summary") or "")
            return AgentToolResult(
                call_id=tool_call.call_id,
                tool_name="tasks.create_task",
                status="success",
                content="ok",
                data={"guid": "task_test_001", "summary": summary, "status": "todo"},
            )
        raise AssertionError(f"unexpected tool call: {tool_call.tool_name}")


class PostMeetingCardCallbackTest(unittest.TestCase):
    """覆盖 M4 按钮卡的修改 / 创建 / 拒绝主路径。"""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.settings = SimpleNamespace(
            app=SimpleNamespace(timezone="Asia/Shanghai"),
            feishu=SimpleNamespace(default_chat_id="oc_test_chat"),
            storage=SimpleNamespace(
                db_path=str(root / "meetflow.sqlite"),
                project_memory_dir=str(root / "project_memory"),
                audit_log_path=str(root / "audit.jsonl"),
            ),
        )
        self.storage = MeetFlowStorage(self.settings.storage)
        self.storage.initialize()
        save_pending_action_values(
            self.settings,
            [
                {
                    "item_id": "action_test_001",
                    "title": "整理答辩材料",
                    "owner": "",
                    "due_date": "",
                    "priority": "high",
                    "confidence": 0.82,
                    "meeting_id": "meeting_test_001",
                    "calendar_event_id": "calendar_test_001",
                    "minute_token": "minute_test_001",
                    "project_id": "meetflow",
                    "evidence_refs": [
                        {
                            "source_type": "minute",
                            "source_id": "minute_test_001",
                            "source_url": "https://example.com/minute",
                            "snippet": "张三负责整理答辩材料，明天前完成。",
                        }
                    ],
                }
            ],
            source={"chat_id": "oc_test_chat", "receive_id_type": "chat_id"},
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_pending_card_contains_form_and_buttons(self) -> None:
        item = ActionItem(
            item_id="action_test_001",
            title="整理答辩材料",
            owner="",
            due_date="",
            priority="high",
            confidence=0.82,
            needs_confirm=True,
            evidence_refs=[
                EvidenceRef(
                    source_type="minute",
                    source_id="minute_test_001",
                    source_url="https://example.com/minute",
                    snippet="张三负责整理答辩材料，明天前完成。",
                )
            ],
            extra={"confirm_reason": "缺少负责人、截止时间"},
        )
        artifacts = SimpleNamespace(
            meeting_summary=SimpleNamespace(topic="M4 按钮回调联调"),
            pending_action_items=[item],
            action_items=[item],
        )
        card = build_pending_action_items_card(artifacts)
        self.assertEqual(card.get("schema"), "2.0")
        self.assertTrue(card.get("config", {}).get("update_multi"))
        body = card.get("body", {})
        elements = body.get("elements", [])
        self.assertTrue(any(element.get("tag") == "form" for element in elements))
        card_text = str(card)
        self.assertIn("确认创建", card_text)
        self.assertIn("修改信息", card_text)
        self.assertIn("拒绝创建", card_text)

    def test_single_pending_button_card_contains_inline_inputs_and_buttons(self) -> None:
        item = ActionItem(
            item_id="action_test_001",
            title="整理答辩材料",
            owner="",
            due_date="",
            priority="high",
            confidence=0.82,
            needs_confirm=True,
            evidence_refs=[
                EvidenceRef(
                    source_type="minute",
                    source_id="minute_test_001",
                    source_url="https://example.com/minute",
                    snippet="张三负责整理答辩材料，明天前完成。",
                )
            ],
            extra={"confirm_reason": "缺少负责人、截止时间"},
        )
        artifacts = SimpleNamespace(meeting_summary=SimpleNamespace(topic="M4 按钮回调联调"))
        card = build_pending_action_item_button_card(artifacts, item, mode="review")
        self.assertEqual(card.get("schema"), "2.0")
        body = card.get("body", {})
        elements = body.get("elements", [])
        self.assertEqual(elements[1].get("tag"), "form")
        card_text = str(card)
        self.assertIn("负责人，例如：张三 / 我", card_text)
        self.assertIn("截止时间，例如：明天 / 2026-05-03", card_text)
        self.assertIn("确认创建", card_text)
        self.assertIn("修改信息", card_text)
        self.assertIn("拒绝创建", card_text)

    def test_edit_button_updates_pending_registry(self) -> None:
        client = FakeFeishuClient()
        payload = {
            "event": {
                "context": {"open_message_id": "om_test_001"},
                "action": {
                    "value": {"action": "edit_task_fields", "item_id": "action_test_001"},
                    "form_value": {"owner_override": "张三", "due_date_override": "明天"},
                }
            }
        }
        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )
        self.assertEqual(result.status, "success")
        records = load_pending_action_records(self.settings)
        value = records["action_test_001"]["value"]
        self.assertEqual(value["owner"], "张三")
        self.assertEqual(value["due_date"], "明天")
        self.assertEqual(records["action_test_001"]["status"], "pending")
        response = result.to_feishu_response()
        self.assertEqual(response["toast"]["type"], "success")
        self.assertEqual(len(client.updated_cards), 1)
        self.assertEqual(client.updated_cards[0]["identity"], "tenant")
        self.assertIn("字段已暂存", str(client.updated_cards[0]["card"]))

    def test_confirm_button_creates_task_and_marks_created(self) -> None:
        client = FakeFeishuClient()
        payload = {
            "event": {
                "context": {"open_message_id": "om_test_002"},
                "action": {
                    "value": {
                        "action": "confirm_create_task",
                        "item_id": "action_test_001",
                        "title": "整理答辩材料",
                        "meeting_id": "meeting_test_001",
                        "calendar_event_id": "calendar_test_001",
                        "minute_token": "minute_test_001",
                        "project_id": "meetflow",
                        "evidence_refs": [
                            {
                                "source_type": "minute",
                                "source_id": "minute_test_001",
                                "source_url": "https://example.com/minute",
                                "snippet": "张三负责整理答辩材料，明天前完成。",
                            }
                        ],
                    },
                    "form_value": {"owner_override": "张三", "due_date_override": "明天"},
                }
            }
        }
        with patch("adapters.create_feishu_tool_registry", return_value=FakeRegistry()):
            result = handle_post_meeting_card_callback(
                payload=payload,
                settings=self.settings,
                client=client,
                storage=self.storage,
                policy=AgentPolicy(),
            )
        self.assertEqual(result.status, "success")
        records = load_pending_action_records(self.settings)
        self.assertEqual(records["action_test_001"]["status"], "created")
        self.assertTrue(result.data.get("task_mapping"))
        response = result.to_feishu_response()
        self.assertEqual(response["toast"]["type"], "success")
        self.assertIn("card", response)
        self.assertEqual(response["card"]["type"], "raw")
        self.assertEqual(len(client.updated_cards), 1)
        self.assertIn("已创建任务", str(client.updated_cards[0]["card"]))

    def test_reject_button_marks_rejected(self) -> None:
        client = FakeFeishuClient()
        payload = {
            "event": {
                "context": {"open_message_id": "om_test_003"},
                "action": {"value": {"action": "reject_create_task", "item_id": "action_test_001"}},
            }
        }
        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )
        self.assertEqual(result.status, "success")
        records = load_pending_action_records(self.settings)
        self.assertEqual(records["action_test_001"]["status"], "reject_create_task")
        response = result.to_feishu_response()
        self.assertEqual(response["toast"]["type"], "success")
        self.assertIn("card", response)
        self.assertEqual(response["card"]["type"], "raw")
        self.assertEqual(len(client.updated_cards), 1)
        self.assertIn("已拒绝创建", str(client.updated_cards[0]["card"]))

    def test_edit_button_without_values_returns_edit_mode_card(self) -> None:
        client = FakeFeishuClient()
        payload = {
            "event": {
                "context": {"open_message_id": "om_test_004"},
                "action": {"value": {"action": "edit_task_fields", "item_id": "action_test_001"}},
            }
        }
        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )
        self.assertEqual(result.status, "info")
        response = result.to_feishu_response()
        self.assertEqual(response["toast"]["type"], "info")
        self.assertEqual(len(client.updated_cards), 1)
        self.assertIn("保存修改", str(client.updated_cards[0]["card"]))

    def test_reject_after_created_is_blocked_and_keeps_created_state(self) -> None:
        client = FakeFeishuClient()
        bind_pending_action_message(self.settings, item_id="action_test_001", message_id="om_test_005", chat_id="oc_test_chat")
        mark_pending_action_status(
            self.settings,
            "action_test_001",
            status="created",
            result={"status": "success", "message": "已创建任务：整理答辩材料"},
        )
        payload = {"event": {"action": {"value": {"action": "reject_create_task", "item_id": "action_test_001"}}}}
        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )
        self.assertEqual(result.status, "success")
        self.assertIn("已创建", result.message)
        records = load_pending_action_records(self.settings)
        self.assertEqual(records["action_test_001"]["status"], "created")
        self.assertEqual(len(client.updated_cards), 1)
        self.assertEqual(client.updated_cards[0]["message_id"], "om_test_005")

    def test_reject_while_creating_is_blocked(self) -> None:
        client = FakeFeishuClient()
        bind_pending_action_message(self.settings, item_id="action_test_001", message_id="om_test_processing", chat_id="oc_test_chat")
        mark_pending_action_status(
            self.settings,
            "action_test_001",
            status="creating",
            result={"status": "processing", "message": "正在创建任务：整理答辩材料"},
        )
        payload = {"event": {"action": {"value": {"action": "reject_create_task", "item_id": "action_test_001"}}}}
        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )
        self.assertEqual(result.status, "info")
        self.assertIn("正在创建中", result.message)
        records = load_pending_action_records(self.settings)
        self.assertEqual(records["action_test_001"]["status"], "creating")
        self.assertEqual(len(client.updated_cards), 1)
        self.assertEqual(client.updated_cards[0]["message_id"], "om_test_processing")
        self.assertNotIn("拒绝创建", str(client.updated_cards[0]["card"]))

    def test_bound_message_id_takes_priority_over_callback_open_message_id(self) -> None:
        client = FakeFeishuClient()
        bind_pending_action_message(self.settings, item_id="action_test_001", message_id="om_bound_001", chat_id="oc_test_chat")
        payload = {
            "event": {
                "context": {"open_message_id": "om_callback_only_999"},
                "action": {"value": {"action": "reject_create_task", "item_id": "action_test_001"}},
            }
        }
        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(len(client.updated_cards), 1)
        self.assertEqual(client.updated_cards[0]["message_id"], "om_bound_001")

    def test_normalize_due_date_override_accepts_slash_date(self) -> None:
        self.assertEqual(normalize_due_date_override("2025/5/3"), "2025-05-03")
        self.assertEqual(normalize_due_date_override("2025/05/03"), "2025-05-03")
        self.assertEqual(normalize_due_date_override("2025-05-03"), "2025-05-03")

    def test_parse_due_date_to_timestamp_ms_accepts_multiple_absolute_formats(self) -> None:
        slash_short = parse_due_date_to_timestamp_ms("2025/5/3")
        slash_full = parse_due_date_to_timestamp_ms("2025/05/03")
        dash_full = parse_due_date_to_timestamp_ms("2025-05-03")
        self.assertTrue(slash_short.isdigit())
        self.assertEqual(slash_short, slash_full)
        self.assertEqual(slash_short, dash_full)


if __name__ == "__main__":
    unittest.main()
