from __future__ import annotations

import json
import unittest

from cards.post_meeting import build_post_meeting_summary_card
from core.post_meeting import PostMeetingInput, build_post_meeting_artifacts_from_input


class PostMeetingD3ReviewCardTest(unittest.TestCase):
    """覆盖 D3 会后复盘卡的结构化字段和卡片渲染。"""

    def test_builds_structured_review_fields_from_transcript(self) -> None:
        artifacts = build_post_meeting_artifacts_from_input(build_d3_input())

        self.assertGreaterEqual(len(artifacts.decisions), 2)
        self.assertGreaterEqual(len(artifacts.open_questions), 2)
        self.assertGreaterEqual(len(artifacts.action_items), 3)
        self.assertGreaterEqual(len(artifacts.risks), 2)
        self.assertGreaterEqual(len(artifacts.disagreements), 2)
        self.assertGreaterEqual(len(artifacts.follow_up_suggestions), 3)
        self.assertIn("主要价值", artifacts.extra["review_summary"])
        self.assertGreaterEqual(artifacts.evidence_pack["total_count"], 6)

    def test_groups_action_items_by_owner_for_overview(self) -> None:
        artifacts = build_post_meeting_artifacts_from_input(build_d3_input())

        groups = artifacts.extra["action_item_owner_groups"]
        owners = {group["owner"] for group in groups}
        self.assertIn("李四", owners)
        self.assertIn("王五", owners)
        self.assertIn("赵六", owners)
        self.assertTrue(all(group["items"] for group in groups))

    def test_summary_card_contains_d3_sections(self) -> None:
        artifacts = build_post_meeting_artifacts_from_input(build_d3_input())
        artifacts.extra["review_session_id"] = "session_d3"
        card = build_post_meeting_summary_card(artifacts)
        payload = json.dumps(card, ensure_ascii=False)

        self.assertNotIn("schema", card)
        self.assertIn("elements", card)
        self.assertIn("MeetFlow 会后复盘", payload)
        self.assertIn("会议复盘摘要", payload)
        self.assertIn("行动项概览", payload)
        self.assertIn("风险提示", payload)
        self.assertIn("争议点 / 分歧点", payload)
        self.assertIn("后续建议", payload)
        self.assertIn("Evidence Pack", payload)
        self.assertIn("执行风险巡检", payload)
        self.assertIn("查看任务卡", payload)
        self.assertIn("查看完整报告", payload)
        self.assertIn('"action": "view_pending_tasks"', payload)
        self.assertIn('"action": "start_risk_scan"', payload)
        self.assertIn('"action": "view_post_meeting_report"', payload)
        self.assertIn('"review_session_id": "session_d3"', payload)
        self.assertIn('"tag": "action"', payload)
        self.assertIn('"value": {"action": "view_pending_tasks"', payload)
        self.assertNotIn('"behaviors": [{"type": "callback"', payload)

    def test_summary_report_button_keeps_local_path_in_callback_value(self) -> None:
        artifacts = build_post_meeting_artifacts_from_input(build_d3_input())
        artifacts.extra["report_path"] = "storage/reports/m4/demo.md"
        card = build_post_meeting_summary_card(artifacts)
        payload = json.dumps(card, ensure_ascii=False)

        self.assertIn('"report_path": "storage/reports/m4/demo.md"', payload)
        self.assertNotIn('"url": "storage/reports/m4/demo.md"', payload)

    def test_summary_report_button_uses_http_url_when_available(self) -> None:
        artifacts = build_post_meeting_artifacts_from_input(build_d3_input())
        artifacts.extra["report_url"] = "https://example.com/report"
        card = build_post_meeting_summary_card(artifacts)
        payload = json.dumps(card, ensure_ascii=False)

        self.assertIn('"report_url": "https://example.com/report"', payload)
        self.assertIn('"tag": "action"', payload)
        self.assertIn('"value": {"action": "view_post_meeting_report"', payload)
        self.assertNotIn('"url": "https://example.com/report"', payload)


def build_d3_input() -> PostMeetingInput:
    """构造覆盖 D3 全部核心模块的脱敏纪要。"""

    return PostMeetingInput(
        meeting_id="meeting_d3",
        calendar_event_id="calendar_d3",
        minute_token="minute_d3",
        project_id="meetflow",
        topic="D3 会后结构化复盘样例",
        source_type="minute",
        source_id="minute_d3",
        source_url="https://example.feishu.cn/minutes/minute_d3",
        raw_text="\n".join(
            [
                "# 会议总结",
                "结论：本次确认 OpenClaw 演示主线采用会前准备、会后复盘和风险巡检的闭环叙事。",
                "结论：会后总结卡必须升级为结构化复盘卡。",
                "开放问题：完整报告入口是先使用本地 Markdown 路径，还是同步生成飞书云文档链接？",
                "开放问题：风险巡检按钮是否直接触发 M5？",
                "待办：李四周五前完成 D3 会后总结卡 JSON 样式走查。",
                "待办：王五下周三前补充真实妙记脱敏样例和截图。",
                "待办：请赵六整理 Evidence Pack 中关键结论对应的妙记片段。",
                "风险：如果真实妙记没有返回 AI 总结，演示会缺少素材，需要准备脱敏兜底样例。",
                "风险：风险巡检依赖 M4 任务映射，如果用户没有确认创建任务，M5 演示可能扫不到本轮任务。",
                "争议点：前端倾向于做卡片按钮，但是后端认为本地 Markdown 路径不能直接作为飞书链接。",
                "分歧：是否直接发送真实群消息暂未统一，倾向于先只读报告，再在测试群灰度发卡。",
            ]
        ),
    )


if __name__ == "__main__":
    unittest.main()
