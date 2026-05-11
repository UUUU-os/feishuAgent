from __future__ import annotations

import json
import unittest

from cards.post_meeting import build_pending_action_item_button_card
from core.post_meeting import (
    PostMeetingInput,
    build_post_meeting_artifacts_from_input,
    build_task_duplicate_hints,
    extract_owner_candidate,
)
from core.post_meeting_tools import resolve_task_owner_candidates_for_artifacts


class PostMeetingD4TaskCardsTest(unittest.TestCase):
    """覆盖 D4 妙记任务分析和任务卡片展示。"""

    def test_builds_task_card_analysis_grouped_by_owner(self) -> None:
        artifacts = build_post_meeting_artifacts_from_input(build_d4_input())

        analysis = artifacts.extra["task_card_analysis"]
        self.assertEqual(analysis["workflow_type"], "post_meeting_followup")
        self.assertGreaterEqual(analysis["summary"]["total_count"], 3)
        self.assertTrue(analysis["task_creation_requires_human_confirmation"])
        owners = {group["owner"] for group in analysis["owner_groups"]}
        self.assertEqual(owners, {"待补充"})
        self.assertTrue(all(card["owner"] == "待补充" for card in analysis["cards"]))
        self.assertTrue(all(card["owner_candidate"] for card in analysis["cards"][:2]))
        self.assertTrue(all(card["due_date"].startswith("20") for card in analysis["cards"][:2]))
        self.assertTrue(all(card["source"]["snippet"] for card in analysis["cards"]))
        self.assertTrue(all(card["agent_suggestion"] for card in analysis["cards"]))

    def test_task_card_marks_missing_fields_and_agent_suggestion(self) -> None:
        artifacts = build_post_meeting_artifacts_from_input(build_d4_input())
        missing_cards = [card for card in artifacts.extra["task_card_analysis"]["cards"] if card["missing_fields"]]

        self.assertTrue(missing_cards)
        self.assertIn("负责人", missing_cards[0]["agent_suggestion"])

    def test_pending_button_card_contains_d4_advice(self) -> None:
        artifacts = build_post_meeting_artifacts_from_input(build_d4_input())
        item = next(item for item in artifacts.pending_action_items if item.extra.get("missing_fields"))
        card = build_pending_action_item_button_card(artifacts, item)
        payload = json.dumps(card, ensure_ascii=False)

        self.assertIn("Agent 建议", payload)
        self.assertIn("缺失字段", payload)
        self.assertIn("确认创建", payload)
        self.assertIn("拒绝创建", payload)

    def test_duplicate_hint_is_non_destructive(self) -> None:
        hints = build_task_duplicate_hints(
            [
                {"item_id": "a1", "title": "整理答辩材料"},
                {"item_id": "a2", "title": "请整理答辩材料一下"},
                {"item_id": "a3", "title": "确认会议室"},
            ]
        )

        self.assertEqual(len(hints), 1)
        self.assertEqual(set(hints[0]["item_ids"]), {"a1", "a2"})
        self.assertIn("建议确认", hints[0]["reason"])

    def test_weekday_is_not_used_as_owner(self) -> None:
        self.assertEqual(extract_owner_candidate("待办：星期四前完成 D4 任务卡演示截图。"), "")
        self.assertEqual(extract_owner_candidate("待办：周四前完成 D4 任务卡演示截图。"), "")

    def test_extracts_owner_from_minute_speaker_and_colon_formats(self) -> None:
        self.assertEqual(extract_owner_candidate("**李健文**：周四前完成数据库表设计和接口草案。"), "李健文")
        self.assertEqual(extract_owner_candidate("完成时间：李健文周四前完成数据库表设计和接口草案。"), "李健文")

    def test_resolves_task_owner_against_feishu_contact_before_card_send(self) -> None:
        artifacts = build_post_meeting_artifacts_from_input(build_d4_input())
        resolved = resolve_task_owner_candidates_for_artifacts(artifacts.to_dict(), client=FakeFeishuClient())

        cards = resolved["extra"]["task_card_analysis"]["cards"]
        lisi_card = next(card for card in cards if card["owner_candidate"] == "李四")
        wangwu_card = next(card for card in cards if card["owner_candidate"] == "王五")
        self.assertEqual(lisi_card["owner"], "李四")
        self.assertTrue(lisi_card["owner_verified"])
        self.assertNotIn("owner", lisi_card["missing_fields"])
        self.assertEqual(wangwu_card["owner"], "待补充")
        self.assertFalse(wangwu_card["owner_verified"])

        pending_item = next(item for item in resolved["pending_action_items"] if item["owner"] == "李四")
        self.assertEqual(pending_item["extra"]["owner_open_id"], "ou_lisi")
        self.assertEqual(pending_item["extra"]["owner_resolution_status"], "resolved")
        payload = json.dumps(resolved["card_payloads"]["pending_card"], ensure_ascii=False)
        self.assertIn("owner_open_id_override", payload)
        self.assertIn("李四", payload)


def build_d4_input() -> PostMeetingInput:
    """构造覆盖多人任务、缺字段和证据来源的 D4 脱敏妙记。"""

    return PostMeetingInput(
        meeting_id="meeting_d4",
        calendar_event_id="calendar_d4",
        minute_token="minute_d4",
        project_id="meetflow",
        topic="D4 妙记任务卡片样例",
        source_type="minute",
        source_id="minute_d4",
        source_url="https://example.feishu.cn/minutes/minute_d4",
        raw_text="\n".join(
            [
                "# 会后待办",
                "待办：李四周五前完成 OpenClaw 演示脚本走查。",
                "待办：王五下周三前补充真实妙记脱敏样例和截图。",
                "待办：整理 D4 任务卡片演示截图。",
            ]
        ),
    )


class FakeFeishuClient:
    """模拟飞书通讯录搜索，用于验证只采纳唯一可信用户。"""

    def search_users(self, query: str, page_size: int = 5, identity: str = "user") -> dict:
        if query == "李四":
            return {"items": [{"open_id": "ou_lisi", "user_id": "u_lisi", "name": "李四"}]}
        if query == "王五":
            return {
                "items": [
                    {"open_id": "ou_wangwu_1", "user_id": "u_wangwu_1", "name": "王五A"},
                    {"open_id": "ou_wangwu_2", "user_id": "u_wangwu_2", "name": "王五B"},
                ]
            }
        return {"items": []}


if __name__ == "__main__":
    unittest.main()
