from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config.loader import StorageSettings
from core.models import Event, WorkflowContext, WorkflowResult
from core.pre_meeting import (
    PreMeetingBriefInput,
    build_pre_meeting_brief_artifacts,
    identify_meeting_topic,
)
from core.storage import MeetFlowStorage


class PreMeetingTopicTest(unittest.TestCase):
    """覆盖 M3 主题识别和卡片刷新场景的上下文补全。"""

    def test_identify_topic_from_clear_title(self) -> None:
        signal = identify_meeting_topic(
            PreMeetingBriefInput(
                meeting_id="meeting_demo",
                calendar_event_id="event_demo",
                project_id="meetflow",
                meeting_title="MeetFlow M3 会前知识卡片方案评审",
                meeting_description="讨论轻量 RAG 检索和飞书卡片交互。",
                participants=[{"display_name": "李健文"}],
                attachments=[{"title": "MeetFlow M3 设计说明"}],
                memory_snapshot={"summary": "MeetFlow 聚焦飞书会议知识服务。"},
            )
        )

        self.assertIn("meetflow", signal.topic.lower())
        self.assertGreaterEqual(signal.confidence, 0.60)
        self.assertFalse(signal.needs_confirmation)

    def test_identify_topic_from_weak_title_with_attachment_and_memory(self) -> None:
        signal = identify_meeting_topic(
            PreMeetingBriefInput(
                meeting_id="meeting_demo",
                calendar_event_id="event_demo",
                project_id="meetflow",
                meeting_title="同步",
                participants=[{"display_name": "产品负责人"}],
                attachments=[{"title": "MeetFlow M3 轻量 RAG 设计稿"}],
                memory_snapshot={
                    "projects": [
                        {
                            "project_id": "meetflow",
                            "name": "MeetFlow",
                            "keywords": ["M3", "轻量 RAG"],
                        }
                    ]
                },
            )
        )

        self.assertIn("MeetFlow", signal.topic)
        self.assertIn("M3", signal.query_hints)
        self.assertGreaterEqual(signal.confidence, 0.60)

    def test_identify_topic_needs_confirmation_when_context_missing(self) -> None:
        signal = identify_meeting_topic(
            PreMeetingBriefInput(
                meeting_id="meeting_demo",
                calendar_event_id="event_demo",
                project_id="meetflow",
                meeting_title="讨论",
            )
        )

        self.assertTrue(signal.needs_confirmation)
        self.assertIn("topic_evidence", signal.missing_context)
        self.assertIn("participants", signal.missing_context)

    def test_card_refresh_hydrates_context_from_latest_saved_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = MeetFlowStorage(
                StorageSettings(
                    db_path=str(Path(tmp_dir) / "meetflow.sqlite"),
                    project_memory_dir=str(Path(tmp_dir) / "projects"),
                    audit_log_path=str(Path(tmp_dir) / "audit.jsonl"),
                )
            )
            storage.initialize()
            storage.save_workflow_result(
                WorkflowResult(
                    trace_id="trace_previous",
                    workflow_name="pre_meeting_brief",
                    status="success",
                    summary="previous",
                    payload={
                        "payload": {
                            "context": {
                                "event": {
                                    "payload": {
                                        "meeting_id": "meeting_demo",
                                        "calendar_event_id": "event_demo",
                                        "summary": "MeetFlow M3 评审会",
                                        "description": "确认卡片刷新与证据检索边界。",
                                        "participants": [{"display_name": "产品负责人"}],
                                        "attachments": [{"title": "M3 方案文档"}],
                                    }
                                },
                                "raw_context": {
                                    "payload": {
                                        "meeting_id": "meeting_demo",
                                        "calendar_event_id": "event_demo",
                                        "summary": "MeetFlow M3 评审会",
                                        "description": "确认卡片刷新与证据检索边界。",
                                        "participants": [{"display_name": "产品负责人"}],
                                        "attachments": [{"title": "M3 方案文档"}],
                                    }
                                },
                            }
                        }
                    },
                    created_at=1700000000,
                )
            )
            context = WorkflowContext(
                workflow_type="pre_meeting_brief",
                trace_id="trace_refresh",
                event=Event(
                    event_id="evt_refresh",
                    event_type="card.refresh_pre_meeting",
                    event_time="1700000100",
                    source="feishu_card",
                    actor="ou_demo",
                    payload={
                        "meeting_id": "meeting_demo",
                        "calendar_event_id": "event_demo",
                    },
                    trace_id="trace_refresh",
                ),
                meeting_id="meeting_demo",
                calendar_event_id="event_demo",
                project_id="meetflow",
            )

            artifacts = build_pre_meeting_brief_artifacts(context, storage=storage)

            self.assertEqual(artifacts.workflow_input.meeting_title, "MeetFlow M3 评审会")
            self.assertEqual(artifacts.workflow_input.participants[0]["display_name"], "产品负责人")
            self.assertEqual(artifacts.workflow_input.attachments[0]["title"], "M3 方案文档")


if __name__ == "__main__":
    unittest.main()
