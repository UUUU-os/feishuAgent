from __future__ import annotations

import unittest

from cards import build_risk_scan_card
from core.risk_scan import RiskNotificationDecision, RiskScanResult, TaskSnapshot, enrich_risk_with_mapping, scan_risks


class RiskScanCardTest(unittest.TestCase):
    """验证 M5 任务风险提醒卡片包含必要业务信息。"""

    def test_card_contains_risk_fields(self) -> None:
        now = 1_700_000_000
        scan_result = scan_risks(
            tasks=[
                TaskSnapshot(
                    task_id="task_overdue",
                    title="完成方案评审",
                    owner="张三",
                    due_timestamp=now - 3600,
                    updated_at=now - 3600,
                    url="https://example.com/task",
                )
            ],
            now=now,
            stale_update_days=3,
            due_soon_hours=24,
        )
        decision = RiskNotificationDecision(
            should_notify=True,
            reason="需要提醒",
            notify_risks=scan_result.risks,
            idempotency_key="risk_scan:notification:demo",
        )

        card = build_risk_scan_card(decision=decision, scan_result=scan_result)
        rendered = str(card)

        self.assertIsInstance(card, dict)
        self.assertEqual(card["header"]["title"]["content"], "MeetFlow 任务风险提醒")
        self.assertIn("完成方案评审", rendered)
        self.assertIn("张三", rendered)
        self.assertIn("已逾期", rendered)
        self.assertIn("风险概览", rendered)
        self.assertIn("Agent 分析", rendered)
        self.assertIn("影响范围", rendered)
        self.assertIn("建议", rendered)

    def test_card_title_can_distinguish_post_meeting_preview(self) -> None:
        scan_result = RiskScanResult(scanned_count=1, risk_count=0, generated_at=1_700_000_000)
        decision = RiskNotificationDecision(should_notify=False, reason="没有风险")

        card = build_risk_scan_card(
            decision=decision,
            scan_result=scan_result,
            title="MeetFlow 会后行动项风险预检",
            empty_message="本次预检没有需要推送的会后行动项风险。",
        )

        self.assertEqual(card["header"]["title"]["content"], "MeetFlow 会后行动项风险预检")
        self.assertIn("会后行动项风险", str(card))

    def test_card_contains_m4_source_and_evidence(self) -> None:
        now = 1_700_000_000
        scan_result = scan_risks(
            tasks=[
                TaskSnapshot(
                    task_id="task_overdue",
                    title="整理测试报告",
                    owner="张三",
                    due_timestamp=now - 3600,
                    updated_at=now - 3600,
                )
            ],
            now=now,
            stale_update_days=3,
            due_soon_hours=24,
        )
        enriched_risk = enrich_risk_with_mapping(
            scan_result.risks[0],
            {
                "item_id": "action_1",
                "task_id": "task_overdue",
                "meeting_id": "meeting_1",
                "minute_token": "minute_1",
                "title": "MeetFlow 测试会议",
                "source_url": "https://example.com/minutes/1",
                "evidence_refs": [
                    {
                        "source_id": "minute_chunk_1",
                        "source_url": "https://example.com/minutes/1",
                        "snippet": "张三负责整理测试报告。",
                    }
                ],
            },
        )
        enriched_result = RiskScanResult(
            scanned_count=1,
            risk_count=1,
            risks=[enriched_risk],
            generated_at=now,
        )
        decision = RiskNotificationDecision(
            should_notify=True,
            reason="需要提醒",
            notify_risks=[enriched_risk],
        )

        card = build_risk_scan_card(decision=decision, scan_result=enriched_result)
        rendered = str(card)

        self.assertIn("来源", rendered)
        self.assertIn("MeetFlow 测试会议", rendered)
        self.assertIn("minute_1", rendered)
        self.assertIn("张三负责整理测试报告", rendered)

    def test_empty_card_is_green(self) -> None:
        scan_result = RiskScanResult(scanned_count=1, risk_count=0, generated_at=1_700_000_000)
        decision = RiskNotificationDecision(should_notify=False, reason="没有风险")

        card = build_risk_scan_card(decision=decision, scan_result=scan_result)

        self.assertEqual(card["header"]["template"], "green")
        self.assertIn("没有需要推送", str(card))

    def test_card_groups_d5_risks_by_severity_and_type(self) -> None:
        now = 1_700_000_000
        scan_result = scan_risks(
            tasks=[
                TaskSnapshot(
                    task_id="task_missing_due",
                    title="补充演示兜底截图",
                    owner="李四",
                    due_timestamp=0,
                    updated_at=now - 3600,
                ),
                TaskSnapshot(
                    task_id="task_recurring",
                    title="任务卡回调不稳定",
                    owner="王五",
                    due_timestamp=now + 86400,
                    updated_at=now - 3600,
                    raw_payload={"extra": {"repeated_mentions": 3}},
                ),
            ],
            now=now,
            stale_update_days=3,
            due_soon_hours=24,
        )
        decision = RiskNotificationDecision(
            should_notify=True,
            reason="需要提醒",
            notify_risks=scan_result.risks,
        )

        card = build_risk_scan_card(decision=decision, scan_result=scan_result)
        rendered = str(card)

        self.assertIn("高风险", rendered)
        self.assertIn("中风险", rendered)
        self.assertIn("缺少截止时间", rendered)
        self.assertIn("反复出现", rendered)
        self.assertIn("高 1 / 中 2 / 低 0", rendered)

    def test_card_keeps_suppressed_risks_visible_for_diagnosis(self) -> None:
        now = 1_700_000_000
        scan_result = scan_risks(
            tasks=[
                TaskSnapshot(
                    task_id="task_overdue",
                    title="完成客户方案评审",
                    owner="张三",
                    due_timestamp=now - 3600,
                    updated_at=now - 3600,
                ),
                TaskSnapshot(
                    task_id="task_missing_due",
                    title="补充演示兜底截图",
                    owner="李四",
                    due_timestamp=0,
                    updated_at=now - 3600,
                ),
            ],
            now=now,
            stale_update_days=3,
            due_soon_hours=24,
        )
        decision = RiskNotificationDecision(
            should_notify=True,
            reason="只提醒一条，其余降噪",
            notify_risks=[scan_result.risks[0]],
            suppressed_risks=scan_result.risks[1:],
        )

        card = build_risk_scan_card(decision=decision, scan_result=scan_result)
        rendered = str(card)

        self.assertIn("完成客户方案评审", rendered)
        self.assertIn("补充演示兜底截图", rendered)
        self.assertIn("缺少截止时间", rendered)


if __name__ == "__main__":
    unittest.main()
