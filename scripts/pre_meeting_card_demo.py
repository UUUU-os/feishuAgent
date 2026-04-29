from __future__ import annotations

import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/pre_meeting_card_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import EvidenceRef, MeetingBrief, MeetingBriefItem, render_pre_meeting_card_payload


def main() -> int:
    """演示 T3.7 会前卡片模板渲染结果。"""

    evidence = EvidenceRef(
        source_type="doc",
        source_id="kref_demo_m3",
        source_url="https://example.feishu.cn/docx/demo",
        snippet="M3 会前卡片需要轻量 RAG、稳定引用和证据展开。",
        updated_at="2026-04-29",
    )
    brief = MeetingBrief(
        meeting_id="meeting_demo_m3",
        calendar_event_id="event_demo_m3",
        project_id="meetflow",
        topic="MeetFlow M3 会前知识卡片评审",
        summary="本次会议建议聚焦 evidence pack、混合检索和父子 chunk 展开是否满足真实会前扫读。",
        last_decisions=[
            MeetingBriefItem(
                title="先完成轻量 RAG 主链路",
                content="SQLite 保存权威元数据，ChromaDB 只负责向量召回。",
                evidence_refs=[evidence],
                confidence=0.86,
            )
        ],
        current_questions=[
            MeetingBriefItem(
                title="是否需要接入真实 reranker provider",
                content="当前 local-rule 已能审计重排字段，真实 provider 可后续替换。",
                evidence_refs=[evidence],
                confidence=0.72,
            )
        ],
        risks=[
            MeetingBriefItem(
                title="不同 embedding 空间混检",
                content="已通过 embedding 指纹和 collection 隔离降低风险。",
                evidence_refs=[evidence],
                confidence=0.8,
            )
        ],
        must_read_resources=[
            MeetingBriefItem(
                title="RAGFlow 设计阅读笔记",
                content="重点看 chunk schema、reranker、TOC 和 evidence pack。",
                evidence_refs=[evidence],
                confidence=0.78,
            )
        ],
        evidence_refs=[evidence],
        confidence=0.82,
    )
    payload = render_pre_meeting_card_payload(brief)
    print(json.dumps(payload.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
