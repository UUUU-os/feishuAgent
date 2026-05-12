from __future__ import annotations

import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/pre_meeting_topic_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import PreMeetingBriefInput, build_retrieval_query, identify_meeting_topic


def main() -> int:
    """验证 T3.2 会议主题识别和 query 增强。"""

    results = []
    for sample in build_samples():
        topic_signal = identify_meeting_topic(sample)
        retrieval_query = build_retrieval_query(sample, topic_signal)
        results.append(
            {
                "case": sample.meeting_id,
                "title": sample.meeting_title,
                "topic_signal": topic_signal.to_dict(),
                "retrieval_query": retrieval_query.to_dict(),
            }
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def build_samples() -> list[PreMeetingBriefInput]:
    """构造三条会前主题识别样例。

    覆盖：
    - 标题明确，能直接识别项目和业务实体
    - 标题过短，但附件和项目记忆能补全检索上下文
    - 信息不足，需要进入待确认或可能相关资料模式
    """

    memory = {
        "project_id": "meetflow",
        "project_name": "MeetFlow",
        "aliases": ["飞书会议知识闭环", "会议 Agent"],
        "keywords": ["会前卡片", "轻量 RAG", "Action Item", "风险巡检"],
        "owners": ["产品负责人", "研发负责人"],
    }
    return [
        PreMeetingBriefInput(
            meeting_id="topic_demo_clear",
            calendar_event_id="event_clear",
            project_id="meetflow",
            meeting_title="MeetFlow M3 会前知识卡片方案评审",
            meeting_description="评审轻量 RAG、结构化元数据和增量更新方案。",
            participants=[
                {"display_name": "产品负责人"},
                {"display_name": "研发负责人"},
            ],
            attachments=[
                {"title": "MeetFlow 架构设计文档"},
            ],
            memory_snapshot=memory,
        ),
        PreMeetingBriefInput(
            meeting_id="topic_demo_short_title",
            calendar_event_id="event_short",
            project_id="meetflow",
            meeting_title="同步",
            meeting_description="",
            participants=[
                {"display_name": "研发负责人"},
                {"display_name": "测试同学"},
            ],
            attachments=[
                {"title": "M3 轻量 RAG 索引与召回方案"},
                {"title": "会前卡片字段草案"},
            ],
            memory_snapshot=memory,
        ),
        PreMeetingBriefInput(
            meeting_id="topic_demo_missing_context",
            calendar_event_id="event_missing",
            project_id="meetflow",
            meeting_title="讨论",
            meeting_description="",
            participants=[],
            attachments=[],
            memory_snapshot={},
        ),
    ]


if __name__ == "__main__":
    raise SystemExit(main())
