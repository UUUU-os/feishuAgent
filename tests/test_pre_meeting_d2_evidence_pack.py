from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config import StorageSettings
from core.models import Resource
from core.pre_meeting import (
    PreMeetingBriefInput,
    build_initial_meeting_brief,
    build_pre_meeting_evidence_pack,
    build_retrieval_query,
    identify_meeting_topic,
    merge_evidence_pack_into_brief,
    recall_related_resources,
    render_pre_meeting_card_payload,
)
from core.storage import MeetFlowStorage
from scripts.agent_demo import build_debug_card_arguments


class PreMeetingD2EvidencePackTest(unittest.TestCase):
    """覆盖 D2 会前智能准备卡的历史证据汇聚。"""

    def test_evidence_pack_collects_history_actions_and_risks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = build_temp_storage(Path(temp_dir))
            storage.save_task_mapping(
                item_id="action_001",
                task_id="task_001",
                owner="李健文",
                due_date="2026-05-12",
                status="todo",
                meeting_id="meeting_last",
                minute_token="minute_001",
                title="MeetFlow D2 会前卡片补充历史行动项",
                evidence_refs=[],
                source_url="https://example.feishu.cn/minute/1",
            )
            storage.record_risk_notification(
                risk_key="risk_task_001_overdue",
                task_id="task_001",
                risk_type="overdue",
                severity="high",
                status="notified",
                trace_id="trace_risk",
                recipient="oc_demo",
                summary="MeetFlow D2 行动项逾期风险",
                payload={"reason": "任务临近答辩仍未完成。", "suggestion": "会前确认负责人和截止时间。"},
                notified_at=1_776_000_000,
                suppressed_until=1_776_086_400,
            )
            workflow_input = PreMeetingBriefInput(
                meeting_id="meeting_d2",
                calendar_event_id="event_d2",
                project_id="meetflow",
                meeting_title="MeetFlow D2 会前卡片评审",
                start_time="1777802400",
                end_time="1777806000",
                organizer="产品负责人",
                participants=[{"display_name": "李健文"}, {"display_name": "叶抒锐"}],
                related_resources=[
                    Resource(
                        resource_id="doc_d2",
                        resource_type="doc",
                        title="MeetFlow D2 会前卡片设计稿",
                        content="D2 需要展示历史会议、遗留行动项、历史风险、建议议题和 Evidence Pack。",
                        source_url="https://example.feishu.cn/docx/d2",
                    )
                ],
                memory_snapshot={
                    "recent_meetings": [
                        {
                            "meeting_id": "meeting_last",
                            "title": "MeetFlow D2 上次评审",
                            "decision": "上次决定优先把历史会议、任务和风险接入会前卡片。",
                            "source_url": "https://example.feishu.cn/minute/1",
                        }
                    ],
                    "open_risks": [
                        {
                            "risk_id": "risk_memory_001",
                            "title": "真实模型可能编造历史结论",
                            "reason": "豆包生成必须绑定 Evidence Pack。",
                            "suggestion": "无证据时标注可能相关或待确认。",
                        }
                    ],
                },
            )

            topic_signal = identify_meeting_topic(workflow_input)
            retrieval_query = build_retrieval_query(workflow_input, topic_signal)
            retrieval_result = recall_related_resources(workflow_input, retrieval_query)
            evidence_pack = build_pre_meeting_evidence_pack(
                workflow_input=workflow_input,
                retrieval_query=retrieval_query,
                retrieval_result=retrieval_result,
                storage=storage,
            )
            brief = build_initial_meeting_brief(
                workflow_input=workflow_input,
                retrieval_query=retrieval_query,
                topic_signal=topic_signal,
                retrieval_result=retrieval_result,
            )
            brief = merge_evidence_pack_into_brief(brief, workflow_input, evidence_pack)
            payload = render_pre_meeting_card_payload(brief)

            self.assertTrue(brief.historical_meetings)
            self.assertTrue(brief.open_action_items)
            self.assertTrue(brief.historical_risks)
            self.assertTrue(brief.suggested_agenda)
            self.assertTrue(brief.pre_meeting_checklist)
            fact_labels = [item["label"] for item in payload.facts]
            self.assertIn("会议时间（权威）", fact_labels)
            self.assertIn("核心背景知识", fact_labels)
            self.assertIn("原始链接", fact_labels)
            self.assertIn("2026-05", payload.facts[0]["value"])
            self.assertIn("【待落地任务】", payload.facts[1]["value"])
            self.assertIn("https://example.feishu.cn/docx/d2", payload.facts[2]["value"])
            self.assertIn("Evidence Pack", [section["title"] for section in payload.sections])
            card_text = json.dumps(payload.card, ensure_ascii=False)
            self.assertIn("会前背景知识卡", card_text)
            self.assertIn("会议时间（权威）", card_text)
            self.assertIn("核心背景知识", card_text)
            self.assertIn("原始链接", card_text)
            self.assertNotIn("刷新背景", card_text)
            self.assertNotIn("生成待办草案", card_text)
            self.assertNotIn("查看历史", card_text)
            self.assertNotIn("发给我", card_text)
            self.assertIn("建议优先讨论", brief.summary)

    def test_scripted_debug_uses_d2_card_payload_from_runtime_context(self) -> None:
        workflow_input = PreMeetingBriefInput(
            meeting_id="meeting_auto_d2",
            calendar_event_id="event_auto_d2",
            project_id="meetflow",
            meeting_title="MeetFLow 需求评审会",
            start_time="1778661900",
            end_time="1778663700",
            related_resources=[
                Resource(
                    resource_id="doc_auto_d2",
                    resource_type="doc",
                    title="MeetFlow 需求评审资料",
                    content="会前背景卡需要使用 D2 格式展示核心背景知识和原始链接。",
                    source_url="https://example.feishu.cn/docx/auto-d2",
                )
            ],
        )
        topic_signal = identify_meeting_topic(workflow_input)
        retrieval_query = build_retrieval_query(workflow_input, topic_signal)
        retrieval_result = recall_related_resources(workflow_input, retrieval_query)
        evidence_pack = build_pre_meeting_evidence_pack(
            workflow_input=workflow_input,
            retrieval_query=retrieval_query,
            retrieval_result=retrieval_result,
            storage=None,
        )
        brief = build_initial_meeting_brief(
            workflow_input=workflow_input,
            retrieval_query=retrieval_query,
            topic_signal=topic_signal,
            retrieval_result=retrieval_result,
        )
        brief = merge_evidence_pack_into_brief(brief, workflow_input, evidence_pack)
        payload = render_pre_meeting_card_payload(brief)
        user_content = (
            "工作流目标：测试自动发卡\n\n"
            "运行时上下文 JSON：\n"
            + json.dumps(
                {
                    "event": {"payload": {"summary": workflow_input.meeting_title}},
                    "pre_meeting_card_payload": payload.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        arguments = build_debug_card_arguments(user_content, {"idempotency_key": "demo_key"})

        self.assertEqual(arguments["title"], payload.title)
        self.assertEqual(arguments["card"], payload.card)
        self.assertEqual(arguments["facts"], payload.facts)
        self.assertIn("2026-05-13", json.dumps(arguments["card"], ensure_ascii=False))
        self.assertIn("核心背景知识", json.dumps(arguments["card"], ensure_ascii=False))
        self.assertIn("原始链接", json.dumps(arguments["card"], ensure_ascii=False))
        self.assertNotIn("刷新背景", json.dumps(arguments["card"], ensure_ascii=False))
        self.assertNotIn("发给我", json.dumps(arguments["card"], ensure_ascii=False))
        self.assertNotIn("MeetFlow MeetFLow", arguments["title"])


def build_temp_storage(root: Path) -> MeetFlowStorage:
    """构造临时 SQLite storage，避免污染真实运行数据。"""

    storage = MeetFlowStorage(
        StorageSettings(
            db_path=str(root / "meetflow.sqlite"),
            project_memory_dir=str(root / "projects"),
            audit_log_path=str(root / "audit.jsonl"),
        )
    )
    storage.initialize()
    return storage


if __name__ == "__main__":
    unittest.main()
