from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config.loader import StorageSettings
from core.storage import MeetFlowStorage


class StorageRiskNotificationsTest(unittest.TestCase):
    """验证风险提醒历史表和降噪查询。"""

    def test_record_and_read_latest_risk_notification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = build_storage(tmp_dir)
            now = 1_700_000_000

            storage.record_risk_notification(
                risk_key="risk_scan:task_1:overdue:20260502",
                task_id="task_1",
                risk_type="overdue",
                severity="high",
                status="notified",
                trace_id="trace_demo",
                recipient="oc_demo",
                summary="任务已逾期",
                payload={"title": "任务"},
                notified_at=now,
                suppressed_until=now + 86400,
            )

            latest = storage.get_latest_risk_notification("risk_scan:task_1:overdue:20260502")

            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest["task_id"], "task_1")
            self.assertEqual(latest["payload_json"]["title"], "任务")
            self.assertTrue(storage.has_recent_risk_notification("risk_scan:task_1:overdue:20260502", now + 60))
            self.assertFalse(storage.has_recent_risk_notification("risk_scan:task_1:overdue:20260502", now + 90000))

    def test_get_task_mapping_by_task_id_keeps_m4_provenance(self) -> None:
        """M5 能用飞书 task_id 找回 M4 保存的会议和证据来源。"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = build_storage(tmp_dir)
            storage.save_task_mapping(
                item_id="action_1",
                task_id="task_1",
                meeting_id="meeting_1",
                minute_token="minute_1",
                title="MeetFlow 测试会议",
                owner="张三",
                due_date="2026-05-05",
                status="created",
                evidence_refs=[
                    {
                        "source_id": "minute_chunk_1",
                        "source_type": "minute",
                        "source_url": "https://example.com/minutes/1",
                        "snippet": "张三负责整理测试报告。",
                    }
                ],
                source_url="https://example.com/minutes/1",
            )

            mapping = storage.get_task_mapping_by_task_id("task_1")

            self.assertIsNotNone(mapping)
            assert mapping is not None
            self.assertEqual(mapping["item_id"], "action_1")
            self.assertEqual(mapping["meeting_id"], "meeting_1")
            self.assertEqual(mapping["title"], "MeetFlow 测试会议")
            self.assertEqual(mapping["evidence_refs"][0]["source_id"], "minute_chunk_1")


def build_storage(tmp_dir: str) -> MeetFlowStorage:
    """构造临时 SQLite 存储。"""

    storage = MeetFlowStorage(
        StorageSettings(
            db_path=str(Path(tmp_dir) / "meetflow.sqlite"),
            project_memory_dir=str(Path(tmp_dir) / "projects"),
            audit_log_path=str(Path(tmp_dir) / "workflow_runs.jsonl"),
        )
    )
    storage.initialize()
    return storage


if __name__ == "__main__":
    unittest.main()
