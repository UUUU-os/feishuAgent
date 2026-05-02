from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from cards.post_meeting import build_pending_action_items_card, build_post_meeting_summary_card
from core.models import ActionItem, BaseModel, EvidenceRef, MeetingSummary, Resource, WorkflowContext


NOISE_LINE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^本次会议由.*(转写|生成)",
        r"^以下内容由.*(智能|AI).*生成",
        r"^会议录制已开始",
        r"^会议录制已结束",
        r"^正在为你生成.*纪要",
        r"^点击.*查看.*完整",
    ]
]

SECTION_TITLE_PATTERNS = [
    re.compile(r"^#{1,6}\s*(?P<title>.+)$"),
    re.compile(r"^(?P<title>(会议纪要|会议总结|关键结论|结论|决策|待办|待办事项|行动项|Action Items?|TODO|开放问题|风险|阻塞|讨论))[:：]?$", re.IGNORECASE),
]

SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "action_item": ("待办", "行动项", "action item", "todo", "跟进", "负责", "完成", "推进", "整理", "补充", "发送", "分享"),
    "owner": ("负责人", "owner", "由", "请", "麻烦", "我来", "你来"),
    "due_date": ("截止", "deadline", "ddl", "今天", "明天", "后天", "周一", "周二", "周三", "周四", "周五", "周六", "周日", "本周", "下周", "月底", "前"),
    "decision": ("决定", "决策", "结论", "确定", "达成一致", "采用", "先按"),
    "open_question": ("问题", "待确认", "是否", "能否", "需要确认", "还不确定", "?"),
}

OWNER_PATTERNS = [
    re.compile(r"@(?P<owner>[\u4e00-\u9fa5A-Za-z0-9_ -]{2,20})"),
    re.compile(r"(?:负责人|owner)[:：]\s*(?P<owner>[^,，；;\s]+)", re.IGNORECASE),
    re.compile(r"由\s*(?P<owner>[^,，；;\s]+?)\s*(?:负责|跟进|推进|完成)"),
    re.compile(r"(?:请|麻烦)\s*(?P<owner>[^,，；;\s]+?)\s*(?:负责|跟进|推进|完成|整理|补充)"),
    re.compile(r"^(?P<owner>[\u4e00-\u9fa5]{2,4})(?=今天|明天|后天|本周|下周|周[一二三四五六日天]|月底|\d{1,2}[/-]\d{1,2})"),
    re.compile(r"^(?P<owner>[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9_]{0,10})\s*(?:今天|明天|后天|本周|下周|周[一二三四五六日天]|月底|\d{1,2}[/-]\d{1,2})"),
]

DUE_DATE_PATTERNS = [
    re.compile(r"(?P<due>今天或最晚明天)"),
    re.compile(r"(?P<due>今天到明天)"),
    re.compile(r"(?P<due>今天或明天)"),
    re.compile(r"(?P<due>最晚明天)"),
    re.compile(r"(?:截止|deadline|ddl)[:：]?\s*(?P<due>[^,，；;。]*?前)", re.IGNORECASE),
    re.compile(r"(?:截止|deadline|ddl)[:：]?\s*(?P<due>今天|明天|后天|本周|下周|周[一二三四五六日天]|月底)", re.IGNORECASE),
    re.compile(r"(?P<due>(?:今天|明天|后天|本周|下周|周[一二三四五六日天]|月底)[^,，；;。]*?前)"),
    re.compile(r"(?P<due>今天|明天|后天|本周|下周|周[一二三四五六日天]|月底)"),
    re.compile(r"(?P<due>20\d{2}[/-]\d{1,2}[/-]\d{1,2})"),
    re.compile(r"(?P<due>\d{1,2}[/-]\d{1,2})"),
]

MIN_ACTION_ITEM_CONFIDENCE = 0.75

AMBIGUOUS_ACTION_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"^(看一下|跟进一下|处理一下|确认一下|优化一下|推进一下)$",
        r"^(继续)?(跟进|处理|推进|优化|确认)$",
        r"^(相关|这个|那个|问题|事项)$",
    ]
]


@dataclass(slots=True)
class PostMeetingInput(BaseModel):
    """会后工作流的确定性输入模型。

    M4 的输入可能来自妙记 ready 事件、手工粘贴的纪要文本或后续工具读取结果。
    这里先把会议、项目、来源链接和原始文本收拢成稳定结构，避免后续清洗、
    抽取和卡片渲染反复解析飞书 payload。
    """

    meeting_id: str
    calendar_event_id: str
    minute_token: str
    project_id: str
    topic: str = ""
    source_type: str = ""
    source_id: str = ""
    source_url: str = ""
    raw_text: str = ""
    participants: list[dict[str, Any]] = field(default_factory=list)
    related_resources: list[Resource] = field(default_factory=list)
    memory_snapshot: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TranscriptSection(BaseModel):
    """清洗后纪要中的一个章节。

    章节用于保留“讨论背景 / 决策 / 待办”等语义分段。后续规则抽取或 LLM
    辅助抽取可以利用章节标题和行号，降低把结论误判为任务的概率。
    """

    title: str
    lines: list[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0
    signal_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CleanedTranscript(BaseModel):
    """会后纪要清洗结果。

    T4.2 只定义契约，不做清洗实现。后续 T4.3 会填充 `cleaned_text`、
    `sections` 和 `signal_lines`，同时保留 `raw_text` 便于证据回溯。
    """

    raw_text: str
    cleaned_text: str = ""
    lines: list[str] = field(default_factory=list)
    sections: list[TranscriptSection] = field(default_factory=list)
    signal_lines: list[dict[str, Any]] = field(default_factory=list)
    source_type: str = ""
    source_id: str = ""
    source_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedDecision(BaseModel):
    """从纪要中抽取出的会议决策。

    决策表示已经达成的结论，不等同于待办。单独建模是为了防止后续任务创建
    阶段把“决定采用某方案”误写成飞书任务。
    """

    decision_id: str
    content: str
    confidence: float = 0.0
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    source_line: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedOpenQuestion(BaseModel):
    """从纪要中抽取出的开放问题。

    开放问题用于表达仍需确认的事项。它可以出现在会后卡片里，但首版不会
    自动分配负责人或直接创建任务。
    """

    question_id: str
    content: str
    confidence: float = 0.0
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    source_line: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PostMeetingArtifacts(BaseModel):
    """M4 会后工作流的最终产物集合。

    这个对象把输入、清洗纪要、结构化总结、待确认任务和卡片 payload 预留在
    同一契约里。后续每个 T4.x 任务只填充自己负责的部分，写任务仍必须经过
    ToolRegistry 和 AgentPolicy。
    """

    workflow_input: PostMeetingInput
    cleaned_transcript: CleanedTranscript
    meeting_summary: MeetingSummary
    decisions: list[ExtractedDecision] = field(default_factory=list)
    open_questions: list[ExtractedOpenQuestion] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    pending_action_items: list[ActionItem] = field(default_factory=list)
    created_task_mappings: list[dict[str, Any]] = field(default_factory=list)
    card_payloads: dict[str, Any] = field(default_factory=dict)
    stage_plan: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def clean_meeting_transcript(raw_text: str) -> CleanedTranscript:
    """清洗原始会议纪要文本。

    这一步只做确定性文本整理：去噪、去空行、合并多余空白、切章节和标记强
    信号行。它不会总结语义，也不会抽取或创建 Action Item，避免 T4.3 提前
    越界到后续任务。
    """

    normalized_lines: list[str] = []
    dropped_count = 0
    seen_lines: set[str] = set()
    for raw_line in raw_text.splitlines():
        line = normalize_transcript_line(raw_line)
        if not line:
            dropped_count += 1
            continue
        # 妙记导出偶尔会重复同一条系统行或标题行；连续重复对证据没有价值。
        if normalized_lines and normalized_lines[-1] == line:
            dropped_count += 1
            continue
        duplicate_key = line.casefold()
        if is_low_value_duplicate(line) and duplicate_key in seen_lines:
            dropped_count += 1
            continue
        seen_lines.add(duplicate_key)
        normalized_lines.append(line)

    signal_lines = build_signal_lines(normalized_lines)
    sections = split_transcript_sections(normalized_lines)
    return CleanedTranscript(
        raw_text=raw_text,
        cleaned_text="\n".join(normalized_lines),
        lines=normalized_lines,
        sections=sections,
        signal_lines=signal_lines,
        extra={
            "raw_line_count": len(raw_text.splitlines()),
            "cleaned_line_count": len(normalized_lines),
            "dropped_line_count": dropped_count,
        },
    )


def normalize_transcript_line(line: str) -> str:
    """规范化单行纪要文本。

    保留说话人、时间戳和章节标题，因为这些信息后续会作为证据定位。这里只
    删除空白、常见列表符号和明显的系统噪声。
    """

    normalized = line.replace("\ufeff", "").replace("\u3000", " ").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"^[\-*•·]\s+", "", normalized)
    normalized = re.sub(r"^\[\s*\]\s+", "", normalized)
    normalized = normalized.strip()
    if not normalized:
        return ""
    if any(pattern.search(normalized) for pattern in NOISE_LINE_PATTERNS):
        return ""
    return normalized


def split_transcript_sections(cleaned_lines: list[str]) -> list[TranscriptSection]:
    """把清洗后的行切成章节。

    首版按显式标题和强语义标题分段。没有标题时放入“正文”章节，保证后续
    抽取逻辑始终能拿到稳定的章节结构。
    """

    sections: list[TranscriptSection] = []
    current_title = "正文"
    current_lines: list[str] = []
    current_start = 1

    for index, line in enumerate(cleaned_lines, start=1):
        title = extract_section_title(line)
        if title:
            if current_lines or sections:
                sections.append(
                    build_transcript_section(
                        title=current_title,
                        lines=current_lines,
                        start_line=current_start,
                        end_line=index - 1,
                    )
                )
            current_title = title
            current_lines = []
            current_start = index + 1
            continue
        if not current_lines:
            current_start = index
        current_lines.append(line)

    if current_lines or not sections:
        sections.append(
            build_transcript_section(
                title=current_title,
                lines=current_lines,
                start_line=current_start if cleaned_lines else 0,
                end_line=len(cleaned_lines),
            )
        )
    return sections


def build_signal_lines(cleaned_lines: list[str]) -> list[dict[str, Any]]:
    """标记包含待办、负责人、截止时间等强信号的行。"""

    signal_lines: list[dict[str, Any]] = []
    for index, line in enumerate(cleaned_lines, start=1):
        tags = detect_signal_tags(line)
        if tags:
            signal_lines.append({"line_no": index, "text": line, "signal_tags": tags})
    return signal_lines


def detect_signal_tags(line: str) -> list[str]:
    """识别一行纪要中对后续抽取有价值的业务信号。"""

    lowered = line.casefold()
    tags: list[str] = []
    for tag, keywords in SIGNAL_KEYWORDS.items():
        if any(keyword.casefold() in lowered for keyword in keywords):
            tags.append(tag)
    if re.search(r"\d{1,2}[/-]\d{1,2}|20\d{2}[/-]\d{1,2}[/-]\d{1,2}", line):
        tags.append("due_date")
    return unique_non_empty(tags)


def extract_section_title(line: str) -> str:
    """从单行文本中识别章节标题。"""

    clean_line = line.strip()
    for pattern in SECTION_TITLE_PATTERNS:
        match = pattern.match(clean_line)
        if match:
            return match.group("title").strip(" ：:")
    return ""


def build_transcript_section(
    title: str,
    lines: list[str],
    start_line: int,
    end_line: int,
) -> TranscriptSection:
    """构造章节对象，并汇总章节内出现过的信号标签。"""

    signal_tags: list[str] = []
    for line in lines:
        signal_tags.extend(detect_signal_tags(line))
    return TranscriptSection(
        title=title,
        lines=list(lines),
        start_line=start_line,
        end_line=end_line,
        signal_tags=unique_non_empty(signal_tags),
    )


def is_low_value_duplicate(line: str) -> bool:
    """判断重复出现时可以丢弃的低价值行。

    人工发言重复可能是重要强调，因此这里只丢弃标题类和系统类短文本。
    """

    return len(line) <= 20 and bool(extract_section_title(line))


def extract_action_items(
    cleaned_transcript: CleanedTranscript,
    meeting_id: str = "",
    source_url: str = "",
) -> list[ActionItem]:
    """从清洗后的纪要中规则抽取行动项。

    首版只处理强信号行，保留负责人和截止时间的文本候选，不解析 open_id。
    缺关键字段时先设置 `needs_confirm=True`，真正能否写入仍留给后续
    AgentPolicy 判断。
    """

    candidates: list[ActionItem] = []
    seen_keys: set[str] = set()
    for line_no, line, tags in iter_action_item_candidate_lines(cleaned_transcript):
        if not should_extract_action_item(line, tags):
            continue
        item = build_action_item_from_line(
            line=line,
            context={
                "meeting_id": meeting_id,
                "source_url": source_url or cleaned_transcript.source_url,
                "source_id": cleaned_transcript.source_id,
                "source_type": cleaned_transcript.source_type,
                "line_no": line_no,
                "signal_tags": tags,
            },
        )
        if not item:
            continue
        dedupe_key = f"{item.title}|{item.owner}|{item.due_date}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        candidates.append(item)
    return candidates


def iter_action_item_candidate_lines(cleaned_transcript: CleanedTranscript) -> list[tuple[int, str, list[str]]]:
    """枚举行动项候选行。

    真实妙记的 AI 总结里经常出现“负责、推进、完成”等普通叙述。为了避免
    误建任务，首选“待办 / 行动项 / TODO”章节中的内容，其次才接受显式以
    待办关键词开头的行。
    """

    candidates: list[tuple[int, str, list[str]]] = []
    seen: set[int] = set()
    for section in cleaned_transcript.sections:
        if not is_action_section(section.title):
            continue
        for offset, line in enumerate(section.lines):
            line_no = section.start_line + offset
            if line_no in seen:
                continue
            seen.add(line_no)
            tags = unique_non_empty([*detect_signal_tags(line), "action_item"])
            candidates.append((line_no, line, tags))

    for signal in cleaned_transcript.signal_lines:
        line_no = int(signal.get("line_no") or 0)
        line = str(signal.get("text") or "")
        if line_no in seen:
            continue
        if not has_explicit_action_prefix(line):
            continue
        seen.add(line_no)
        tags = [str(tag) for tag in signal.get("signal_tags", [])]
        candidates.append((line_no, line, tags))
    return candidates


def is_action_section(title: str) -> bool:
    """判断章节是否是明确的待办区域。"""

    normalized = title.casefold()
    return any(keyword in normalized for keyword in ("待办", "行动项", "action item", "todo"))


def has_explicit_action_prefix(line: str) -> bool:
    """判断行本身是否带有明确待办前缀。"""

    return bool(re.match(r"^(?:待办|行动项|Action Items?|TODO|负责人)[:：]", line.strip(), flags=re.IGNORECASE))


def build_action_item_from_line(line: str, context: dict[str, Any]) -> ActionItem | None:
    """把单行纪要转换为 `ActionItem` 草案。

    这里的 `owner` 是纪要中的负责人文本，不是飞书 open_id。后续真实创建任务
    前必须通过通讯录工具解析，不能把这个字段当作 assignee_ids 使用。
    """

    title = normalize_action_title(line)
    if not title:
        return None
    owner = extract_owner_candidate(line)
    due_date = extract_due_date_candidate(line)
    evidence_ref = build_evidence_ref(
        source_type=str(context.get("source_type") or "minute"),
        source_id=str(context.get("source_id") or context.get("meeting_id") or "post_meeting"),
        source_url=str(context.get("source_url") or ""),
        snippet=line,
    )
    missing_fields = []
    if not owner:
        missing_fields.append("owner")
    if not due_date:
        missing_fields.append("due_date")
    needs_confirm = bool(missing_fields)
    confidence = 0.82 if not needs_confirm else 0.58
    item_id = stable_id("action", str(context.get("meeting_id") or ""), line)
    action_item = ActionItem(
        item_id=item_id,
        title=title,
        owner=owner,
        due_date=due_date,
        priority=infer_priority(line),
        confidence=confidence,
        needs_confirm=needs_confirm,
        evidence_refs=[evidence_ref],
        extra={
            "source_line": int(context.get("line_no") or 0),
            "signal_tags": list(context.get("signal_tags") or []),
            "meeting_id": str(context.get("meeting_id") or ""),
            "source_id": str(context.get("source_id") or ""),
            "source_type": str(context.get("source_type") or ""),
            "owner_resolution_required": bool(owner),
            "missing_fields": missing_fields,
            "confirm_reason": "、".join(f"缺少{field_label(field)}" for field in missing_fields),
        },
    )
    return mark_action_item_confirmation_state(action_item)


def evaluate_action_item_confidence(action_item: ActionItem) -> float:
    """评估行动项是否足够清晰，能进入字段完整候选。

    这是 M4 的业务侧预判，只负责给抽取结果打分和标记风险；任务创建仍
    必须先经过人工确认，再经过 `AgentPolicy.authorize_tool_call()`。
    """

    score = 0.95
    if not action_item.title.strip():
        score -= 0.35
    if is_semantically_ambiguous_title(action_item.title):
        score -= 0.25
    if not action_item.owner.strip():
        score -= 0.2
    elif is_group_owner_candidate(action_item.owner):
        score -= 0.15
    if not action_item.due_date.strip():
        score -= 0.2
    if not action_item.evidence_refs:
        score -= 0.2
    if action_item.extra.get("missing_fields"):
        score -= 0.05 * len(action_item.extra.get("missing_fields", []))
    return max(0.0, min(1.0, round(score, 2)))


def mark_action_item_confirmation_state(action_item: ActionItem) -> ActionItem:
    """根据字段完整性、语义清晰度和证据情况标记待确认状态。"""

    confidence = evaluate_action_item_confidence(action_item)
    missing_fields = build_missing_action_item_fields(action_item)
    confirm_reasons = build_confirmation_reasons(action_item, confidence, missing_fields)
    action_item.confidence = confidence
    action_item.needs_confirm = bool(confirm_reasons)
    action_item.extra["missing_fields"] = missing_fields
    action_item.extra["confirm_reason"] = build_confirmation_reason(action_item)
    action_item.extra["confidence_threshold"] = MIN_ACTION_ITEM_CONFIDENCE
    action_item.extra["auto_create_candidate"] = not action_item.needs_confirm
    action_item.extra["task_creation_requires_human_confirmation"] = True
    return action_item


def build_confirmation_reason(action_item: ActionItem) -> str:
    """生成待确认原因，供卡片和人工复核展示。"""

    missing_fields = [str(item) for item in action_item.extra.get("missing_fields", [])]
    reasons = build_confirmation_reasons(action_item, action_item.confidence, missing_fields)
    return "；".join(reasons)


def build_missing_action_item_fields(action_item: ActionItem) -> list[str]:
    """计算行动项缺失的关键字段。"""

    missing_fields: list[str] = []
    if not action_item.title.strip():
        missing_fields.append("title")
    if not action_item.owner.strip():
        missing_fields.append("owner")
    elif is_group_owner_candidate(action_item.owner):
        missing_fields.append("owner_resolution")
    if not action_item.due_date.strip():
        missing_fields.append("due_date")
    if not action_item.evidence_refs:
        missing_fields.append("evidence_refs")
    return missing_fields


def is_group_owner_candidate(owner: str) -> bool:
    """判断负责人是否是群体称呼，不能直接解析成单个飞书 open_id。"""

    normalized = owner.strip()
    return normalized in {"所有参赛同学", "全体参赛同学", "所有人", "大家", "全员", "成员"}


def build_confirmation_reasons(
    action_item: ActionItem,
    confidence: float,
    missing_fields: list[str],
) -> list[str]:
    """汇总导致任务进入待确认的业务原因。"""

    reasons = [f"缺少{field_label(field)}" for field in missing_fields]
    if action_item.title and is_semantically_ambiguous_title(action_item.title):
        reasons.append("语义不明确")
    if confidence < MIN_ACTION_ITEM_CONFIDENCE:
        reasons.append(f"置信度低于阈值 {MIN_ACTION_ITEM_CONFIDENCE:.2f}")
    return unique_non_empty(reasons)


def is_semantically_ambiguous_title(title: str) -> bool:
    """判断任务标题是否过于模糊，无法直接落地。"""

    normalized = title.strip(" ，,；;。")
    if len(normalized) < 4:
        return True
    return any(pattern.match(normalized) for pattern in AMBIGUOUS_ACTION_PATTERNS)


def extract_decisions(
    cleaned_transcript: CleanedTranscript,
    meeting_id: str = "",
    source_url: str = "",
) -> list[ExtractedDecision]:
    """从纪要中抽取已经达成的会议决策。"""

    decisions: list[ExtractedDecision] = []
    seen: set[str] = set()
    for signal in cleaned_transcript.signal_lines:
        line = str(signal.get("text") or "")
        tags = [str(tag) for tag in signal.get("signal_tags", [])]
        if "decision" not in tags or should_extract_action_item(line, tags):
            continue
        if is_heading_like_line(line):
            continue
        content = normalize_decision_content(line)
        if not content or content in seen:
            continue
        seen.add(content)
        source_line = int(signal.get("line_no") or 0)
        decisions.append(
            ExtractedDecision(
                decision_id=stable_id("decision", meeting_id, line),
                content=content,
                confidence=0.78,
                evidence_refs=[
                    build_evidence_ref(
                        source_type=cleaned_transcript.source_type or "minute",
                        source_id=cleaned_transcript.source_id or meeting_id or "post_meeting",
                        source_url=source_url or cleaned_transcript.source_url,
                        snippet=line,
                    )
                ],
                source_line=source_line,
                extra={"signal_tags": tags},
            )
        )
    return decisions


def extract_open_questions(
    cleaned_transcript: CleanedTranscript,
    meeting_id: str = "",
    source_url: str = "",
) -> list[ExtractedOpenQuestion]:
    """从纪要中抽取仍需确认的开放问题。"""

    questions: list[ExtractedOpenQuestion] = []
    seen: set[str] = set()
    for signal in cleaned_transcript.signal_lines:
        line = str(signal.get("text") or "")
        tags = [str(tag) for tag in signal.get("signal_tags", [])]
        if "open_question" not in tags or "decision" in tags or should_extract_action_item(line, tags):
            continue
        if not should_extract_open_question_line(line, tags):
            continue
        content = normalize_open_question_content(line)
        if not content or content in seen:
            continue
        seen.add(content)
        source_line = int(signal.get("line_no") or 0)
        questions.append(
            ExtractedOpenQuestion(
                question_id=stable_id("question", meeting_id, line),
                content=content,
                confidence=0.76,
                evidence_refs=[
                    build_evidence_ref(
                        source_type=cleaned_transcript.source_type or "minute",
                        source_id=cleaned_transcript.source_id or meeting_id or "post_meeting",
                        source_url=source_url or cleaned_transcript.source_url,
                        snippet=line,
                    )
                ],
                source_line=source_line,
                extra={"signal_tags": tags},
            )
        )
    return questions


def should_extract_open_question_line(line: str, tags: list[str]) -> bool:
    """判断一行是否真的是待解决问题，而不是章节名或普通说明。"""

    stripped = line.strip()
    if is_heading_like_line(stripped):
        return False
    if stripped.endswith(("?", "？")):
        return True
    if re.match(r"^(?:开放问题|待确认)[:：]", stripped):
        return True
    if re.match(r"^(?:问题|风险|阻塞)[:：]", stripped):
        return any(keyword in stripped for keyword in ("是否", "能否", "还不确定", "需要确认", "待确认", "谁", "何时", "怎么"))
    return any(keyword in stripped for keyword in ("是否", "能否", "还不确定", "需要确认", "待确认"))


def is_heading_like_line(line: str) -> bool:
    """过滤妙记 AI 产物中的纯标题，避免误当成决策或开放问题。"""

    stripped = line.strip()
    if re.fullmatch(r"\*\*[^*]{2,40}\*\*", stripped):
        return True
    if re.fullmatch(r"\d+[.、]\s*[^。；;：:]{2,40}", stripped):
        return True
    return False


def build_evidence_ref(
    source_type: str,
    source_id: str,
    source_url: str,
    snippet: str,
    updated_at: str = "",
) -> EvidenceRef:
    """构造 M4 抽取产物的证据引用。"""

    return EvidenceRef(
        source_type=source_type,
        source_id=source_id,
        source_url=source_url,
        snippet=snippet,
        updated_at=updated_at,
    )


def should_extract_action_item(line: str, tags: list[str]) -> bool:
    """判断一行是否应作为行动项候选。"""

    tag_set = set(tags)
    if "open_question" in tag_set and not ({"action_item", "owner", "due_date"} & tag_set):
        return False
    if "decision" in tag_set and not ({"action_item", "owner", "due_date"} & tag_set):
        return False
    if "action_item" in tag_set:
        return True
    return bool({"owner", "due_date"} <= tag_set and not line.strip().endswith("?"))


def normalize_action_title(line: str) -> str:
    """从行动项候选行中提取可读任务标题。"""

    title = line.strip()
    owner = extract_owner_candidate(line)
    due_date = extract_due_date_candidate(line)
    title = re.sub(r"^\d+[.、]\s*", "", title)
    title = re.sub(r"^(?:待办|行动项|Action Items?|TODO)[:：]\s*", "", title, flags=re.IGNORECASE)
    if owner:
        title = re.sub(rf"(?:负责人|owner)[:：]\s*{re.escape(owner)}[,，；;]?\s*", "", title, flags=re.IGNORECASE)
        title = re.sub(rf"\s*@{re.escape(owner)}\s*$", "", title)
        title = re.sub(rf"^(?:由\s*)?{re.escape(owner)}\s*(?:负责|跟进|推进)?", "", title)
    if due_date:
        title = re.sub(rf"(?:截止|deadline|ddl)[:：]?\s*{re.escape(due_date)}[,，；;]?\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^(?:请|麻烦)\s*", "", title)
    title = re.sub(r"由\s*[^,，；;\s]+?\s*(?:负责|跟进|推进)", "", title)
    title = title.strip(" ，,；;。")
    return title[:120]


def normalize_decision_content(line: str) -> str:
    """清理决策行中的标题前缀。"""

    content = re.sub(r"^(?:关键结论|结论|决策)[:：]\s*", "", line.strip())
    return content.strip(" ，,；;。")


def normalize_open_question_content(line: str) -> str:
    """清理开放问题行中的标题前缀。"""

    content = re.sub(r"^(?:开放问题|待确认|问题)[:：]\s*", "", line.strip())
    return content.strip(" ，,；;。")


def extract_owner_candidate(line: str) -> str:
    """从行动项候选行中提取负责人文本。"""

    normalized_line = strip_action_prefix(line)
    for pattern in OWNER_PATTERNS:
        match = pattern.search(normalized_line)
        if match:
            return match.group("owner").strip(" @，,；;。)")
    return ""


def extract_due_date_candidate(line: str) -> str:
    """从行动项候选行中提取截止时间文本。"""

    normalized_line = strip_action_prefix(line)
    for pattern in DUE_DATE_PATTERNS:
        match = pattern.search(normalized_line)
        if match:
            return match.group("due").strip(" ，,；;。")
    return ""


def infer_priority(line: str) -> str:
    """根据纪要措辞给行动项一个保守优先级。"""

    if any(keyword in line for keyword in ("紧急", "高优", "必须", "今天", "明天")):
        return "high"
    if any(keyword in line for keyword in ("低优", "有空", "可选")):
        return "low"
    return "medium"


def stable_id(prefix: str, *parts: str) -> str:
    """为规则抽取结果生成稳定 ID，方便后续去重和映射。"""

    raw = "|".join(part for part in parts if part)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def field_label(field_name: str) -> str:
    """把内部字段名转换为用户可读的中文字段名。"""

    labels = {
        "title": "任务标题",
        "owner": "负责人",
        "owner_resolution": "可解析负责人",
        "due_date": "截止时间",
        "evidence_refs": "证据引用",
    }
    return labels.get(field_name, field_name)


def strip_action_prefix(line: str) -> str:
    """去掉待办类前缀，方便后续规则识别姓名和日期。"""

    return re.sub(r"^(?:待办|行动项|Action Items?|TODO)[:：]\s*", "", line.strip(), flags=re.IGNORECASE)


def build_post_meeting_input_from_context(context: WorkflowContext) -> PostMeetingInput:
    """从通用 `WorkflowContext` 构造 M4 专用输入。

    这里只做字段归一化和来源识别，不访问飞书，也不执行清洗或抽取。这样本地
    demo、Agent 工作流和真实只读联调都可以复用同一份输入契约。
    """

    payload = context.event.payload if context.event else {}
    related_resources = list(context.related_resources)
    text_resource = first_content_resource(related_resources)
    raw_text = first_non_empty(
        payload,
        "raw_text",
        "transcript",
        "transcript_text",
        "minutes_text",
        "minute_text",
        "summary_text",
        "content",
    )
    if not raw_text and text_resource:
        raw_text = text_resource.content

    source_type = first_non_empty(payload, "source_type", "resource_type")
    source_id = first_non_empty(payload, "source_id", "resource_id", "minute_token", "minute")
    source_url = first_non_empty(
        payload,
        "source_url",
        "minute_url",
        "minutes_url",
        "document_url",
        "doc_url",
        "url",
        "app_link",
    )
    if text_resource:
        source_type = source_type or text_resource.resource_type
        source_id = source_id or text_resource.resource_id
        source_url = source_url or text_resource.source_url

    minute_token = context.minute_token or first_non_empty(payload, "minute_token", "minute")
    if minute_token and not source_id:
        source_id = minute_token
    if minute_token and not source_type:
        source_type = "minute"

    return PostMeetingInput(
        meeting_id=context.meeting_id,
        calendar_event_id=context.calendar_event_id,
        minute_token=minute_token,
        project_id=context.project_id,
        topic=first_non_empty(payload, "topic", "summary", "title", "meeting_title"),
        source_type=source_type,
        source_id=source_id,
        source_url=source_url,
        raw_text=raw_text,
        participants=list(context.participants),
        related_resources=related_resources,
        memory_snapshot=dict(context.memory_snapshot),
        raw_payload=dict(payload),
        extra={
            "trace_id": context.trace_id,
            "workflow_type": context.workflow_type,
            "has_raw_text": bool(raw_text),
        },
    )


def build_post_meeting_artifacts(context: WorkflowContext) -> PostMeetingArtifacts:
    """从工作流上下文构造 M4 本地产物。

    这个函数服务 T4.9：它只基于现有上下文里的纪要文本或资源内容做本地清洗、
    抽取和卡片 payload 生成，不主动访问飞书，也不创建任务。
    """

    workflow_input = build_post_meeting_input_from_context(context)
    artifacts = build_post_meeting_artifacts_from_input(workflow_input)
    artifacts.extra["trace_id"] = context.trace_id
    artifacts.extra["workflow_type"] = context.workflow_type
    return artifacts


def build_post_meeting_artifacts_from_input(workflow_input: PostMeetingInput) -> PostMeetingArtifacts:
    """从 M4 输入生成完整的本地产物。"""

    cleaned_transcript = clean_meeting_transcript(workflow_input.raw_text)
    cleaned_transcript.source_type = workflow_input.source_type
    cleaned_transcript.source_id = workflow_input.source_id
    cleaned_transcript.source_url = workflow_input.source_url
    decisions = extract_decisions(
        cleaned_transcript,
        meeting_id=workflow_input.meeting_id,
        source_url=workflow_input.source_url,
    )
    if not decisions:
        decisions = build_fallback_decisions(
            cleaned_transcript,
            meeting_id=workflow_input.meeting_id,
            source_url=workflow_input.source_url,
        )
    open_questions = extract_open_questions(
        cleaned_transcript,
        meeting_id=workflow_input.meeting_id,
        source_url=workflow_input.source_url,
    )
    action_items = extract_action_items(
        cleaned_transcript,
        meeting_id=workflow_input.meeting_id,
        source_url=workflow_input.source_url,
    )
    for item in action_items:
        item.extra["meeting_id"] = workflow_input.meeting_id
        item.extra["calendar_event_id"] = workflow_input.calendar_event_id
        item.extra["minute_token"] = workflow_input.minute_token
        item.extra["project_id"] = workflow_input.project_id
    # 产品策略要求所有会后任务都先进入人工审核。`needs_confirm` 仍保留字段完整性
    # 判断结果，用于解释为什么需要补字段；pending 列表则承载全部待审核任务。
    pending_action_items = list(action_items)
    meeting_summary = MeetingSummary(
        meeting_id=workflow_input.meeting_id,
        project_id=workflow_input.project_id,
        topic=workflow_input.topic,
        decisions=[item.content for item in decisions],
        open_questions=[item.content for item in open_questions],
        action_items=action_items,
        evidence_refs=collect_artifact_evidence(decisions, open_questions, action_items),
    )
    artifacts = PostMeetingArtifacts(
        workflow_input=workflow_input,
        cleaned_transcript=cleaned_transcript,
        meeting_summary=meeting_summary,
        decisions=decisions,
        open_questions=open_questions,
        action_items=action_items,
        pending_action_items=pending_action_items,
        stage_plan=[
            "prepare_post_meeting_input",
            "clean_transcript",
            "extract_decisions_and_action_items",
            "validate_owner_due_date_evidence",
            "render_summary_or_confirmation_card",
            "request_human_confirmation_before_task_creation",
        ],
        extra={
            "ready_action_item_count": len([item for item in action_items if not item.needs_confirm]),
            "pending_action_item_count": len(pending_action_items),
            "task_creation_requires_human_confirmation": True,
        },
    )
    artifacts.card_payloads = {
        "summary_card": build_post_meeting_summary_card(artifacts),
        "pending_card": build_pending_action_items_card(artifacts),
    }
    return artifacts


def enrich_post_meeting_related_resources(
    artifacts: PostMeetingArtifacts,
    knowledge_store: Any,
    top_n: int = 5,
) -> PostMeetingArtifacts:
    """复用 M3 轻量 RAG 为会后总结补充背景资料。

    M4 不直接读取飞书文档，也不绕过知识索引权限边界；这里只用已经进入本地
    RAG 索引的资料做召回，并把压缩证据包放进卡片展示。检索失败时调用方可
    继续发送普通会后卡片，不应阻断任务创建。
    """

    query = build_post_meeting_related_resource_query(artifacts)
    if not query:
        artifacts.extra["related_knowledge_status"] = "skipped_empty_query"
        return artifacts
    result = knowledge_store.search_chunks(
        query=query,
        meeting_id=artifacts.workflow_input.meeting_id,
        project_id=artifacts.workflow_input.project_id,
        resource_types=["doc", "docx", "wiki", "sheet", "bitable"],
        top_k=max(top_n * 4, 12),
        top_n=top_n,
        evidence_token_budget=600,
        max_snippet_tokens=120,
    )
    hits = list(getattr(result, "hits", []) or [])
    hits = dedupe_related_knowledge_hits(hits, limit=top_n)
    artifacts.extra["related_knowledge_query"] = query
    artifacts.extra["related_knowledge_hits"] = hits
    artifacts.extra["related_knowledge_status"] = "hit" if hits else "empty"
    artifacts.extra["related_knowledge_reason"] = getattr(result, "reason", "")
    artifacts.card_payloads["summary_card"] = build_post_meeting_summary_card(artifacts)
    return artifacts


def build_post_meeting_related_resource_query(artifacts: PostMeetingArtifacts) -> str:
    """为会后背景资料召回构造稳定查询。"""

    workflow_input = artifacts.workflow_input
    parts: list[str] = [
        workflow_input.topic,
        workflow_input.project_id,
    ]
    parts.extend(item.content for item in artifacts.decisions[:4])
    parts.extend(item.title for item in artifacts.action_items[:4])
    return " ".join(unique_non_empty([part.strip() for part in parts if part])).strip()


def dedupe_related_knowledge_hits(hits: list[Any], limit: int) -> list[Any]:
    """按文档维度去重背景资料，避免同一文档多个 chunk 挤占业务卡片。"""

    deduped: list[Any] = []
    seen: set[str] = set()
    for hit in hits:
        key = "|".join(
            [
                str(getattr(hit, "document_id", "") or ""),
                str(getattr(hit, "source_url", "") or ""),
                str(getattr(hit, "title", "") or ""),
            ]
        ).strip("|")
        if not key:
            key = str(getattr(hit, "ref_id", "") or getattr(hit, "chunk_id", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
        if len(deduped) >= limit:
            break
    return deduped


def build_fallback_decisions(
    cleaned_transcript: CleanedTranscript,
    meeting_id: str = "",
    source_url: str = "",
) -> list[ExtractedDecision]:
    """在显式决策缺失时，为关键结论区提供保守兜底。

    真实妙记有时把结论写进“会议总结 / 正文”而不是“关键结论”章节。卡片中的
    关键结论区对用户很重要，所以这里从非待办、非开放问题的高价值行中选取
    少量摘要句，并标记为 `fallback=True` 方便后续审计。
    """

    decisions: list[ExtractedDecision] = []
    seen: set[str] = set()
    for line_no, line in iter_fallback_decision_lines(cleaned_transcript):
        content = normalize_fallback_decision_content(line)
        if not content or content in seen:
            continue
        seen.add(content)
        decisions.append(
            ExtractedDecision(
                decision_id=stable_id("decision_fallback", meeting_id, line),
                content=content,
                confidence=0.52,
                evidence_refs=[
                    build_evidence_ref(
                        source_type=cleaned_transcript.source_type or "minute",
                        source_id=cleaned_transcript.source_id or meeting_id or "post_meeting",
                        source_url=source_url or cleaned_transcript.source_url,
                        snippet=line,
                    )
                ],
                source_line=line_no,
                extra={"fallback": True, "reason": "未识别到显式关键结论，使用会议摘要行兜底"},
            )
        )
        if len(decisions) >= 3:
            break
    return decisions


def iter_fallback_decision_lines(cleaned_transcript: CleanedTranscript) -> list[tuple[int, str]]:
    """枚举可作为关键结论兜底的纪要行。"""

    candidates: list[tuple[int, str]] = []
    for section in cleaned_transcript.sections:
        if is_action_section(section.title):
            continue
        for offset, line in enumerate(section.lines):
            stripped = line.strip()
            if not stripped or is_heading_like_line(stripped):
                continue
            tags = detect_signal_tags(stripped)
            if should_extract_action_item(stripped, tags) or should_extract_open_question_line(stripped, tags):
                continue
            if len(stripped) < 8:
                continue
            if any(keyword in stripped for keyword in ("总结", "方案", "目标", "背景", "结论", "决定", "采用", "需要", "已经")):
                candidates.append((section.start_line + offset, stripped))
    return candidates


def normalize_fallback_decision_content(line: str) -> str:
    """清理关键结论兜底行的常见前缀。"""

    content = re.sub(r"^(?:会议总结|总结|背景|目标)[:：]\s*", "", line.strip())
    return content.strip(" ，,；;。")


def build_empty_post_meeting_artifacts(workflow_input: PostMeetingInput) -> PostMeetingArtifacts:
    """构造只包含契约壳的 M4 产物。

    T4.2 用它验证最终产物边界。后续 T4.3-T4.8 会逐步填充清洗结果、
    决策、开放问题、Action Items 和卡片 payload。
    """

    cleaned_transcript = CleanedTranscript(
        raw_text=workflow_input.raw_text,
        source_type=workflow_input.source_type,
        source_id=workflow_input.source_id,
        source_url=workflow_input.source_url,
    )
    meeting_summary = MeetingSummary(
        meeting_id=workflow_input.meeting_id,
        project_id=workflow_input.project_id,
        topic=workflow_input.topic,
    )
    return PostMeetingArtifacts(
        workflow_input=workflow_input,
        cleaned_transcript=cleaned_transcript,
        meeting_summary=meeting_summary,
        stage_plan=[
            "prepare_post_meeting_input",
            "clean_transcript",
            "extract_decisions_and_action_items",
            "validate_owner_due_date_evidence",
            "render_summary_or_confirmation_card",
            "request_human_confirmation_before_task_creation",
        ],
    )


def build_task_create_arguments(
    action_item: ActionItem,
    context: WorkflowContext | None = None,
    assignee_ids: list[str] | None = None,
    timezone: str = "Asia/Shanghai",
) -> dict[str, Any]:
    """把已确认的行动项转换为 `tasks.create_task` 工具参数。

    这里只生成工具参数，不直接调用飞书。`assignee_ids` 必须由通讯录工具解析
    后传入，不能使用纪要中的姓名文本冒充 open_id。
    """

    idempotency_key = build_task_idempotency_key(action_item, context)
    due_timestamp_ms = parse_due_date_to_timestamp_ms(action_item.due_date, timezone=timezone)
    description = build_task_description(action_item, context)
    return {
        "summary": action_item.title,
        "description": description,
        "assignee_ids": list(assignee_ids or []),
        "due_timestamp_ms": due_timestamp_ms,
        "confidence": action_item.confidence,
        "idempotency_key": idempotency_key,
        "identity": "user",
        "evidence_refs": [ref.to_dict() for ref in action_item.evidence_refs],
    }


def build_task_mapping_payload(
    action_item: ActionItem,
    task_result: ActionItem | dict[str, Any],
    context: WorkflowContext | None = None,
) -> dict[str, Any]:
    """构造保存到 `task_mappings` 的稳定字段。"""

    task_id = ""
    task_status = action_item.status
    if isinstance(task_result, ActionItem):
        task_id = task_result.item_id
        task_status = task_result.status or task_status
    elif isinstance(task_result, dict):
        task_id = str(task_result.get("item_id") or task_result.get("task_id") or task_result.get("guid") or "")
        task_status = str(task_result.get("status") or task_status)

    return {
        "item_id": action_item.item_id,
        "task_id": task_id,
        "meeting_id": context.meeting_id if context else "",
        "minute_token": context.minute_token if context else "",
        "title": action_item.title,
        "owner": action_item.owner,
        "due_date": action_item.due_date,
        "status": task_status,
        "evidence_refs": [ref.to_dict() for ref in action_item.evidence_refs],
        "source_url": first_evidence_source_url(action_item),
    }


def build_task_idempotency_key(action_item: ActionItem, context: WorkflowContext | None = None) -> str:
    """为任务创建生成稳定幂等键。"""

    meeting_id = context.meeting_id if context else ""
    minute_token = context.minute_token if context else ""
    base = "|".join([meeting_id, minute_token, action_item.item_id, action_item.title])
    return f"post_meeting:create_task:{stable_id('item', base)}"


def build_task_description(action_item: ActionItem, context: WorkflowContext | None = None) -> str:
    """生成飞书任务描述，保留会议来源和证据片段。"""

    lines = ["由 MeetFlow 从会后纪要中抽取。"]
    if context and context.meeting_id:
        lines.append(f"会议 ID：{context.meeting_id}")
    if context and context.minute_token:
        lines.append(f"妙记 token：{context.minute_token}")
    for index, ref in enumerate(action_item.evidence_refs[:3], start=1):
        source = ref.source_url or ref.source_id
        lines.append(f"证据 {index}：{ref.snippet}")
        if source:
            lines.append(f"来源 {index}：{source}")
    return "\n".join(lines)


def parse_due_date_to_timestamp_ms(raw_due_date: str, timezone: str = "Asia/Shanghai") -> str:
    """把常见中文截止时间转换为毫秒时间戳。

    首版支持相对日期、周几、YYYY-MM-DD、YYYY/MM/DD、MM-DD、MM/DD。无法解析时
    返回空字符串，由 `AgentPolicy` 或待确认卡片继续拦截。
    """

    due = raw_due_date.strip().rstrip("前之前内")
    if not due:
        return ""
    if due.isdigit() and len(due) >= 10:
        return due

    tz = ZoneInfo(timezone or "Asia/Shanghai")
    now = datetime.now(tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if due in {"今天", "今日"}:
        return str(int(today.timestamp() * 1000))
    if due in {"明天", "最晚明天", "今天或明天", "今天到明天", "今天或最晚明天"}:
        return str(int((today + timedelta(days=1)).timestamp() * 1000))
    if due == "后天":
        return str(int((today + timedelta(days=2)).timestamp() * 1000))
    if due == "本周":
        return str(int(next_weekday(today, 5, include_today=True).timestamp() * 1000))
    if due == "下周":
        return str(int((next_weekday(today, 0, include_today=False) + timedelta(days=7)).timestamp() * 1000))
    if due == "月底":
        next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return str(int((next_month - timedelta(days=1)).timestamp() * 1000))

    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    weekday_match = re.search(r"(下?周)([一二三四五六日天])", due)
    if weekday_match:
        weekday = weekday_map[weekday_match.group(2)]
        base = next_weekday(today, weekday, include_today=True)
        if weekday_match.group(1) == "下周":
            base = base + timedelta(days=7)
        return str(int(base.timestamp() * 1000))

    date_match = re.match(r"(?P<year>20\d{2})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})", due)
    if date_match:
        target = datetime(
            int(date_match.group("year")),
            int(date_match.group("month")),
            int(date_match.group("day")),
            tzinfo=tz,
        )
        return str(int(target.timestamp() * 1000))

    short_date_match = re.match(r"(?P<month>\d{1,2})[/-](?P<day>\d{1,2})", due)
    if short_date_match:
        target = datetime(
            today.year,
            int(short_date_match.group("month")),
            int(short_date_match.group("day")),
            tzinfo=tz,
        )
        if target < today:
            target = target.replace(year=today.year + 1)
        return str(int(target.timestamp() * 1000))
    return ""


def next_weekday(today: datetime, weekday: int, include_today: bool) -> datetime:
    """计算最近的指定周几。"""

    delta = (weekday - today.weekday()) % 7
    if delta == 0 and not include_today:
        delta = 7
    return today + timedelta(days=delta)


def collect_artifact_evidence(*groups: Any) -> list[EvidenceRef]:
    """从产物集合中收集去重证据。"""

    refs: list[EvidenceRef] = []
    seen: set[str] = set()
    for group in groups:
        for item in list(group or []):
            for ref in list(getattr(item, "evidence_refs", []) or []):
                key = f"{ref.source_type}|{ref.source_id}|{ref.snippet}"
                if key in seen:
                    continue
                seen.add(key)
                refs.append(ref)
    return refs


def first_evidence_source_url(action_item: ActionItem) -> str:
    """读取行动项第一条证据来源链接。"""

    for ref in action_item.evidence_refs:
        if ref.source_url:
            return ref.source_url
    return ""


def first_content_resource(resources: list[Resource]) -> Resource | None:
    """选择最适合作为纪要文本来源的资源。

    妙记优先，其次是文档。这个函数只在已有上下文资源中选择，不主动读取外部
    系统，避免 T4.2 提前引入真实 API 依赖。
    """

    preferred_types = {"minute", "minutes", "doc", "document"}
    for resource in resources:
        if resource.content and resource.resource_type in preferred_types:
            return resource
    for resource in resources:
        if resource.content:
            return resource
    return None


def first_non_empty(data: dict[str, Any], *keys: str) -> str:
    """从 payload 中读取第一个非空字段，统一转成字符串。"""

    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return str(value)
    return ""


def unique_non_empty(items: list[str]) -> list[str]:
    """保持顺序去重，并过滤空字符串。"""

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        clean_item = item.strip()
        if not clean_item or clean_item in seen:
            continue
        seen.add(clean_item)
        result.append(clean_item)
    return result
