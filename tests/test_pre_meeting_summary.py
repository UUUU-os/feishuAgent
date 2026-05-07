from __future__ import annotations

import unittest

from core.models import Resource
from core.pre_meeting import (
    PreMeetingBriefInput,
    build_initial_meeting_brief,
    build_retrieval_query,
    identify_meeting_topic,
    recall_related_resources,
)


class PreMeetingSummaryTest(unittest.TestCase):
    """覆盖 M3 会前摘要关键栏位生成。"""

    def test_build_initial_meeting_brief_populates_key_sections(self) -> None:
        workflow_input = PreMeetingBriefInput(
            meeting_id="meeting_demo",
            calendar_event_id="event_demo",
            project_id="meetflow",
            meeting_title="MeetFlow M3 方案评审",
            participants=[{"display_name": "研发负责人"}],
            related_resources=[
                Resource(
                    resource_id="minute_001",
                    resource_type="minute",
                    title="上次评审结论 - MeetFlow M3",
                    content="上次决定优先完成会前卡片和知识检索闭环。",
                    source_url="https://example.feishu.cn/minute/1",
                ),
                Resource(
                    resource_id="doc_001",
                    resource_type="doc",
                    title="当前问题清单 - 负责人字段",
                    content="待确认 create_task_draft 的负责人解析策略。",
                    source_url="https://example.feishu.cn/docx/1",
                ),
                Resource(
                    resource_id="task_001",
                    resource_type="task",
                    title="未完成待办 - 刷新背景幂等键",
                    content="存在重复点击被判重的风险，需要修复。",
                    source_url="https://example.feishu.cn/task/1",
                ),
            ],
            memory_snapshot={"summary": "MeetFlow 聚焦飞书会议知识服务。"},
        )

        topic_signal = identify_meeting_topic(workflow_input)
        retrieval_query = build_retrieval_query(workflow_input, topic_signal)
        retrieval_result = recall_related_resources(workflow_input, retrieval_query, top_k=5)
        brief = build_initial_meeting_brief(
            workflow_input=workflow_input,
            retrieval_query=retrieval_query,
            topic_signal=topic_signal,
            retrieval_result=retrieval_result,
        )

        self.assertTrue(brief.last_decisions)
        self.assertTrue(brief.current_questions)
        self.assertTrue(brief.must_read_resources)
        self.assertTrue(brief.risks)
        self.assertIn("上次结论优先查看", brief.summary)
        self.assertIn("需要提前关注的风险或待办", brief.summary)


if __name__ == "__main__":
    unittest.main()
