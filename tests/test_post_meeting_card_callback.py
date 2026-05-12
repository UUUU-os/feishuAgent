from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cards.post_meeting import (
    build_pending_action_item_button_card,
    build_pending_action_item_reaction_card,
    build_pending_action_items_card,
)
from core.card_callback import (
    handle_post_meeting_card_callback,
    merge_action_values_preserving_cached,
    normalize_due_date_override,
    workflow_context_from_callback_value,
)
from core.confirmation_commands import bind_pending_action_message, load_pending_action_records, mark_pending_action_status, save_pending_action_values
from core.models import ActionItem, AgentToolResult, EvidenceRef
from core.policy import AgentPolicy
from core.post_meeting import parse_due_date_to_timestamp_ms
from core.storage import MeetFlowStorage


class FakeFeishuClient:
    """模拟消息卡片更新接口。"""

    def __init__(self) -> None:
        self.updated_cards: list[dict[str, object]] = []
        self.sent_cards: list[dict[str, object]] = []

    def update_card_message(self, message_id: str, card: dict[str, object], identity: str | None = None) -> dict[str, object]:
        self.updated_cards.append({"message_id": message_id, "card": card, "identity": identity})
        return {"message_id": message_id}

    def send_card_message(
        self,
        receive_id: str,
        card: dict[str, object],
        receive_id_type: str = "chat_id",
        idempotency_key: str = "",
        identity: str | None = None,
    ) -> dict[str, object]:
        message_id = f"om_sent_{len(self.sent_cards) + 1:03d}"
        self.sent_cards.append(
            {
                "message_id": message_id,
                "receive_id": receive_id,
                "receive_id_type": receive_id_type,
                "idempotency_key": idempotency_key,
                "identity": identity,
                "card": card,
            }
        )
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
        self.assertNotIn("修改信息", card_text)
        self.assertNotIn("保存修改", card_text)
        self.assertIn("拒绝创建", card_text)
        self.assertIn("**会议：** M4 按钮回调联调", card_text)
        self.assertIn("**待确认任务数：** 1", card_text)
        self.assertIn("**任务 ID：** action_test_001", card_text)
        self.assertIn("**负责人：** 待补充", card_text)
        self.assertIn("**截止时间：** 待补充", card_text)
        self.assertIn("**优先级：** high｜**置信度：** 0.82", card_text)
        self.assertIn("**待确认原因：** 缺少负责人、截止时间", card_text)
        self.assertIn("**证据：** 张三负责整理答辩材料，明天前完成。", card_text)
        self.assertIn("  \\n**任务 ID：** action_test_001", card_text)
        self.assertIn("待补充  \\n**截止时间：** 待补充", card_text)
        self.assertNotIn("\\n\\n**任务 ID：** action_test_001", card_text)
        self.assertNotIn("待补充\\n\\n**截止时间：** 待补充", card_text)
        self.assertNotIn("负责人：**待补充**", card_text)
        self.assertNotIn("截止时间：**待补充**", card_text)
        self.assertNotIn("任务 ID：`action_test_001`", card_text)
        self.assertNotIn("整理答辩材料**任务 ID", card_text)
        self.assertNotIn("**补充字段**", card_text)
        self.assertNotIn("**任务 ID：**action_test_001", card_text)

    def test_pending_card_keeps_all_tasks_in_one_message(self) -> None:
        items = [
            ActionItem(
                item_id=f"action_test_{index:03d}",
                title=f"整理答辩材料 {index}",
                owner="",
                due_date="",
                priority="medium",
                confidence=0.8,
                needs_confirm=True,
                extra={"confirm_reason": "缺少负责人、截止时间"},
            )
            for index in range(1, 11)
        ]
        artifacts = SimpleNamespace(
            meeting_summary=SimpleNamespace(topic="M4 聚合任务卡"),
            pending_action_items=items,
            action_items=items,
        )
        card = build_pending_action_items_card(artifacts)
        card_text = str(card)

        self.assertIn("整理答辩材料 1", card_text)
        self.assertIn("整理答辩材料 10", card_text)
        self.assertNotIn("另有", card_text)
        forms = [element for element in card.get("body", {}).get("elements", []) if element.get("tag") == "form"]
        self.assertEqual(len(forms), 10)
        self.assertTrue(all("elements" in form for form in forms))
        self.assertTrue(all("body" not in form for form in forms))

    def test_view_pending_tasks_sends_aggregate_task_card_once(self) -> None:
        save_pending_action_values(
            self.settings,
            [
                {
                    "item_id": "action_view_001",
                    "title": "补充状态流转文案",
                    "owner": "叶抒锐",
                    "due_date": "2026-05-13",
                    "priority": "medium",
                    "confidence": 0.95,
                    "meeting_id": "meeting_view_001",
                    "minute_token": "minute_view_001",
                    "review_session_id": "session_view_001",
                    "meeting_topic": "M4 查看任务卡",
                },
                {
                    "item_id": "action_view_002",
                    "title": "整理测试覆盖状态筛选组合",
                    "owner": "",
                    "due_date": "",
                    "priority": "medium",
                    "confidence": 0.7,
                    "meeting_id": "meeting_view_001",
                    "minute_token": "minute_view_001",
                    "review_session_id": "session_view_001",
                    "meeting_topic": "M4 查看任务卡",
                },
            ],
            source={"chat_id": "oc_test_chat", "receive_id_type": "chat_id", "review_session_id": "session_view_001"},
        )
        client = FakeFeishuClient()
        payload = {
            "event": {
                "context": {"open_chat_id": "oc_test_chat", "open_message_id": "om_summary_001"},
                "action": {
                    "value": {
                        "action": "view_pending_tasks",
                        "source_card": "post_meeting_summary",
                        "workflow_type": "post_meeting_followup",
                        "meeting_id": "meeting_view_001",
                        "minute_token": "minute_view_001",
                        "review_session_id": "session_view_001",
                    }
                },
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
        self.assertEqual(len(client.sent_cards), 1)
        sent = client.sent_cards[0]
        self.assertEqual(sent["receive_id"], "oc_test_chat")
        self.assertEqual(sent["identity"], "tenant")
        sent_text = str(sent["card"])
        self.assertIn("补充状态流转文案", sent_text)
        self.assertIn("整理测试覆盖状态筛选组合", sent_text)
        self.assertIn("confirm_action_view_001", sent_text)
        self.assertIn("confirm_action_view_002", sent_text)
        records = load_pending_action_records(self.settings)
        self.assertEqual(records["action_view_001"]["source"]["message_id"], "om_sent_001")
        self.assertEqual(records["action_view_002"]["source"]["message_id"], "om_sent_001")

        second_result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )

        self.assertEqual(second_result.status, "success")
        self.assertEqual(len(client.sent_cards), 1)
        self.assertIn("已经发送过", second_result.message)

    def test_start_risk_scan_quick_action_sends_risk_card(self) -> None:
        payload = {
            "header": {"event_id": "evt_risk_001"},
            "event": {
                "context": {"open_chat_id": "oc_test_chat", "open_message_id": "om_summary_001"},
                "operator": {"operator_id": {"open_id": "ou_user"}},
                "action": {
                    "value": {
                        "action": "start_risk_scan",
                        "source_card": "post_meeting_summary",
                        "workflow_type": "post_meeting_followup",
                        "meeting_id": "meeting_test_001",
                        "minute_token": "minute_test_001",
                    }
                },
            },
        }
        client = FakeFeishuClient()

        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )

        self.assertEqual(result.status, "success")
        self.assertIn("风险巡检", result.message)
        self.assertIsNone(result.agent_input)
        self.assertEqual(len(client.sent_cards), 1)
        sent = client.sent_cards[0]
        self.assertEqual(sent["receive_id"], "oc_test_chat")
        self.assertEqual(sent["identity"], "tenant")
        self.assertIn("MeetFlow 风险巡检提醒", str(sent["card"]))
        self.assertEqual(result.to_feishu_response()["toast"]["type"], "success")

    def test_view_post_meeting_report_quick_action_sends_report_card(self) -> None:
        payload = {
            "event": {
                "context": {"open_chat_id": "oc_test_chat", "open_message_id": "om_summary_001"},
                "action": {
                    "value": {
                        "action": "view_post_meeting_report",
                        "source_card": "post_meeting_summary",
                        "workflow_type": "post_meeting_followup",
                        "report_url": "https://example.com/post-meeting-report",
                    }
                },
            }
        }
        client = FakeFeishuClient()

        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )

        self.assertEqual(result.status, "success")
        self.assertIsNone(result.agent_input)
        self.assertEqual(len(client.sent_cards), 1)
        sent_text = str(client.sent_cards[0]["card"])
        self.assertIn("MeetFlow 完整复盘报告", sent_text)
        self.assertIn("https://example.com/post-meeting-report", sent_text)
        self.assertEqual(result.to_feishu_response()["toast"]["type"], "success")

    def test_aggregate_card_update_keeps_other_task_buttons(self) -> None:
        save_pending_action_values(
            self.settings,
            [
                {
                    "item_id": "action_test_001",
                    "title": "整理答辩材料 1",
                    "owner": "张三",
                    "due_date": "2026-05-13",
                    "priority": "medium",
                    "confidence": 0.95,
                    "meeting_topic": "M4 聚合按钮回调",
                    "evidence_refs": [],
                },
                {
                    "item_id": "action_test_002",
                    "title": "整理答辩材料 2",
                    "owner": "筛选组合",
                    "due_date": "周四前",
                    "priority": "medium",
                    "confidence": 0.9,
                    "meeting_topic": "M4 聚合按钮回调",
                    "extra": {
                        "missing_fields": ["owner", "due_date"],
                        "owner_candidate": "筛选组合",
                        "owner_resolution_status": "not_found",
                    },
                    "evidence_refs": [],
                },
            ],
            source={"chat_id": "oc_test_chat", "receive_id_type": "chat_id"},
        )
        bind_pending_action_message(self.settings, item_id="action_test_001", message_id="om_aggregate", chat_id="oc_test_chat")
        bind_pending_action_message(self.settings, item_id="action_test_002", message_id="om_aggregate", chat_id="oc_test_chat")
        client = FakeFeishuClient()
        payload = {
            "event": {
                "context": {"open_message_id": "om_aggregate"},
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
        updated_card = client.updated_cards[0]["card"]
        updated_text = str(updated_card)
        response = result.to_feishu_response()
        self.assertIn("card", response)
        self.assertEqual(response["card"]["data"], updated_card)
        self.assertEqual(client.updated_cards[0]["message_id"], "om_aggregate")
        self.assertIn("整理答辩材料 1", updated_text)
        self.assertIn("已拒绝创建", updated_text)
        self.assertIn("整理答辩材料 2", updated_text)
        self.assertIn("**负责人：** 待补充", updated_text)
        self.assertIn("**截止时间：** 待补充", updated_text)
        self.assertNotIn("**负责人：** 筛选组合", updated_text)
        self.assertNotIn("**截止时间：** 周四前", updated_text)
        forms = [element for element in updated_card.get("body", {}).get("elements", []) if element.get("tag") == "form"]
        self.assertEqual(len(forms), 1)
        self.assertIn("confirm_action_test_002", updated_text)
        self.assertIn("reject_action_test_002", updated_text)
        self.assertNotIn("confirm_action_test_001", updated_text)

    def test_aggregate_card_update_falls_back_to_review_session_group(self) -> None:
        save_pending_action_values(
            self.settings,
            [
                {
                    "item_id": "action_session_001",
                    "title": "按确认批次保留按钮 1",
                    "owner": "张三",
                    "due_date": "2026-05-13",
                    "priority": "medium",
                    "confidence": 0.95,
                    "meeting_topic": "M4 聚合按钮回调",
                    "review_session_id": "session_group_test",
                },
                {
                    "item_id": "action_session_002",
                    "title": "按确认批次保留按钮 2",
                    "owner": "李四",
                    "due_date": "2026-05-14",
                    "priority": "medium",
                    "confidence": 0.9,
                    "meeting_topic": "M4 聚合按钮回调",
                    "review_session_id": "session_group_test",
                },
            ],
            source={"chat_id": "oc_test_chat", "review_session_id": "session_group_test"},
        )
        client = FakeFeishuClient()
        payload = {
            "event": {
                "context": {"open_message_id": "om_callback_only"},
                "action": {"value": {"action": "reject_create_task", "item_id": "action_session_001"}},
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
        updated_card = client.updated_cards[0]["card"]
        updated_text = str(updated_card)
        response = result.to_feishu_response()
        self.assertIn("card", response)
        self.assertEqual(response["card"]["data"], updated_card)
        self.assertEqual(client.updated_cards[0]["message_id"], "om_callback_only")
        self.assertIn("按确认批次保留按钮 1", updated_text)
        self.assertIn("已拒绝创建", updated_text)
        self.assertIn("按确认批次保留按钮 2", updated_text)
        self.assertIn("confirm_action_session_002", updated_text)
        self.assertNotIn("confirm_action_session_001", updated_text)

    def test_pending_card_strips_markdown_from_business_values(self) -> None:
        item = ActionItem(
            item_id="action_markdown_001",
            title="**李健文**：周四前完成数据库表设计和接口草案",
            owner="李健文",
            due_date="2026-05-14",
            priority="medium",
            confidence=0.95,
            needs_confirm=True,
            evidence_refs=[
                EvidenceRef(
                    source_type="minute",
                    source_id="minute_test_001",
                    source_url="https://example.com/minute",
                    snippet="**李健文**：周四前完成数据库表设计和接口草案。",
                )
            ],
            extra={"confirm_reason": "待人工复核"},
        )
        artifacts = SimpleNamespace(
            meeting_summary=SimpleNamespace(topic="项目组会"),
            pending_action_items=[item],
            action_items=[item],
        )

        card = build_pending_action_items_card(artifacts)
        card_text = str(card)

        self.assertIn("1. 李健文：周四前完成数据库表设计和接口草案", card_text)
        self.assertIn("**负责人：** 待补充", card_text)
        self.assertIn("**证据：** 李健文：周四前完成数据库表设计和接口草案。", card_text)
        self.assertIn("补充字段", card_text)
        self.assertNotIn("**李健文**", card_text)
        self.assertNotIn("**补充字段**", card_text)

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
        self.assertNotIn("修改信息", card_text)
        self.assertNotIn("保存修改", card_text)
        self.assertIn("拒绝创建", card_text)
        self.assertIn("**负责人：** 待补充", card_text)
        self.assertIn("**截止时间：** 待补充", card_text)
        self.assertIn("  \\n**任务 ID：** action_test_001", card_text)
        self.assertNotIn("\\n\\n**任务 ID：** action_test_001", card_text)
        self.assertNotIn("负责人：**待补充**", card_text)
        self.assertNotIn("任务 ID：`action_test_001`", card_text)
        self.assertNotIn("整理答辩材料**任务 ID", card_text)
        self.assertNotIn("**修改字段**", card_text)

    def test_reaction_pending_card_uses_label_only_bold_rendering(self) -> None:
        item = ActionItem(
            item_id="action_test_001",
            title="整理答辩材料",
            owner="张三",
            due_date="2026-05-13",
            priority="medium",
            confidence=0.8,
            needs_confirm=True,
            evidence_refs=[
                EvidenceRef(
                    source_type="minute",
                    source_id="minute_test_001",
                    source_url="https://example.com/minute",
                    snippet="张三负责整理答辩材料，明天前完成。",
                )
            ],
            extra={"confirm_reason": "待人工复核"},
        )
        artifacts = SimpleNamespace(meeting_summary=SimpleNamespace(topic="M4 Reaction 兜底"))

        card = build_pending_action_item_reaction_card(artifacts, item)
        card_text = str(card)

        self.assertIn("**会议：** M4 Reaction 兜底", card_text)
        self.assertIn("**任务：** 整理答辩材料", card_text)
        self.assertIn("**任务 ID：** action_test_001", card_text)
        self.assertIn("**负责人：** 张三", card_text)
        self.assertIn("**截止时间：** 2026-05-13", card_text)
        self.assertIn("  \\n**任务 ID：** action_test_001", card_text)
        self.assertNotIn("\\n\\n**任务 ID：** action_test_001", card_text)
        self.assertNotIn("负责人：**张三**", card_text)
        self.assertNotIn("任务 ID：`action_test_001`", card_text)

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

    def test_schema2_nested_form_value_updates_and_confirms_task(self) -> None:
        """schema 2.0 可能按 form name 嵌套提交值，回调解析必须能读到。"""

        client = FakeFeishuClient()
        nested_edit_payload = {
            "event": {
                "context": {"open_message_id": "om_test_nested"},
                "action": {
                    "value": {
                        "action": "edit_task_fields",
                        "item_id": "action_test_001",
                        "owner_field": "owner_override__action_test_001",
                        "due_date_field": "due_date_override__action_test_001",
                    },
                    "form_value": {
                        "pending_form_action_test_001": {
                            "owner_override__action_test_001": "李健文\u0000",
                            "due_date_override__action_test_001": "2026-05-13",
                        }
                    },
                },
            }
        }

        edit_result = handle_post_meeting_card_callback(
            payload=nested_edit_payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )

        self.assertEqual(edit_result.status, "success")
        records = load_pending_action_records(self.settings)
        self.assertEqual(records["action_test_001"]["value"]["owner"], "李健文")
        self.assertEqual(records["action_test_001"]["value"]["due_date"], "2026-05-13")

        stale_confirm_payload = {
            "event": {
                "context": {"open_message_id": "om_test_nested"},
                "action": {
                    "value": {
                        "action": "confirm_create_task",
                        "item_id": "action_test_001",
                        "title": "整理答辩材料",
                        "owner": "",
                        "due_date": "",
                        "meeting_id": "meeting_test_001",
                        "minute_token": "minute_test_001",
                        "project_id": "meetflow",
                    }
                },
            }
        }
        with patch("adapters.create_feishu_tool_registry", return_value=FakeRegistry()):
            confirm_result = handle_post_meeting_card_callback(
                payload=stale_confirm_payload,
                settings=self.settings,
                client=client,
                storage=self.storage,
                policy=AgentPolicy(),
            )

        self.assertEqual(confirm_result.status, "success")
        mapping = confirm_result.data["task_mapping"]
        self.assertEqual(mapping["owner"], "李健文")
        self.assertEqual(mapping["due_date"], "2026-05-13")
        self.assertEqual(load_pending_action_records(self.settings)["action_test_001"]["status"], "created")

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

    def test_confirm_uses_cached_fields_when_button_value_is_stale_empty(self) -> None:
        update_payload = {
            "event": {
                "context": {"open_message_id": "om_test_cached"},
                "action": {
                    "value": {"action": "edit_task_fields", "item_id": "action_test_001"},
                    "form_value": {"owner_override": "李四", "due_date_override": "2026-05-01"},
                },
            }
        }
        edit_result = handle_post_meeting_card_callback(
            payload=update_payload,
            settings=self.settings,
            client=FakeFeishuClient(),
            storage=self.storage,
            policy=AgentPolicy(),
        )
        self.assertEqual(edit_result.status, "success")

        stale_confirm_payload = {
            "event": {
                "context": {"open_message_id": "om_test_cached"},
                "action": {
                    "value": {
                        "action": "confirm_create_task",
                        "item_id": "action_test_001",
                        "title": "整理答辩材料",
                        "owner": "",
                        "due_date": "",
                        "meeting_id": "meeting_test_001",
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
                },
            }
        }
        with patch("adapters.create_feishu_tool_registry", return_value=FakeRegistry()):
            result = handle_post_meeting_card_callback(
                payload=stale_confirm_payload,
                settings=self.settings,
                client=FakeFeishuClient(),
                storage=self.storage,
                policy=AgentPolicy(),
            )

        self.assertEqual(result.status, "success")
        mapping = result.data["task_mapping"]
        self.assertEqual(mapping["owner"], "李四")
        self.assertEqual(mapping["due_date"], "2026-05-01")

    def test_merge_action_values_preserves_cached_non_empty_fields(self) -> None:
        merged = merge_action_values_preserving_cached(
            {"item_id": "action_test_001", "owner": "李四", "due_date": "2026-05-01"},
            {"action": "confirm_create_task", "owner": "", "due_date": ""},
        )

        self.assertEqual(merged["owner"], "李四")
        self.assertEqual(merged["due_date"], "2026-05-01")
        self.assertEqual(merged["action"], "confirm_create_task")

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
        self.assertIn("确认创建", str(client.updated_cards[0]["card"]))
        self.assertNotIn("保存修改", str(client.updated_cards[0]["card"]))

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

    def test_new_review_session_resets_created_status(self) -> None:
        """同一个妙记重复发卡时，新确认会话应允许再次测试创建任务。"""

        mark_pending_action_status(
            self.settings,
            "action_test_001",
            status="created",
            result={"status": "success", "message": "上一轮已创建"},
        )
        save_pending_action_values(
            self.settings,
            [
                {
                    "item_id": "action_test_001",
                    "title": "整理答辩材料",
                    "owner": "张三",
                    "due_date": "明天",
                    "minute_token": "minute_test_001",
                    "review_session_id": "session_2",
                }
            ],
            source={"chat_id": "oc_test_chat", "review_session_id": "session_2"},
        )

        records = load_pending_action_records(self.settings)

        self.assertEqual(records["action_test_001"]["status"], "pending")
        self.assertEqual(records["action_test_001"]["value"]["review_session_id"], "session_2")

    def test_old_review_session_card_is_blocked_after_new_card_sent(self) -> None:
        save_pending_action_values(
            self.settings,
            [
                {
                    "item_id": "action_test_001",
                    "title": "整理答辩材料",
                    "review_session_id": "session_new",
                }
            ],
            source={"chat_id": "oc_test_chat", "review_session_id": "session_new"},
        )
        payload = {
            "event": {
                "action": {
                    "value": {
                        "action": "confirm_create_task",
                        "item_id": "action_test_001",
                        "review_session_id": "session_old",
                    }
                }
            }
        }

        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=FakeFeishuClient(),
            storage=self.storage,
            policy=AgentPolicy(),
        )

        self.assertEqual(result.status, "info")
        self.assertIn("旧的待确认卡", result.message)

    def test_review_session_enters_create_task_idempotency_key(self) -> None:
        context = workflow_context_from_callback_value(
            {
                "action": "confirm_create_task",
                "item_id": "action_test_001",
                "minute_token": "minute_test_001",
                "review_session_id": "session_2",
            }
        )

        self.assertEqual(
            context.raw_context["decision"]["idempotency_key"],
            "post_meeting_card:minute_test_001:action_test_001:session_2",
        )

    def test_reject_callback_updates_review_session_audit(self) -> None:
        save_pending_action_values(
            self.settings,
            [
                {
                    "action": "reject_create_task",
                    "item_id": "action_test_001",
                    "title": "整理答辩材料",
                    "review_session_id": "session_audit_001",
                    "meeting_id": "meeting_test_001",
                    "minute_token": "minute_test_001",
                }
            ],
            source={"chat_id": "oc_test_chat", "review_session_id": "session_audit_001"},
        )
        payload = {
            "event": {
                "action": {
                    "value": {
                        "action": "reject_create_task",
                        "item_id": "action_test_001",
                        "review_session_id": "session_audit_001",
                        "meeting_id": "meeting_test_001",
                        "minute_token": "minute_test_001",
                    }
                }
            }
        }

        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=FakeFeishuClient(),
            storage=self.storage,
            policy=AgentPolicy(),
        )

        self.assertEqual(result.status, "success")
        review_session = self.storage.get_review_session("session_audit_001")
        self.assertIsNotNone(review_session)
        assert review_session is not None
        self.assertEqual(review_session["status"], "completed")
        self.assertEqual(review_session["rejected_count"], 1)

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
