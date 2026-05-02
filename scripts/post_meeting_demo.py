from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/post_meeting_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cards.post_meeting import build_pending_action_items_card, build_post_meeting_summary_card
from core.models import MeetingSummary
from core.post_meeting import (
    CleanedTranscript,
    PostMeetingArtifacts,
    PostMeetingInput,
    clean_meeting_transcript,
    extract_action_items,
    extract_decisions,
    extract_open_questions,
)


@dataclass(slots=True)
class DemoSample:
    """本地演示样例。

    T4.8 的 demo 只验证本地纯函数链路，不读取配置、不访问飞书、不执行任何
    写操作。样例文本刻意覆盖完整任务、缺字段任务、决策和开放问题。
    """

    sample_id: str
    topic: str
    raw_text: str


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="MeetFlow M4 会后总结本地 mock demo。")
    parser.add_argument("--backend", choices=["local"], default="local", help="当前仅支持 local，不访问飞书。")
    parser.add_argument(
        "--sample",
        choices=["all", *sorted(build_demo_samples().keys())],
        default="all",
        help="选择内置样例；默认运行全部样例。",
    )
    parser.add_argument("--transcript-file", default="", help="读取本地纪要文本文件；传入后忽略 --sample。")
    parser.add_argument("--show-card-json", action="store_true", help="打印完整会后卡片 JSON。")
    return parser.parse_args()


def main() -> int:
    """运行本地 M4 会后流程 demo。"""

    args = parse_args()
    samples = load_demo_samples(args)
    reports = [run_demo_sample(sample, show_card_json=args.show_card_json) for sample in samples]
    print(json.dumps({"backend": args.backend, "sample_count": len(samples), "reports": reports}, ensure_ascii=False, indent=2))
    return 0


def load_demo_samples(args: argparse.Namespace) -> list[DemoSample]:
    """根据参数读取内置样例或本地文本文件。"""

    if args.transcript_file:
        path = Path(args.transcript_file)
        raw_text = path.read_text(encoding="utf-8")
        return [DemoSample(sample_id="file", topic=path.stem, raw_text=raw_text)]

    samples = build_demo_samples()
    if args.sample == "all":
        return [samples[key] for key in sorted(samples)]
    return [samples[args.sample]]


def run_demo_sample(sample: DemoSample, show_card_json: bool = False) -> dict[str, Any]:
    """执行单个样例的清洗、抽取和卡片生成。"""

    workflow_input = PostMeetingInput(
        meeting_id=f"meeting_{sample.sample_id}",
        calendar_event_id=f"calendar_{sample.sample_id}",
        minute_token=f"minute_{sample.sample_id}",
        project_id="meetflow",
        topic=sample.topic,
        source_type="minute",
        source_id=f"minute_{sample.sample_id}",
        source_url=f"https://example.com/minutes/minute_{sample.sample_id}",
        raw_text=sample.raw_text,
    )
    cleaned = clean_meeting_transcript(sample.raw_text)
    cleaned.source_type = workflow_input.source_type
    cleaned.source_id = workflow_input.source_id
    cleaned.source_url = workflow_input.source_url
    decisions = extract_decisions(cleaned, meeting_id=workflow_input.meeting_id, source_url=workflow_input.source_url)
    open_questions = extract_open_questions(
        cleaned,
        meeting_id=workflow_input.meeting_id,
        source_url=workflow_input.source_url,
    )
    action_items = extract_action_items(
        cleaned,
        meeting_id=workflow_input.meeting_id,
        source_url=workflow_input.source_url,
    )
    pending_action_items = [item for item in action_items if item.needs_confirm]
    meeting_summary = MeetingSummary(
        meeting_id=workflow_input.meeting_id,
        project_id=workflow_input.project_id,
        topic=workflow_input.topic,
        decisions=[item.content for item in decisions],
        open_questions=[item.content for item in open_questions],
        action_items=action_items,
        evidence_refs=[
            ref
            for item in [*decisions, *open_questions, *action_items]
            for ref in list(getattr(item, "evidence_refs", []) or [])
        ],
    )
    artifacts = PostMeetingArtifacts(
        workflow_input=workflow_input,
        cleaned_transcript=cleaned,
        meeting_summary=meeting_summary,
        decisions=decisions,
        open_questions=open_questions,
        action_items=action_items,
        pending_action_items=pending_action_items,
    )
    summary_card = build_post_meeting_summary_card(artifacts)
    pending_card = build_pending_action_items_card(artifacts)

    report: dict[str, Any] = {
        "sample_id": sample.sample_id,
        "topic": sample.topic,
        "cleaned": summarize_cleaned_transcript(cleaned),
        "decisions": [item.to_dict() for item in decisions],
        "open_questions": [item.to_dict() for item in open_questions],
        "action_items": [item.to_dict() for item in action_items],
        "card_summary": {
            "summary_card_title": summary_card["header"]["title"]["content"],
            "summary_card_template": summary_card["header"]["template"],
            "summary_card_elements": count_card_elements(summary_card),
            "pending_card_title": pending_card["header"]["title"]["content"],
            "pending_card_template": pending_card["header"]["template"],
            "pending_card_elements": count_card_elements(pending_card),
        },
    }
    if show_card_json:
        report["card_json"] = {
            "summary_card": summary_card,
            "pending_card": pending_card,
        }
    return report


def summarize_cleaned_transcript(cleaned: CleanedTranscript) -> dict[str, Any]:
    """生成适合终端阅读的清洗结果摘要。"""

    return {
        "line_count": len(cleaned.lines),
        "sections": [section.to_dict() for section in cleaned.sections],
        "signal_lines": list(cleaned.signal_lines),
        "extra": dict(cleaned.extra),
    }


def count_card_elements(card: dict[str, Any]) -> int:
    """兼容旧版 `elements` 和 schema 2.0 `body.elements` 的元素计数。"""

    if not isinstance(card, dict):
        return 0
    elements = card.get("elements")
    if isinstance(elements, list):
        return len(elements)
    body = card.get("body")
    if isinstance(body, dict) and isinstance(body.get("elements"), list):
        return len(body["elements"])
    return 0


def build_demo_samples() -> dict[str, DemoSample]:
    """构造 T4.8 的内置 mock 纪要样例。"""

    return {
        "complete": DemoSample(
            sample_id="complete",
            topic="M4 会后任务完整字段样例",
            raw_text="""
以下内容由 AI 智能生成
# 会议总结
结论：本周先采用 BM25/RRF 融合方案，reranker 放到后续灰度。
待办：李四周五前完成 demo 验证。
负责人：王五，截止：下周三前补充风险清单。
开放问题：是否接入真实 reranker provider？
会议录制已结束
""",
        ),
        "missing_owner": DemoSample(
            sample_id="missing_owner",
            topic="M4 缺负责人样例",
            raw_text="""
会议纪要
结论：会后卡片先展示待确认任务，并预留确认、修改和拒绝按钮。
待办：周五前补充真实妙记样例。
待办：整理任务映射字段。
开放问题：测试群是否已经配置机器人？
""",
        ),
        "missing_due": DemoSample(
            sample_id="missing_due",
            topic="M4 缺截止时间样例",
            raw_text="""
会议总结
决策：任务创建必须继续经过 AgentPolicy。
待办：请赵六整理任务创建参数。
待办：钱七明天跟进。
问题：是否需要扩展 task_mappings 表字段？
""",
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
