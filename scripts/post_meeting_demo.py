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
from core.post_meeting import (
    CleanedTranscript,
    PostMeetingInput,
    build_post_meeting_artifacts_from_input,
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
    artifacts = build_post_meeting_artifacts_from_input(workflow_input)
    summary_card = build_post_meeting_summary_card(artifacts)
    pending_card = build_pending_action_items_card(artifacts)

    report: dict[str, Any] = {
        "sample_id": sample.sample_id,
        "topic": sample.topic,
        "cleaned": summarize_cleaned_transcript(artifacts.cleaned_transcript),
        "review_summary": artifacts.extra.get("review_summary", ""),
        "decisions": [item.to_dict() for item in artifacts.decisions],
        "open_questions": [item.to_dict() for item in artifacts.open_questions],
        "risks": [item.to_dict() for item in artifacts.risks],
        "disagreements": [item.to_dict() for item in artifacts.disagreements],
        "follow_up_suggestions": [item.to_dict() for item in artifacts.follow_up_suggestions],
        "evidence_pack": artifacts.evidence_pack,
        "action_item_owner_groups": artifacts.extra.get("action_item_owner_groups", []),
        "action_items": [item.to_dict() for item in artifacts.action_items],
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
        "d3_review": DemoSample(
            sample_id="d3_review",
            topic="D3 会后结构化复盘样例",
            raw_text="""
# 会议总结
结论：本次确认 OpenClaw 演示主线采用“会前准备 -> 会后复盘 -> 风险巡检”的闭环叙事。
结论：会后总结卡必须从一段摘要升级为结论、开放问题、行动项、风险和建议的结构化复盘卡。
开放问题：完整报告入口是先使用本地 Markdown 报告路径，还是同步生成飞书云文档链接？
开放问题：风险巡检按钮是否在首轮演示中直接触发 M5，还是先展示命令兜底？
待办：李四周五前完成 D3 会后总结卡 JSON 样式走查。
待办：王五下周三前补充真实妙记脱敏样例和截图。
待办：请赵六整理 Evidence Pack 中关键结论对应的妙记片段。
风险：如果真实妙记没有返回 AI 总结、待办或章节，会后卡可能缺少演示素材，需要准备脱敏兜底样例。
风险：风险巡检依赖 M4 任务映射，如果用户没有确认创建任务，M5 演示可能扫不到本轮任务。
争议点：前端倾向于把完整报告入口做成卡片按钮，但是后端认为本地 Markdown 路径不能直接作为飞书可访问链接。
分歧：演示中是否直接发送真实群消息暂未统一，倾向于先只读报告，再在测试群灰度发卡。
""",
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
