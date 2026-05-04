from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/card_preview_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cards.post_meeting import build_pending_action_item_button_card
from core import EvidenceRef, MeetingBrief, MeetingBriefItem, Resource, render_pre_meeting_card_payload
from core.post_meeting import (
    PostMeetingInput,
    build_post_meeting_artifacts_from_input,
    build_post_meeting_related_resource_query_plan,
)


def parse_args() -> argparse.Namespace:
    """解析卡片预览脚本参数。"""

    parser = argparse.ArgumentParser(
        description="本地预览 M3/M4 MeetFlow 卡片 JSON；不读取飞书、不发送消息、不创建任务。"
    )
    parser.add_argument(
        "--workflow",
        choices=["m3", "m4", "both"],
        default="both",
        help="选择要生成的卡片；默认同时生成 M3 和 M4。",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="可选：把卡片 JSON 写入目录，例如 storage/reports/card_preview。",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="在终端打印完整卡片 JSON；默认只打印摘要，避免输出过长。",
    )
    return parser.parse_args()


def main() -> int:
    """生成本地卡片预览。"""

    args = parse_args()
    previews: dict[str, Any] = {}
    if args.workflow in {"m3", "both"}:
        previews["m3_pre_meeting"] = build_m3_preview()
    if args.workflow in {"m4", "both"}:
        previews["m4_post_meeting"] = build_m4_preview()

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir:
        write_preview_files(output_dir, previews)

    summary = {
        "workflow": args.workflow,
        "output_dir": str(output_dir) if output_dir else "",
        "cards": summarize_previews(previews),
    }
    if args.print_json:
        summary["preview_json"] = previews
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_m3_preview() -> dict[str, Any]:
    """构造 M3 会前卡片预览数据。"""

    evidence = EvidenceRef(
        source_type="docx",
        source_id="docx_m3_preview",
        source_url="https://example.feishu.cn/docx/m3-preview",
        snippet="M3 会前卡片固定展示主题、摘要、结论、问题、风险、待读资料和证据引用。",
        updated_at="2026-05-04",
    )
    brief = MeetingBrief(
        meeting_id="meeting_m3_preview",
        calendar_event_id="event_m3_preview",
        project_id="meetflow",
        topic="MeetFlow M3 会前知识卡片评审",
        summary="建议重点检查统一卡片骨架、证据引用位置和资料链接是否稳定。",
        last_decisions=[
            MeetingBriefItem(
                title="卡片外壳收口到 cards.layout",
                content="M3/M4 统一 header、config 和分隔线结构。",
                evidence_refs=[evidence],
                confidence=0.9,
            )
        ],
        current_questions=[
            MeetingBriefItem(
                title="是否需要把预览 JSON 纳入演示材料",
                content="本地脚本已能稳定生成卡片 JSON，可用于答辩截图或回归检查。",
                evidence_refs=[evidence],
                confidence=0.78,
            )
        ],
        risks=[
            MeetingBriefItem(
                title="模型自由组织 facts 导致卡片漂移",
                content="卡片模板层继续保留固定区块，LLM 只提供结构化内容。",
                evidence_refs=[evidence],
                confidence=0.82,
            )
        ],
        must_read_resources=[
            MeetingBriefItem(
                title="M3/M4 卡片格式优化记录",
                content="关注卡片 layout helper 和发送工具 fallback 之间的边界。",
                evidence_refs=[evidence],
                confidence=0.86,
            )
        ],
        possible_related_resources=[
            MeetingBriefItem(
                title="RAGFlow 设计阅读笔记",
                content="可对比 evidence pack、chunk 元数据和 reranker 设计。",
                evidence_refs=[evidence],
                confidence=0.7,
            )
        ],
        evidence_refs=[evidence],
        confidence=0.84,
    )
    payload = render_pre_meeting_card_payload(brief)
    return {
        "payload": payload.to_dict(),
        "card": payload.card,
    }


def build_m4_preview() -> dict[str, Any]:
    """构造 M4 会后卡片预览数据。"""

    workflow_input = PostMeetingInput(
        meeting_id="meeting_m4_preview",
        calendar_event_id="event_m4_preview",
        minute_token="minute_m4_preview",
        project_id="meetflow",
        topic="MeetFlow M4 会后任务闭环评审",
        source_type="minute",
        source_id="minute_m4_preview",
        source_url="https://example.feishu.cn/minutes/m4-preview",
        raw_text="""
# 会议总结
结论：统一卡片骨架后，M3/M4 的 header、config 和 body padding 应保持稳定。
决策：M4 RAG query 采用 query plan，保留关键词来源和被过滤噪声。
待办：李四周五前验证 M3/M4 卡片 JSON 快照。
待办：整理 MeetFlow RAG query 优化说明。
开放问题：是否需要把 query_plan 写入正式联调报告？
""",
        related_resources=[
            Resource(
                resource_id="doc_m4_preview",
                resource_type="docx",
                title="MeetFlow 卡片与 RAG 优化设计",
                content="记录 M3/M4 卡片基础格式、M4 query plan 和联调验证方式。",
                source_url="https://example.feishu.cn/docx/m4-preview",
                updated_at="2026-05-04",
            )
        ],
    )
    artifacts = build_post_meeting_artifacts_from_input(workflow_input)
    query_plan = build_post_meeting_related_resource_query_plan(artifacts)
    artifacts.extra["related_knowledge_query"] = query_plan.query
    artifacts.extra["related_knowledge_query_plan"] = query_plan.to_dict()
    first_pending = artifacts.pending_action_items[0] if artifacts.pending_action_items else None
    pending_button_card = (
        build_pending_action_item_button_card(artifacts, first_pending, mode="review")
        if first_pending
        else {}
    )
    return {
        "query_plan": query_plan.to_dict(),
        "summary_card": artifacts.card_payloads["summary_card"],
        "pending_card": artifacts.card_payloads["pending_card"],
        "pending_button_card": pending_button_card,
    }


def write_preview_files(output_dir: Path, previews: dict[str, Any]) -> None:
    """把每张卡片写成独立 JSON，便于人工查看和 diff。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    for workflow_key, preview in previews.items():
        workflow_dir = output_dir / workflow_key
        workflow_dir.mkdir(parents=True, exist_ok=True)
        for name, value in flatten_preview_cards(preview).items():
            path = workflow_dir / f"{name}.json"
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def flatten_preview_cards(preview: dict[str, Any]) -> dict[str, Any]:
    """提取适合写文件的卡片或辅助 JSON。"""

    flattened: dict[str, Any] = {}
    for key, value in preview.items():
        if isinstance(value, dict):
            flattened[key] = value
    return flattened


def summarize_previews(previews: dict[str, Any]) -> dict[str, Any]:
    """生成终端友好的卡片摘要。"""

    summary: dict[str, Any] = {}
    for workflow_key, preview in previews.items():
        cards = flatten_preview_cards(preview)
        summary[workflow_key] = {
            name: summarize_card(value)
            for name, value in cards.items()
            if is_card_like(value) or name.endswith("plan")
        }
    return summary


def summarize_card(card: dict[str, Any]) -> dict[str, Any]:
    """抽取卡片标题、颜色和元素数量。"""

    if "query" in card and "terms" in card:
        return {
            "query": card.get("query", ""),
            "terms": card.get("terms", []),
            "dropped_terms": card.get("dropped_terms", []),
        }
    header = card.get("header", {}) if isinstance(card, dict) else {}
    title = header.get("title", {}) if isinstance(header, dict) else {}
    return {
        "schema": card.get("schema", "1.0"),
        "title": title.get("content", ""),
        "template": header.get("template", ""),
        "element_count": count_card_elements(card),
    }


def is_card_like(value: dict[str, Any]) -> bool:
    """判断一个 dict 是否像飞书卡片。"""

    return "header" in value or "elements" in value or "body" in value


def count_card_elements(card: dict[str, Any]) -> int:
    """兼容旧版 elements 和新版 schema 2.0 body.elements 计数。"""

    elements = card.get("elements")
    if isinstance(elements, list):
        return len(elements)
    body = card.get("body")
    if isinstance(body, dict) and isinstance(body.get("elements"), list):
        return len(body["elements"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
