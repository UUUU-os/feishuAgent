from __future__ import annotations

import unittest

from core.models import ActionItem
from core.post_meeting import (
    ExtractedDecision,
    ExtractedOpenQuestion,
    PostMeetingArtifacts,
    PostMeetingInput,
    build_post_meeting_artifacts_from_input,
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

    def test_extracts_feishu_ai_todo_sentence_without_explicit_prefix(self) -> None:
        """飞书妙记 AI 产物可能直接写“张三负责...明天前完成”，不带待办前缀。"""

        artifacts = build_post_meeting_artifacts_from_input(
            PostMeetingInput(
                meeting_id="m1",
                calendar_event_id="c1",
                minute_token="minute1",
                project_id="meetflow",
                topic="测试会议",
                source_url="https://example.feishu.cn/minutes/minute1",
                raw_text="\n".join(
                    [
                        "基础信息",
                        "今天确认 MeetFlow 的 M4 和 M5 闭环测试。",
                        "AI 产物状态",
                        "张三负责整理 MeetFlow 测试报告，明天下午六点前完成。",
                    ]
                ),
            )
        )

        self.assertEqual(len(artifacts.action_items), 1)
        item = artifacts.action_items[0]
        self.assertEqual(item.owner, "张三")
        self.assertIn("明天", item.due_date)
        self.assertIn(item, artifacts.pending_action_items)
        self.assertIn("MeetFlow 测试报告", item.title)

    def test_does_not_create_task_when_feishu_returns_no_ai_artifacts(self) -> None:
        """“当前没有返回 AI 总结、待办或章节”是系统状态，不是行动项。"""

        artifacts = build_post_meeting_artifacts_from_input(
            PostMeetingInput(
                meeting_id="m1",
                calendar_event_id="c1",
                minute_token="minute1",
                project_id="meetflow",
                topic="测试会议",
                raw_text="\n".join(
                    [
                        "# 测试会议",
                        "## AI 产物状态",
                        "当前没有返回 AI 总结、待办或章节。",
                    ]
                ),
            )
        )

        self.assertEqual(artifacts.action_items, [])
        self.assertEqual(artifacts.pending_action_items, [])


if __name__ == "__main__":
    unittest.main()
