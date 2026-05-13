from __future__ import annotations

import unittest

from core.models import Resource
from core.pre_meeting import (
    PreMeetingBriefInput,
    build_retrieval_query,
    identify_meeting_topic,
    recall_related_resources,
)


class PreMeetingRetrievalTest(unittest.TestCase):
    """覆盖 M3 关联资源召回的去重和原因解释。"""

    def test_recall_related_resources_dedupes_and_keeps_reasons(self) -> None:
        workflow_input = PreMeetingBriefInput(
            meeting_id="meeting_demo",
            calendar_event_id="event_demo",
            project_id="meetflow",
            meeting_title="MeetFlow M3 方案评审",
            participants=[{"display_name": "李健文"}],
            attachments=[{"title": "MeetFlow M3 设计稿"}],
            related_resources=[
                Resource(
                    resource_id="doc_001",
                    resource_type="doc",
                    title="MeetFlow M3 设计稿",
                    content="包含会前卡片、知识检索和刷新动作说明。",
                    source_url="https://example.feishu.cn/docx/m3",
                ),
                Resource(
                    resource_id="doc_002",
                    resource_type="doc",
                    title="MeetFlow M3 设计稿",
                    content="同一份文档的重复记录。",
                    source_url="https://example.feishu.cn/docx/m3",
                ),
                Resource(
                    resource_id="task_001",
                    resource_type="task",
                    title="未完成待办 - 刷新背景回调",
                    content="需要修复卡片刷新幂等键。",
                    source_url="https://example.feishu.cn/task/1",
                ),
            ],
            memory_snapshot={
                "recent_resources": [
                    {
                        "resource_id": "minute_001",
                        "resource_type": "minute",
                        "title": "上次评审结论",
                        "summary": "确认 M3 会前卡片继续沿用证据引用格式。",
                        "source_url": "https://example.feishu.cn/minute/1",
                    }
                ]
            },
        )

        retrieval_query = build_retrieval_query(workflow_input, identify_meeting_topic(workflow_input))
        retrieval_result = recall_related_resources(workflow_input, retrieval_query, top_k=6)

        titles = [resource.title for resource in retrieval_result.resources]
        self.assertEqual(titles.count("MeetFlow M3 设计稿"), 1)
        self.assertGreaterEqual(len(retrieval_result.resources), 2)
        self.assertTrue(any(reason.startswith("命中检索词:") for reason in retrieval_result.resources[0].reasons))


if __name__ == "__main__":
    unittest.main()
