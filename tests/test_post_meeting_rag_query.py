from __future__ import annotations

import unittest

from core.models import ActionItem
from core.post_meeting import (
    ExtractedDecision,
    ExtractedOpenQuestion,
    PostMeetingArtifacts,
    PostMeetingInput,
    build_post_meeting_related_resource_query,
    build_post_meeting_related_resource_query_plan,
)


class PostMeetingRagQueryTest(unittest.TestCase):
    """覆盖 M4 会后 RAG query 的关键词提取和审计信息。"""

    def test_query_prefers_business_terms_and_filters_execution_noise(self) -> None:
        artifacts = PostMeetingArtifacts(
            workflow_input=PostMeetingInput(
                meeting_id="m1",
                calendar_event_id="c1",
                minute_token="minute1",
                project_id="meetflow",
                topic="MeetFlow M4 会后任务闭环评审",
            ),
            cleaned_transcript=None,  # type: ignore[arg-type]
            meeting_summary=None,  # type: ignore[arg-type]
            decisions=[
                ExtractedDecision(
                    decision_id="d1",
                    content="决定采用卡片按钮回调方案沉淀 pending registry 状态机。",
                )
            ],
            open_questions=[
                ExtractedOpenQuestion(
                    question_id="q1",
                    content="是否需要把 RAG query 计划写入联调报告？",
                )
            ],
            action_items=[
                ActionItem(
                    item_id="a1",
                    title="负责人：张三，截止：明天，整理 MeetFlow RAG query 优化方案",
                    owner="张三",
                    due_date="明天",
                )
            ],
        )

        plan = build_post_meeting_related_resource_query_plan(artifacts)
        self.assertEqual(build_post_meeting_related_resource_query(artifacts), plan.query)
        self.assertIn("meetflow", plan.query)
        self.assertIn("pending", plan.query)
        self.assertIn("registry", plan.query)
        self.assertIn("rag", plan.query)
        self.assertNotIn("张三", plan.query)
        self.assertNotIn("明天", plan.query)
        self.assertIn("topic", plan.term_sources.get("meetflow", []))


if __name__ == "__main__":
    unittest.main()
