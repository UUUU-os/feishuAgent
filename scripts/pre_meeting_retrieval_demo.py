from __future__ import annotations

import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/pre_meeting_retrieval_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import PreMeetingBriefInput, Resource, build_retrieval_query, identify_meeting_topic, recall_related_resources


def main() -> int:
    """验证 T3.3 关联资源召回。"""

    workflow_input = build_sample_input()
    topic_signal = identify_meeting_topic(workflow_input)
    retrieval_query = build_retrieval_query(workflow_input, topic_signal)
    retrieval_result = recall_related_resources(workflow_input, retrieval_query, top_k=6)
    print(
        json.dumps(
            {
                "topic_signal": topic_signal.to_dict(),
                "retrieval_query": retrieval_query.to_dict(),
                "retrieval_result": retrieval_result.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_sample_input() -> PreMeetingBriefInput:
    """构造包含文档、妙记和任务候选的会前召回样例。"""

    return PreMeetingBriefInput(
        meeting_id="retrieval_demo_meeting",
        calendar_event_id="event_retrieval_demo",
        project_id="meetflow",
        meeting_title="MeetFlow M3 会前知识卡片方案评审",
        meeting_description="评审轻量 RAG、结构化元数据和增量更新方案。",
        participants=[
            {"display_name": "产品负责人"},
            {"display_name": "研发负责人"},
        ],
        attachments=[
            {
                "document_id": "doc_arch",
                "title": "MeetFlow 架构设计文档",
                "url": "https://example.feishu.cn/docx/arch",
                "updated_at": "2026-04-20",
                "block_id": "block_arch_m3",
            },
        ],
        related_resources=[
            Resource(
                resource_id="doc_payload_brief",
                resource_type="feishu_document",
                title="会前卡片字段草案",
                content="包含会议主题、背景摘要、上次决策、当前问题、待读资料和风险点字段。",
                source_url="https://example.feishu.cn/docx/pre_meeting_card",
                updated_at="2026-04-25",
                source_meta={"block_id": "block_card_fields"},
            )
        ],
        memory_snapshot={
            "project_id": "meetflow",
            "project_name": "MeetFlow",
            "aliases": ["飞书会议知识闭环", "会议 Agent"],
            "keywords": ["会前卡片", "轻量 RAG", "结构化元数据", "增量更新"],
            "owners": ["产品负责人", "研发负责人"],
            "documents": [
                {
                    "document_id": "doc_rag_plan",
                    "resource_type": "doc",
                    "title": "M3 轻量 RAG 索引与召回方案",
                    "summary": "说明 KnowledgeDocument、KnowledgeChunk、checksum 和检索排序策略。",
                    "source_url": "https://example.feishu.cn/docx/rag_plan",
                    "updated_at": "2026-04-26",
                    "source_locator": "heading:m3-rag",
                },
                {
                    "document_id": "doc_unrelated",
                    "resource_type": "doc",
                    "title": "报销流程说明",
                    "summary": "行政报销和发票规范。",
                    "source_url": "https://example.feishu.cn/docx/finance",
                    "updated_at": "2026-03-01",
                },
            ],
            "minutes": [
                {
                    "minute_token": "minute_last_review",
                    "resource_type": "minute",
                    "title": "上次 MeetFlow M3 评审妙记",
                    "summary": "上次决定先完成 RetrievalQuery、轻量 RAG 和会前卡片渲染，再接定时触发。",
                    "source_url": "https://example.feishu.cn/minutes/minute_last_review",
                    "updated_at": "2026-04-24",
                    "segment_id": "seg_14",
                }
            ],
            "tasks": [
                {
                    "task_id": "task_index_checksum",
                    "resource_type": "task",
                    "title": "实现 updated_at + checksum 增量索引",
                    "summary": "为 M3 文档清洗和知识索引增加重复构建拦截。",
                    "source_url": "https://example.feishu.cn/task/task_index_checksum",
                    "updated_at": "2026-04-27",
                }
            ],
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
