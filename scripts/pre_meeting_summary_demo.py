from __future__ import annotations

import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/pre_meeting_summary_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import build_initial_meeting_brief, build_retrieval_query, identify_meeting_topic, recall_related_resources
from scripts.pre_meeting_retrieval_demo import build_sample_input


def main() -> int:
    """验证 T3.5 证据排序与会前摘要生成。"""

    workflow_input = build_sample_input()
    topic_signal = identify_meeting_topic(workflow_input)
    retrieval_query = build_retrieval_query(workflow_input, topic_signal)
    retrieval_result = recall_related_resources(workflow_input, retrieval_query, top_k=6)
    meeting_brief = build_initial_meeting_brief(
        workflow_input=workflow_input,
        retrieval_query=retrieval_query,
        topic_signal=topic_signal,
        retrieval_result=retrieval_result,
    )
    print(
        json.dumps(
            {
                "topic": meeting_brief.topic,
                "summary": meeting_brief.summary,
                "last_decisions": [item.to_dict() for item in meeting_brief.last_decisions],
                "current_questions": [item.to_dict() for item in meeting_brief.current_questions],
                "must_read_resources": [item.to_dict() for item in meeting_brief.must_read_resources],
                "risks": [item.to_dict() for item in meeting_brief.risks],
                "possible_related_resources": [item.to_dict() for item in meeting_brief.possible_related_resources],
                "evidence_refs": [item.to_dict() for item in meeting_brief.evidence_refs],
                "needs_confirmation": meeting_brief.needs_confirmation,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
