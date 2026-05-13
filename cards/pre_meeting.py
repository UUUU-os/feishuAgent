from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def build_pre_meeting_card(brief: Any) -> dict[str, Any]:
    """构造会前背景卡片的飞书 interactive card JSON。

    D2 真实联调要求第一屏就是“背景知识卡”：权威会议时间、基于
    RAG/Evidence Pack 整理的核心背景知识、原始资料链接。详细区块仍
    通过 `build_pre_meeting_card_sections()` 保留给报告和 Console。
    """

    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": build_background_card_intro_markdown(brief),
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": render_core_background_markdown(brief),
            },
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": render_original_links_markdown(brief),
            },
        },
    ]
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
                "content": build_pre_meeting_card_title(brief),
            },
        },
        "elements": elements,
    }


def build_pre_meeting_card_title(brief: Any) -> str:
    """生成用户在飞书消息列表里能直接识别的会前背景知识卡标题。"""

    topic = safe_text(getattr(brief, "topic", "")) or "测试会议"
    if topic.lower().startswith("meetflow"):
        return f"{topic} 会前背景知识卡"
    return f"MeetFlow {topic} 会前背景知识卡"


def build_background_card_intro_markdown(brief: Any) -> str:
    """渲染卡片首段，固定展示权威会议时间和一句背景摘要。"""

    meeting_time = format_authoritative_meeting_time(getattr(brief, "meeting_basic_info", {}))
    summary = safe_text(getattr(brief, "summary", "")) or "本次会议背景待补充，建议先查看原始资料。"
    return "\n".join(
        [
            f"**会议时间（权威）**：{meeting_time or '待确认'}",
            summary,
        ]
    )


def render_core_background_markdown(brief: Any) -> str:
    """把 D2 证据整理成“核心背景知识”列表。"""

    lines = ["**核心背景知识**"]
    background_items = build_core_background_knowledge_lines(brief)
    if not background_items:
        lines.append("- 【资料状态】当前证据不足，请先补充会议文档或妙记链接。")
    else:
        lines.extend(f"- {item}" for item in background_items[:4])
    return "\n".join(lines)


def render_original_links_markdown(brief: Any) -> str:
    """渲染原始文档、妙记和证据链接。"""

    lines = ["**原始链接**"]
    links = collect_original_source_links(brief)
    if not links:
        lines.append("- 暂无可打开的原始资料链接")
    else:
        for index, link in enumerate(links[:5], start=1):
            label = "原始资料" if index == 1 else f"原始资料 {index}"
            lines.append(f"- {render_link(label, link)}")
    return "\n".join(lines)


def build_core_background_knowledge_lines(brief: Any) -> list[str]:
    """生成会前卡片最核心的 2-4 条背景知识。

    条目优先来自历史会议、遗留行动项、风险和 RAG 资料，避免把每个
    结构化字段都平铺到飞书卡片里造成错乱。
    """

    lines: list[str] = []
    progress = summarize_items(
        [
            *list(getattr(brief, "last_decisions", []) or []),
            *list(getattr(brief, "current_questions", []) or []),
            *list(getattr(brief, "must_read_resources", []) or []),
        ],
        limit=3,
    )
    if progress:
        lines.append(f"【当前模块进展】{progress}")

    actions = summarize_items(getattr(brief, "open_action_items", []) or [], limit=4)
    if not actions:
        actions = summarize_items(getattr(brief, "pre_meeting_checklist", []) or [], limit=3)
    if actions:
        lines.append(f"【待落地任务】{actions}")

    risks = summarize_items(
        (getattr(brief, "historical_risks", []) or getattr(brief, "risks", []) or []),
        limit=3,
    )
    if risks:
        lines.append(f"【现存风险点】{risks}")

    agenda = summarize_items(getattr(brief, "suggested_agenda", []) or [], limit=3)
    if agenda:
        lines.append(f"【本次建议议题】{agenda}")

    if not lines:
        fallback = safe_text(getattr(brief, "summary", ""))
        if fallback:
            lines.append(f"【会议背景】{fallback}")
    return lines[:4]


def summarize_items(items: list[Any], limit: int = 3) -> str:
    """把 MeetingBriefItem 列表压缩成适合飞书卡片的一句话。"""

    parts: list[str] = []
    for item in items[:limit]:
        title = safe_text(getattr(item, "title", ""))
        content = safe_text(getattr(item, "content", ""))
        text = title
        if content and content != title:
            text = f"{title}：{content}" if title else content
        if text:
            parts.append(text)
    return "、".join(parts)


def format_authoritative_meeting_time(info: dict[str, Any]) -> str:
    """把会议起止时间格式化为卡片要求的权威展示文本。"""

    if not isinstance(info, dict):
        return ""
    timezone_name = safe_text(info.get("timezone")) or "Asia/Shanghai"
    start_text = format_meeting_timestamp(info.get("start_time"), timezone_name)
    end_text = format_meeting_timestamp(info.get("end_time"), timezone_name)
    if start_text and end_text:
        if " " not in start_text or " " not in end_text:
            if start_text == end_text:
                return f"{start_text} 全天 {timezone_name}"
            return f"{start_text}-{end_text} {timezone_name}"
        start_date, start_clock = start_text.split(" ", 1)
        end_date, end_clock = end_text.split(" ", 1)
        if start_date == end_date:
            return f"{start_date} {start_clock}-{end_clock} {timezone_name}"
        return f"{start_text}-{end_text} {timezone_name}"
    return start_text or end_text


def format_meeting_timestamp(value: Any, timezone_name: str) -> str:
    """兼容飞书秒级/毫秒级 timestamp、全天日期和已格式化文本。"""

    raw_value = safe_text(value)
    if not raw_value:
        return ""
    if len(raw_value) == 10 and raw_value[4] == "-" and raw_value[7] == "-":
        return raw_value
    try:
        timestamp = int(raw_value)
    except ValueError:
        return raw_value
    if timestamp > 10_000_000_000:
        timestamp = timestamp // 1000
    try:
        tz = ZoneInfo(timezone_name or "Asia/Shanghai")
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    return datetime.fromtimestamp(timestamp, tz).strftime("%Y-%m-%d %H:%M")


def collect_original_source_links(brief: Any) -> list[str]:
    """收集会前卡片可展示的原始资料链接。"""

    links: list[str] = []
    info = getattr(brief, "meeting_basic_info", {})
    if isinstance(info, dict):
        for key in ("source_url", "url", "link", "doc_url", "minute_url"):
            value = safe_text(info.get(key))
            if value:
                links.append(value)
    for ref in getattr(brief, "evidence_refs", []) or []:
        source_url = safe_text(getattr(ref, "source_url", ""))
        if source_url:
            links.append(source_url)
    for group_name in (
        "must_read_resources",
        "possible_related_resources",
        "last_decisions",
        "current_questions",
        "open_action_items",
        "historical_risks",
        "risks",
    ):
        for item in getattr(brief, group_name, []) or []:
            for ref in getattr(item, "evidence_refs", []) or []:
                source_url = safe_text(getattr(ref, "source_url", ""))
                if source_url:
                    links.append(source_url)
    return unique_preserved_texts(links)


def unique_preserved_texts(values: list[str]) -> list[str]:
    """按出现顺序去重，保证链接展示稳定。"""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = safe_text(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def build_pre_meeting_card_actions(brief: Any) -> dict[str, Any]:
    """构造会前卡片按钮区。

    按钮 value 使用 MeetFlow 自己的稳定协议。飞书回调进入后端后，会被
    解析为 `CardActionInput`，再进入受控 Agent 主链路。
    """

    meeting_id = safe_text(getattr(brief, "meeting_id", ""))
    calendar_event_id = safe_text(getattr(brief, "calendar_event_id", ""))
    return {
        "tag": "action",
        "actions": [
            build_card_action_button(
                text="刷新背景",
                action="refresh_pre_meeting_brief",
                button_type="primary",
                meeting_id=meeting_id,
                calendar_event_id=calendar_event_id,
            ),
            build_card_action_button(
                text="生成待办草案",
                action="create_task_draft",
                button_type="default",
                meeting_id=meeting_id,
                calendar_event_id=calendar_event_id,
            ),
            build_card_action_button(
                text="查看历史",
                action="view_pre_meeting_history",
                button_type="default",
                meeting_id=meeting_id,
                calendar_event_id=calendar_event_id,
            ),
            build_card_action_button(
                text="发给我",
                action="send_summary_to_me",
                button_type="default",
                meeting_id=meeting_id,
                calendar_event_id=calendar_event_id,
            ),
        ],
    }


def build_card_action_button(
    text: str,
    action: str,
    button_type: str,
    meeting_id: str,
    calendar_event_id: str,
) -> dict[str, Any]:
    """构造单个飞书卡片按钮，避免模板里散落 action value 字段。"""

    return {
        "tag": "button",
        "text": {
            "tag": "plain_text",
            "content": text,
        },
        "type": button_type,
        "value": {
            "action": action,
            "workflow_type": "pre_meeting_brief",
            "meeting_id": meeting_id,
            "calendar_event_id": calendar_event_id,
            "source_card": "pre_meeting_brief",
        },
    }


def build_pre_meeting_card_sections(brief: Any) -> list[dict[str, Any]]:
    """把 MeetingBrief 分组为卡片区块，保持模板字段稳定。"""

    return [
        {
            "key": "meeting_basic_info",
            "title": "会议基本信息",
            "empty": "暂无会议信息",
            "items": normalize_basic_info_items(getattr(brief, "meeting_basic_info", {})),
        },
        {
            "key": "last_decisions",
            "title": "上次结论",
            "empty": "暂无明确结论",
            "items": normalize_card_items(getattr(brief, "last_decisions", [])),
        },
        {
            "key": "open_action_items",
            "title": "遗留行动项",
            "empty": "暂无遗留行动项",
            "items": normalize_card_items(getattr(brief, "open_action_items", [])),
        },
        {
            "key": "current_questions",
            "title": "当前问题",
            "empty": "暂无待确认问题",
            "items": normalize_card_items(getattr(brief, "current_questions", [])),
        },
        {
            "key": "risks",
            "title": "历史风险",
            "empty": "暂无显著风险",
            "items": normalize_card_items(getattr(brief, "historical_risks", []) or getattr(brief, "risks", [])),
        },
        {
            "key": "suggested_agenda",
            "title": "本次建议议题",
            "empty": "暂无建议议题",
            "items": normalize_card_items(getattr(brief, "suggested_agenda", [])),
        },
        {
            "key": "pre_meeting_checklist",
            "title": "会前 Checklist",
            "empty": "暂无 checklist",
            "items": normalize_card_items(getattr(brief, "pre_meeting_checklist", [])),
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
        {
            "key": "evidence_pack",
            "title": "Evidence Pack",
            "empty": "暂无证据包",
            "items": normalize_evidence_pack_items(getattr(brief, "evidence_pack", {}), getattr(brief, "evidence_refs", [])),
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


def normalize_basic_info_items(info: dict[str, Any]) -> list[dict[str, str]]:
    """把会议基本信息渲染为卡片条目。"""

    if not isinstance(info, dict) or not info:
        return []
    participants = info.get("participants") if isinstance(info.get("participants"), list) else []
    time_range = " - ".join(
        item for item in [safe_text(info.get("start_time")), safe_text(info.get("end_time"))] if item
    )
    rows = [
        ("会议标题", safe_text(info.get("title"))),
        ("会议时间", time_range),
        ("组织者", safe_text(info.get("organizer"))),
        ("参会人", "、".join(safe_text(item) for item in participants[:6] if safe_text(item))),
        ("会议来源", safe_text(info.get("source"))),
    ]
    return [
        {"title": title, "content": value, "ref_id": "", "source_url": ""}
        for title, value in rows
        if value
    ]


def normalize_evidence_pack_items(evidence_pack: dict[str, Any], evidence_refs: list[Any]) -> list[dict[str, str]]:
    """把 D2 Evidence Pack 压缩成卡片底部证据条目。"""

    items: list[dict[str, str]] = []
    if isinstance(evidence_pack, dict):
        reason = safe_text(evidence_pack.get("reason"))
        confidence = evidence_pack.get("confidence")
        if reason:
            items.append(
                {
                    "title": "证据汇聚",
                    "content": f"{reason}；置信度 {float(confidence or 0.0):.2f}",
                    "ref_id": "",
                    "source_url": "",
                }
            )
    for ref in evidence_refs[:5]:
        source_type = safe_text(getattr(ref, "source_type", ""))
        source_id = safe_text(getattr(ref, "source_id", ""))
        snippet = safe_text(getattr(ref, "snippet", ""))[:80]
        items.append(
            {
                "title": source_id or source_type or "evidence",
                "content": f"{source_type}：{snippet}" if source_type else snippet,
                "ref_id": source_id,
                "source_url": safe_text(getattr(ref, "source_url", "")),
            }
        )
    return items[:5]


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
