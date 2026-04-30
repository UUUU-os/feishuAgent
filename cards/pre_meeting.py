from __future__ import annotations

from typing import Any


def build_pre_meeting_card(brief: Any) -> dict[str, Any]:
    """构造会前背景卡片的飞书 interactive card JSON。

    这个模板服务 T3.7：它不是通用通知卡，而是把会前最需要扫读的
    主题、摘要、上次结论、当前问题、风险、待读资料和证据引用固定成
    稳定版式，方便答辩演示和后续真实推送复用。
    """

    sections = build_pre_meeting_card_sections(brief)
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": build_overview_markdown(brief),
        },
        {"tag": "hr"},
    ]
    for section in sections:
        if not section["items"]:
            continue
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": render_section_markdown(section),
                },
            }
        )
    if getattr(brief, "evidence_refs", None):
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": render_evidence_markdown(brief.evidence_refs),
                },
            ]
        )

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": choose_header_template(brief),
            "title": {
                "tag": "plain_text",
                "content": f"MeetFlow 会前背景卡：{safe_text(getattr(brief, 'topic', ''))}",
            },
        },
        "elements": elements,
    }


def build_pre_meeting_card_sections(brief: Any) -> list[dict[str, Any]]:
    """把 MeetingBrief 分组为卡片区块，保持模板字段稳定。"""

    return [
        {
            "key": "last_decisions",
            "title": "上次结论",
            "empty": "暂无明确结论",
            "items": normalize_card_items(getattr(brief, "last_decisions", [])),
        },
        {
            "key": "current_questions",
            "title": "当前问题",
            "empty": "暂无待确认问题",
            "items": normalize_card_items(getattr(brief, "current_questions", [])),
        },
        {
            "key": "risks",
            "title": "风险点",
            "empty": "暂无显著风险",
            "items": normalize_card_items(getattr(brief, "risks", [])),
        },
        {
            "key": "must_read_resources",
            "title": "待读资料",
            "empty": "暂无必读资料",
            "items": normalize_card_items(getattr(brief, "must_read_resources", [])),
        },
        {
            "key": "possible_related_resources",
            "title": "可能相关资料",
            "empty": "暂无候选资料",
            "items": normalize_card_items(getattr(brief, "possible_related_resources", [])),
        },
    ]


def build_overview_markdown(brief: Any) -> str:
    """构造卡片顶部概览，让用户第一屏看到主题、摘要和可信度。"""

    summary = safe_text(getattr(brief, "summary", "")) or "暂无背景摘要。"
    confidence = float(getattr(brief, "confidence", 0.0) or 0.0)
    status = "需确认" if getattr(brief, "needs_confirmation", False) else "可参考"
    return "\n".join(
        [
            f"**主题**：{safe_text(getattr(brief, 'topic', '')) or '待识别'}",
            f"**状态**：{status}  |  **置信度**：{confidence:.2f}",
            f"**背景摘要**：{summary}",
        ]
    )


def render_section_markdown(section: dict[str, Any]) -> str:
    """把一个卡片区块渲染成 lark_md。"""

    lines = [f"**{section['title']}**"]
    for index, item in enumerate(section["items"][:3], start=1):
        evidence = f" `{item['ref_id']}`" if item.get("ref_id") else ""
        title = render_link(item["title"], item.get("source_url", ""))
        content = f"：{item['content']}" if item.get("content") else ""
        lines.append(f"{index}. {title}{content}{evidence}")
    return "\n".join(lines)


def render_evidence_markdown(evidence_refs: list[Any]) -> str:
    """渲染证据引用列表，保持卡片结论可追溯。"""

    lines = ["**证据引用**"]
    for index, ref in enumerate(evidence_refs[:5], start=1):
        source_type = safe_text(getattr(ref, "source_type", ""))
        source_id = safe_text(getattr(ref, "source_id", ""))
        source_url = safe_text(getattr(ref, "source_url", ""))
        snippet = safe_text(getattr(ref, "snippet", ""))[:80]
        label = source_id or f"ref_{index}"
        linked_label = render_link(f"`{label}`", source_url)
        lines.append(f"- {linked_label} {source_type}：{snippet}")
    return "\n".join(lines)


def normalize_card_items(items: list[Any]) -> list[dict[str, str]]:
    """把 MeetingBriefItem 转成模板可直接消费的轻量结构。"""

    normalized: list[dict[str, str]] = []
    for item in items:
        evidence_refs = list(getattr(item, "evidence_refs", []) or [])
        first_ref = evidence_refs[0] if evidence_refs else None
        normalized.append(
            {
                "title": safe_text(getattr(item, "title", "")),
                "content": safe_text(getattr(item, "content", "")),
                "ref_id": safe_text(getattr(first_ref, "source_id", "")) if first_ref else "",
                "source_url": safe_text(getattr(first_ref, "source_url", "")) if first_ref else "",
            }
        )
    return normalized


def render_link(label: str, url: str) -> str:
    """在有来源 URL 时渲染飞书 Markdown 链接。"""

    clean_label = safe_text(label)
    clean_url = safe_text(url)
    if not clean_label:
        return ""
    if not clean_url:
        return clean_label
    return f"[{clean_label}]({clean_url})"


def choose_header_template(brief: Any) -> str:
    """根据置信度和风险情况选择飞书卡片 header 颜色。"""

    if getattr(brief, "needs_confirmation", False):
        return "orange"
    if getattr(brief, "risks", None):
        return "red"
    confidence = float(getattr(brief, "confidence", 0.0) or 0.0)
    if confidence >= 0.75:
        return "green"
    return "blue"


def safe_text(value: Any) -> str:
    """清洗卡片文本，避免 None 或异常对象进入飞书卡片 JSON。"""

    return str(value or "").strip()
