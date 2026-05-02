from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config.loader import StorageSettings
from core.observability import EventWriterSettings, configure_structured_events
from core.risk_scan import (
    TaskSnapshot,
    build_risk_dedupe_key,
    decide_risk_notification,
    normalize_task_snapshots,
    parse_task_timestamp,
    scan_risks,
)
from core.storage import MeetFlowStorage


class RiskScanTest(unittest.TestCase):
    """验证 M5 风险规则引擎的确定性行为。"""

    def setUp(self) -> None:
        """测试中关闭结构化事件落盘，避免污染本地运行日志。"""

        configure_structured_events(EventWriterSettings(structured_events_enabled=False))
        self.now = 1_700_000_000

    def test_parse_seconds_and_milliseconds(self) -> None:
        self.assertEqual(parse_task_timestamp("1700000000"), 1_700_000_000)
        self.assertEqual(parse_task_timestamp("1700000000000"), 1_700_000_000)
        self.assertEqual(parse_task_timestamp({"timestamp": "1700000000000"}), 1_700_000_000)

    def test_completed_task_is_skipped(self) -> None:
        result = scan_risks(
            tasks=[
                TaskSnapshot(
                    task_id="task_done",
                    title="已完成任务",
                    status="completed",
                    due_timestamp=self.now - 86400,
                    completed_at=self.now - 3600,
                )
            ],
            now=self.now,
            stale_update_days=3,
            due_soon_hours=24,
        )

        self.assertEqual(result.risk_count, 0)

    def test_detects_overdue_due_soon_stale_and_missing_owner(self) -> None:
        tasks = [
            TaskSnapshot(
                task_id="task_overdue",
                title="逾期任务",
                owner="张三",
                due_timestamp=self.now - 30 * 3600,
                updated_at=self.now - 3600,
            ),
            TaskSnapshot(
                task_id="task_due_soon",
                title="临期任务",
                owner="李四",
                due_timestamp=self.now + 2 * 3600,
                updated_at=self.now - 3600,
            ),
            TaskSnapshot(
                task_id="task_stale",
                title="长期未更新任务",
                owner="王五",
                due_timestamp=self.now + 7 * 86400,
                updated_at=self.now - 5 * 86400,
            ),
            TaskSnapshot(
                task_id="task_missing_owner",
                title="缺少负责人任务",
                due_timestamp=self.now + 7 * 86400,
                updated_at=self.now - 3600,
            ),
        ]

        result = scan_risks(tasks=tasks, now=self.now, stale_update_days=3, due_soon_hours=24)
        risk_types = {risk.risk_type for risk in result.risks}

        self.assertEqual(result.risk_count, 4)
        self.assertIn("overdue", risk_types)
        self.assertIn("due_soon", risk_types)
        self.assertIn("stale_update", risk_types)
        self.assertIn("missing_owner", risk_types)
        self.assertEqual(result.risks[0].severity, "high")

    def test_normalize_action_item_like_dict(self) -> None:
        snapshots = normalize_task_snapshots(
            [
                {
                    "item_id": "task_1",
                    "title": "任务",
                    "owner": "张三",
                    "due_date": "1700000000000",
                    "extra": {"updated_at": "1699900000000", "url": "https://example.com"},
                }
            ]
        )

        self.assertEqual(snapshots[0].task_id, "task_1")
        self.assertEqual(snapshots[0].due_timestamp, 1_700_000_000)
        self.assertEqual(snapshots[0].url, "https://example.com")

    def test_dedupe_key_is_day_bucketed(self) -> None:
        key = build_risk_dedupe_key("task_1", "overdue", self.now)

        self.assertTrue(key.startswith("risk_scan:task_1:overdue:"))

    def test_notification_decision_suppresses_recent_notification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = MeetFlowStorage(
                StorageSettings(
                    db_path=str(Path(tmp_dir) / "meetflow.sqlite"),
                    project_memory_dir=str(Path(tmp_dir) / "projects"),
                    audit_log_path=str(Path(tmp_dir) / "workflow_runs.jsonl"),
                )
            )
            storage.initialize()
            result = scan_risks(
                tasks=[
                    TaskSnapshot(
                        task_id="task_overdue",
                        title="逾期任务",
                        owner="张三",
                        due_timestamp=self.now - 3600,
                        updated_at=self.now - 3600,
                    )
                ],
                now=self.now,
                stale_update_days=3,
                due_soon_hours=24,
            )
            risk = result.risks[0]
            storage.record_risk_notification(
                risk_key=risk.dedupe_key,
                task_id=risk.task_id,
                risk_type=risk.risk_type,
                severity=risk.severity,
                status="notified",
                trace_id="trace_demo",
                recipient="oc_demo",
                summary=risk.reason,
                payload={"title": risk.task.title},
                notified_at=self.now,
                suppressed_until=self.now + 86400,
            )

            decision = decide_risk_notification(
                scan_result=result,
                storage=storage,
                max_reminders_per_day=5,
                now=self.now + 60,
            )

            self.assertFalse(decision.should_notify)
            self.assertEqual(len(decision.suppressed_risks), 1)


if __name__ == "__main__":
    unittest.main()
