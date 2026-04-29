from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.models import BaseModel, EvidenceRef, Resource, WorkflowContext


@dataclass(slots=True)
class PreMeetingBriefInput(BaseModel):
    """会前工作流的确定性输入模型。

    它把 `WorkflowContext` 中与会前卡片有关的字段收拢起来，让后续
    主题识别、检索、摘要和卡片渲染都依赖稳定结构，而不是反复读取
    原始飞书 payload。
    """

    meeting_id: str
    calendar_event_id: str
    project_id: str
    meeting_title: str = ""
    meeting_description: str = ""
    start_time: str = ""
    end_time: str = ""
    timezone: str = ""
    organizer: str = ""
    participants: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    related_resources: list[Resource] = field(default_factory=list)
    memory_snapshot: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalQuery(BaseModel):
    """会前知识召回的结构化查询。

    M3 后续的轻量 RAG 会基于这个对象做 query enrichment、候选召回、
    混合排序和低置信度判断。它不等同于一个关键词字符串，而是保留
    会议、人员、附件、资源类型和缺失上下文等信号。
    """

    meeting_id: str
    calendar_event_id: str
    project_id: str
    meeting_title: str = ""
    meeting_description: str = ""
    entities: list[str] = field(default_factory=list)
    attendee_names: list[str] = field(default_factory=list)
    attachment_titles: list[str] = field(default_factory=list)
    related_resource_titles: list[str] = field(default_factory=list)
    resource_types: list[str] = field(default_factory=lambda: ["doc", "sheet", "minute", "task"])
    time_window: str = "recent_90_days"
    search_queries: list[str] = field(default_factory=list)
    confidence: float = 0.0
    missing_context: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CandidateProject(BaseModel):
    """会议可能归属的项目候选。

    T3.2 先用规则分数承接项目记忆、标题、附件和人员线索。后续接入知识库
    检索后，可以继续把历史同名会议、相似参会人组合等信号写进这里。
    """

    project_id: str
    name: str
    score: float
    matched_signals: list[str] = field(default_factory=list)
    source: str = "memory"


@dataclass(slots=True)
class MeetingTopicSignal(BaseModel):
    """会议主题识别结果。

    输出不只是一段主题文本，还包含候选项目、业务实体、参会人线索、置信度
    和缺失字段，方便低置信场景进入“可能相关资料”或人工确认模式。
    """

    topic: str
    candidate_projects: list[CandidateProject] = field(default_factory=list)
    business_entities: list[str] = field(default_factory=list)
    attendee_signals: list[str] = field(default_factory=list)
    confidence: float = 0.0
    missing_context: list[str] = field(default_factory=list)
    query_hints: list[str] = field(default_factory=list)
    needs_confirmation: bool = False
    reason: str = ""


@dataclass(slots=True)
class RetrievedResource(BaseModel):
    """会前召回到的一条相关资源。

    这是 T3.3 的确定性召回结果，先承接资源标题、摘要、链接、更新时间、
    命中原因和回链定位。后续 T3.4 的 `KnowledgeChunk` 可以继续挂到
    `source_locator` 或 `extra` 里。
    """

    resource_id: str
    resource_type: str
    title: str
    summary: str
    source_url: str
    updated_at: str = ""
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    source_locator: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalResult(BaseModel):
    """关联资源召回结果集合。"""

    query: RetrievalQuery
    resources: list[RetrievedResource] = field(default_factory=list)
    omitted_count: int = 0
    low_confidence: bool = False
    reason: str = ""


@dataclass(slots=True)
class MeetingBriefItem(BaseModel):
    """会前卡片中的一条可溯源内容。"""

    title: str
    content: str
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "draft"


@dataclass(slots=True)
class MeetingBrief(BaseModel):
    """会前背景知识卡片的结构化产物。

    这个对象是 Agent Loop 草案和卡片渲染层之间的契约。LLM 后续可以
    负责填充摘要和证据，但字段边界由确定性代码固定，避免卡片层解析
    自由文本。
    """

    meeting_id: str
    calendar_event_id: str
    project_id: str
    topic: str
    summary: str = ""
    last_decisions: list[MeetingBriefItem] = field(default_factory=list)
    current_questions: list[MeetingBriefItem] = field(default_factory=list)
    must_read_resources: list[MeetingBriefItem] = field(default_factory=list)
    risks: list[MeetingBriefItem] = field(default_factory=list)
    possible_related_resources: list[MeetingBriefItem] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    confidence: float = 0.0
    needs_confirmation: bool = False
    status: str = "draft"


@dataclass(slots=True)
class PreMeetingCardPayload(BaseModel):
    """会前卡片渲染层的最小输入。

    当前飞书卡片工具接受 `title`、`summary` 和 `facts`。这里先对齐这个
    最小接口，后续 T3.7 可以在不破坏 `MeetingBrief` 的情况下替换为
    更复杂的卡片模板。
    """

    title: str
    summary: str
    facts: list[dict[str, str]] = field(default_factory=list)
    source_meeting_id: str = ""
    idempotency_key: str = ""


@dataclass(slots=True)
class PreMeetingBriefArtifacts(BaseModel):
    """`pre_meeting_brief` 工作流各阶段之间传递的中间产物。"""

    workflow_input: PreMeetingBriefInput
    topic_signal: MeetingTopicSignal
    retrieval_query: RetrievalQuery
    retrieval_result: RetrievalResult
    meeting_brief: MeetingBrief
    card_payload: PreMeetingCardPayload
    stage_plan: list[str] = field(default_factory=list)


def build_pre_meeting_brief_artifacts(context: WorkflowContext) -> PreMeetingBriefArtifacts:
    """从 `WorkflowContext` 构造 T3.1 约定的会前工作流输入输出壳。"""

    workflow_input = build_pre_meeting_brief_input(context)
    topic_signal = identify_meeting_topic(workflow_input)
    retrieval_query = build_retrieval_query(workflow_input, topic_signal)
    retrieval_result = recall_related_resources(workflow_input, retrieval_query)
    meeting_brief = build_initial_meeting_brief(
        workflow_input,
        retrieval_query,
        topic_signal,
        retrieval_result,
    )
    card_payload = render_pre_meeting_card_payload(meeting_brief)
    return PreMeetingBriefArtifacts(
        workflow_input=workflow_input,
        topic_signal=topic_signal,
        retrieval_query=retrieval_query,
        retrieval_result=retrieval_result,
        meeting_brief=meeting_brief,
        card_payload=card_payload,
        stage_plan=[
            "prepare_context",
            "build_retrieval_query",
            "agent_loop_collect_evidence",
            "validate_meeting_brief",
            "render_card_payload",
            "send_or_save",
        ],
    )


def build_pre_meeting_brief_input(context: WorkflowContext) -> PreMeetingBriefInput:
    """把通用上下文转换成会前工作流专用输入。"""

    payload = context.event.payload if context.event else {}
    return PreMeetingBriefInput(
        meeting_id=context.meeting_id,
        calendar_event_id=context.calendar_event_id,
        project_id=context.project_id,
        meeting_title=first_non_empty(payload, "summary", "title", "meeting_title", "calendar_summary"),
        meeting_description=first_non_empty(payload, "description", "meeting_description", "desc"),
        start_time=first_non_empty(payload, "start_time", "startTime", "start"),
        end_time=first_non_empty(payload, "end_time", "endTime", "end"),
        timezone=first_non_empty(payload, "timezone", "time_zone"),
        organizer=first_non_empty(payload, "organizer", "organizer_name", "creator_name"),
        participants=list(context.participants),
        attachments=normalize_dict_list(payload.get("attachments", [])),
        related_resources=list(context.related_resources),
        memory_snapshot=dict(context.memory_snapshot),
        raw_payload=dict(payload),
    )


def build_retrieval_query(
    workflow_input: PreMeetingBriefInput,
    topic_signal: MeetingTopicSignal | None = None,
) -> RetrievalQuery:
    """基于会前输入生成结构化检索查询。"""

    final_topic_signal = topic_signal or identify_meeting_topic(workflow_input)
    attachment_titles = [
        first_non_empty(item, "title", "name", "url", "link")
        for item in workflow_input.attachments
    ]
    attendee_names = [
        first_non_empty(item, "display_name", "name", "email", "open_id")
        for item in workflow_input.participants
    ]
    related_resource_titles = [resource.title for resource in workflow_input.related_resources if resource.title]
    entities = unique_non_empty(
        [
            *final_topic_signal.business_entities,
            *collect_entities(
                workflow_input.meeting_title,
                workflow_input.meeting_description,
                attachment_titles,
                related_resource_titles,
            ),
        ]
    )
    search_queries = unique_non_empty(
        [
            final_topic_signal.topic,
            workflow_input.meeting_title,
            workflow_input.project_id,
            *final_topic_signal.query_hints,
            " ".join(entities[:8]),
            " ".join(attachment_titles[:5]),
            " ".join(attendee_names[:5]),
            *related_resource_titles[:5],
        ]
    )
    missing_context: list[str] = []
    if not workflow_input.meeting_title:
        missing_context.append("meeting_title")
    if not workflow_input.participants:
        missing_context.append("participants")
    if not workflow_input.attachments and not workflow_input.related_resources:
        missing_context.append("related_resources")
    missing_context = unique_non_empty([*missing_context, *final_topic_signal.missing_context])

    confidence = 0.35
    if workflow_input.meeting_title:
        confidence += 0.25
    if workflow_input.participants:
        confidence += 0.15
    if workflow_input.attachments or workflow_input.related_resources:
        confidence += 0.15
    if workflow_input.memory_snapshot:
        confidence += 0.10
    confidence = max(confidence, final_topic_signal.confidence)

    return RetrievalQuery(
        meeting_id=workflow_input.meeting_id,
        calendar_event_id=workflow_input.calendar_event_id,
        project_id=workflow_input.project_id,
        meeting_title=workflow_input.meeting_title,
        meeting_description=workflow_input.meeting_description,
        entities=entities,
        attendee_names=unique_non_empty([*attendee_names, *final_topic_signal.attendee_signals]),
        attachment_titles=unique_non_empty(attachment_titles),
        related_resource_titles=unique_non_empty(related_resource_titles),
        search_queries=search_queries,
        confidence=min(confidence, 0.95),
        missing_context=missing_context,
        extra={
            "identified_topic": final_topic_signal.topic,
            "topic_signal": final_topic_signal.to_dict(),
            "start_time": workflow_input.start_time,
            "end_time": workflow_input.end_time,
            "timezone": workflow_input.timezone,
            "organizer": workflow_input.organizer,
        },
    )


def build_initial_meeting_brief(
    workflow_input: PreMeetingBriefInput,
    retrieval_query: RetrievalQuery,
    topic_signal: MeetingTopicSignal | None = None,
    retrieval_result: RetrievalResult | None = None,
) -> MeetingBrief:
    """生成进入 Agent Loop 前的 MeetingBrief 空壳。

    当前只放入确定性已知信息和证据不足提示。T3.5 后会用检索证据和 LLM
    草案填充结论、风险和必读资料。
    """

    final_topic_signal = topic_signal or identify_meeting_topic(workflow_input)
    topic = final_topic_signal.topic or workflow_input.meeting_title or workflow_input.project_id or "待确认会议"
    if retrieval_result is None:
        retrieval_result = recall_related_resources(workflow_input, retrieval_query)
    evidence_items = build_brief_items_from_retrieval(retrieval_result)
    last_decisions = select_brief_items_by_intent(evidence_items, ["上次", "决定", "结论", "妙记", "评审"])
    current_questions = select_brief_items_by_intent(evidence_items, ["问题", "待确认", "方案", "评审", "字段"])
    risks = select_risk_items(evidence_items)
    must_read_resources = select_must_read_resources(evidence_items)
    possible_resources = [
        item
        for item in evidence_items
        if item.title not in {selected.title for selected in must_read_resources}
    ][:5]
    summary = build_pre_meeting_summary(
        topic=topic,
        last_decisions=last_decisions,
        current_questions=current_questions,
        must_read_resources=must_read_resources,
        risks=risks,
        retrieval_result=retrieval_result,
    )
    evidence_refs = collect_brief_evidence_refs(
        [*last_decisions, *current_questions, *must_read_resources, *risks, *possible_resources]
    )
    return MeetingBrief(
        meeting_id=workflow_input.meeting_id,
        calendar_event_id=workflow_input.calendar_event_id,
        project_id=workflow_input.project_id,
        topic=topic,
        summary=summary,
        last_decisions=last_decisions,
        current_questions=current_questions,
        must_read_resources=must_read_resources,
        risks=risks,
        possible_related_resources=possible_resources,
        evidence_refs=evidence_refs,
        confidence=retrieval_query.confidence,
        needs_confirmation=(
            bool(retrieval_query.missing_context)
            or final_topic_signal.needs_confirmation
            or retrieval_result.low_confidence
        ),
        status="draft",
    )


def recall_related_resources(
    workflow_input: PreMeetingBriefInput,
    retrieval_query: RetrievalQuery,
    top_k: int = 8,
) -> RetrievalResult:
    """根据 `RetrievalQuery` 召回会前相关资源。

    T3.3 首版先做本地候选召回：payload 已带资源、日程附件、项目记忆资源。
    排序采用关键词/元数据命中 + 资源新鲜度的轻量混合分数。T3.4 接入知识
    索引后，这里可以改为从 KnowledgeStore 读取候选 chunk/document。
    """

    candidates = build_resource_candidates(workflow_input)
    scored: list[RetrievedResource] = []
    seen_keys: set[str] = set()
    for resource in candidates:
        candidate = score_resource_candidate(resource, retrieval_query)
        if candidate.score < 0.25 or not has_business_match(candidate):
            continue
        dedupe_key = candidate.source_url or f"{candidate.resource_type}:{candidate.resource_id}:{candidate.title}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        scored.append(candidate)

    scored.sort(key=lambda item: item.score, reverse=True)
    top_resources = scored[:top_k]
    omitted_count = max(len(scored) - len(top_resources), 0)
    low_confidence = not top_resources or retrieval_query.confidence < 0.55
    if top_resources:
        reason = f"召回 {len(top_resources)} 条资源，按关键词、元数据和更新时间排序。"
    else:
        reason = "未召回到相关资源，需要补充附件、项目记忆或后续接入知识索引。"
    return RetrievalResult(
        query=retrieval_query,
        resources=top_resources,
        omitted_count=omitted_count,
        low_confidence=low_confidence,
        reason=reason,
    )


def build_resource_candidates(workflow_input: PreMeetingBriefInput) -> list[RetrievedResource]:
    """构造 T3.3 首版召回候选池。"""

    candidates: list[RetrievedResource] = []
    for resource in workflow_input.related_resources:
        candidates.append(resource_to_retrieved_resource(resource, source="payload.related_resources"))

    for index, attachment in enumerate(workflow_input.attachments):
        title = first_non_empty(attachment, "title", "name", "file_name", "url", "link")
        url = first_non_empty(attachment, "source_url", "url", "link")
        candidates.append(
            RetrievedResource(
                resource_id=first_non_empty(attachment, "resource_id", "document_id", "token", "id") or f"attachment_{index}",
                resource_type=normalize_resource_type(first_non_empty(attachment, "resource_type", "type") or "attachment"),
                title=title or f"日程附件 {index + 1}",
                summary=first_non_empty(attachment, "summary", "description", "content"),
                source_url=url,
                updated_at=first_non_empty(attachment, "updated_at", "update_time", "created_at"),
                source_locator=first_non_empty(attachment, "source_locator", "block_id", "range", "sheet"),
                metadata={"candidate_source": "calendar.attachment", **attachment},
            )
        )

    memory = workflow_input.memory_snapshot
    for source_key in ("resources", "documents", "docs", "minutes", "tasks", "recent_resources"):
        raw_items = memory.get(source_key)
        if not isinstance(raw_items, list):
            continue
        for index, item in enumerate(raw_items):
            if isinstance(item, dict):
                candidates.append(resource_dict_to_retrieved_resource(item, source=f"memory.{source_key}", index=index))
            elif item:
                candidates.append(
                    RetrievedResource(
                        resource_id=f"{source_key}_{index}",
                        resource_type=normalize_resource_type(source_key),
                        title=str(item),
                        summary="",
                        source_url="",
                        metadata={"candidate_source": f"memory.{source_key}"},
                    )
                )
    return candidates


def resource_to_retrieved_resource(resource: Resource, source: str) -> RetrievedResource:
    """把通用 `Resource` 转成 T3.3 召回候选。"""

    return RetrievedResource(
        resource_id=resource.resource_id,
        resource_type=normalize_resource_type(resource.resource_type),
        title=resource.title,
        summary=resource.content[:240],
        source_url=resource.source_url,
        updated_at=resource.updated_at,
        source_locator=str(resource.source_meta.get("source_locator") or resource.source_meta.get("block_id") or ""),
        metadata={"candidate_source": source, **resource.source_meta},
    )


def resource_dict_to_retrieved_resource(data: dict[str, Any], source: str, index: int) -> RetrievedResource:
    """把项目记忆里的资源字典转成召回候选。"""

    return RetrievedResource(
        resource_id=first_non_empty(data, "resource_id", "id", "document_id", "minute_token", "task_id") or f"{source}_{index}",
        resource_type=normalize_resource_type(first_non_empty(data, "resource_type", "type", "source_type") or source),
        title=first_non_empty(data, "title", "name", "summary") or f"未命名资源 {index + 1}",
        summary=first_non_empty(data, "summary", "description", "content"),
        source_url=first_non_empty(data, "source_url", "url", "link", "app_link"),
        updated_at=first_non_empty(data, "updated_at", "update_time", "modified_at", "created_at"),
        source_locator=first_non_empty(data, "source_locator", "block_id", "range", "sheet", "segment_id"),
        metadata={"candidate_source": source, **data},
    )


def score_resource_candidate(resource: RetrievedResource, retrieval_query: RetrievalQuery) -> RetrievedResource:
    """对资源候选进行轻量混合排序打分。"""

    text = " ".join(
        [
            resource.title,
            resource.summary,
            resource.resource_type,
            resource.source_url,
            str(resource.metadata.get("candidate_source", "")),
        ]
    ).lower()
    score = 0.0
    reasons: list[str] = []

    for query in retrieval_query.search_queries:
        if query and query.lower() in text:
            score += 0.30
            reasons.append(f"命中检索词:{query}")
    for entity in retrieval_query.entities:
        if entity and entity.lower() in text:
            score += 0.18
            reasons.append(f"命中实体:{entity}")
    for attendee in retrieval_query.attendee_names:
        if attendee and attendee.lower() in text:
            score += 0.08
            reasons.append(f"命中参会人:{attendee}")
    for title in retrieval_query.attachment_titles:
        if title and title.lower() in text:
            score += 0.16
            reasons.append(f"命中附件标题:{title}")
    if resource.resource_type in retrieval_query.resource_types:
        score += 0.08
        reasons.append(f"资源类型匹配:{resource.resource_type}")
    freshness = estimate_freshness_score(resource.updated_at)
    if freshness:
        score += freshness
        reasons.append("资源更新时间较近")
    if resource.source_url:
        score += 0.04
        reasons.append("包含来源链接")
    if resource.source_locator:
        score += 0.03
        reasons.append("包含回链定位")

    return RetrievedResource(
        resource_id=resource.resource_id,
        resource_type=resource.resource_type,
        title=resource.title,
        summary=resource.summary,
        source_url=resource.source_url,
        updated_at=resource.updated_at,
        score=round(min(score, 0.99), 3),
        reasons=unique_non_empty(reasons),
        source_locator=resource.source_locator,
        metadata=resource.metadata,
    )


def has_business_match(resource: RetrievedResource) -> bool:
    """判断资源是否真正命中业务线索。

    类型匹配、更新时间和链接只是排序加权，不能单独证明资源相关。
    """

    prefixes = (
        "命中检索词:",
        "命中实体:",
        "命中参会人:",
        "命中附件标题:",
    )
    return any(reason.startswith(prefixes) for reason in resource.reasons)


def build_brief_items_from_retrieval(retrieval_result: RetrievalResult) -> list[MeetingBriefItem]:
    """把召回资源转换成 `MeetingBrief` 的候选资料条目。"""

    items: list[MeetingBriefItem] = []
    for resource in rank_retrieved_resources_for_brief(retrieval_result.resources):
        evidence = EvidenceRef(
            source_type=resource.resource_type,
            source_id=resource.resource_id,
            source_url=resource.source_url,
            snippet=resource.summary or "资源已召回，等待后续 chunk 展开。",
            updated_at=resource.updated_at,
        )
        items.append(
            MeetingBriefItem(
                title=resource.title,
                content=build_brief_item_content(resource),
                evidence_refs=[evidence],
                confidence=resource.score,
                status="high_confidence" if resource.score >= 0.70 else "possible",
            )
        )
    return items


def rank_retrieved_resources_for_brief(resources: list[RetrievedResource]) -> list[RetrievedResource]:
    """为会前最小知识集重新排序证据。

    T3.3 的召回分数重在“相关性”，T3.5 还会轻微偏好妙记、任务和带回链定位的资源，
    因为它们更容易提炼上次结论、当前风险和可验证来源。
    """

    def rank_key(resource: RetrievedResource) -> tuple[float, float, str]:
        type_boost = {
            "minute": 0.08,
            "task": 0.06,
            "doc": 0.04,
            "sheet": 0.03,
        }.get(resource.resource_type, 0.0)
        locator_boost = 0.03 if resource.source_locator else 0.0
        return (resource.score + type_boost + locator_boost, resource.score, resource.title)

    return sorted(resources, key=rank_key, reverse=True)


def build_brief_item_content(resource: RetrievedResource) -> str:
    """构造会前卡片条目的简短内容。"""

    reason = "；".join(resource.reasons[:3])
    summary = resource.summary or resource.source_url or "资源已召回，等待后续 chunk 展开。"
    if reason:
        return f"{summary}\n召回原因：{reason}"
    return summary


def select_must_read_resources(items: list[MeetingBriefItem], limit: int = 3) -> list[MeetingBriefItem]:
    """选择会前最值得阅读的资料。"""

    selected: list[MeetingBriefItem] = []
    for item in items:
        if item.confidence >= 0.65:
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def select_brief_items_by_intent(
    items: list[MeetingBriefItem],
    keywords: list[str],
    limit: int = 3,
) -> list[MeetingBriefItem]:
    """按关键词从证据条目中挑选某类会前信息。"""

    selected: list[MeetingBriefItem] = []
    for item in items:
        text = f"{item.title}\n{item.content}".lower()
        if any(keyword.lower() in text for keyword in keywords):
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def select_risk_items(items: list[MeetingBriefItem], limit: int = 3) -> list[MeetingBriefItem]:
    """选择需要会前关注的风险或待办。

    避免把“卡片包含风险点字段”这类字段说明误判为真实风险；任务类资源
    或明确含有风险、阻塞、逾期、待办、未完成等信号时才进入风险栏。
    """

    selected: list[MeetingBriefItem] = []
    strong_keywords = ["阻塞", "逾期", "待办", "未完成", "延期", "依赖"]
    for item in items:
        text = f"{item.title}\n{item.content}".lower()
        source_type = item.evidence_refs[0].source_type if item.evidence_refs else ""
        has_real_risk = any(keyword.lower() in text for keyword in strong_keywords)
        has_risk_signal = "风险" in text and not any(marker in text for marker in ["字段", "字段说明", "模板"])
        if source_type == "task" or has_real_risk or has_risk_signal:
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def build_pre_meeting_summary(
    topic: str,
    last_decisions: list[MeetingBriefItem],
    current_questions: list[MeetingBriefItem],
    must_read_resources: list[MeetingBriefItem],
    risks: list[MeetingBriefItem],
    retrieval_result: RetrievalResult,
) -> str:
    """生成简洁的会前背景摘要草案。"""

    if retrieval_result.low_confidence:
        return f"{topic} 的上下文证据不足，当前只召回到可能相关资料，建议人工确认后再推送。"

    parts = [f"围绕 {topic}，已召回 {len(retrieval_result.resources)} 条相关资料。"]
    if last_decisions:
        parts.append(f"上次结论优先查看：{join_item_titles(last_decisions)}。")
    if current_questions:
        parts.append(f"本次讨论重点可能集中在：{join_item_titles(current_questions)}。")
    if risks:
        parts.append(f"需要提前关注的风险或待办：{join_item_titles(risks)}。")
    if must_read_resources:
        parts.append(f"会前待读资料：{join_item_titles(must_read_resources)}。")
    return "".join(parts)


def join_item_titles(items: list[MeetingBriefItem]) -> str:
    """拼接条目标题，控制摘要长度。"""

    return "、".join(item.title for item in items[:3])


def collect_brief_evidence_refs(items: list[MeetingBriefItem]) -> list[EvidenceRef]:
    """收集 MeetingBrief 顶层证据，按来源去重。"""

    refs: list[EvidenceRef] = []
    seen: set[str] = set()
    for item in items:
        for ref in item.evidence_refs:
            key = f"{ref.source_type}:{ref.source_id}:{ref.source_url}:{ref.snippet}"
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def identify_meeting_topic(workflow_input: PreMeetingBriefInput) -> MeetingTopicSignal:
    """识别会议主题、候选项目和 query 增强线索。

    首版使用确定性规则，主要服务三类输入：
    - 标题/描述包含明确项目或版本号
    - 标题较短，但附件和项目记忆能补足上下文
    - 标题和资源都不足，需要进入低置信待确认
    """

    attachment_titles = [
        first_non_empty(item, "title", "name", "url", "link")
        for item in workflow_input.attachments
    ]
    attendee_names = [
        first_non_empty(item, "display_name", "name", "email", "open_id")
        for item in workflow_input.participants
    ]
    related_resource_titles = [resource.title for resource in workflow_input.related_resources if resource.title]
    memory_projects = extract_memory_projects(workflow_input)
    text_fields = unique_non_empty(
        [
            workflow_input.meeting_title,
            workflow_input.meeting_description,
            *attachment_titles,
            *related_resource_titles,
            str(workflow_input.memory_snapshot.get("summary", "") or ""),
            str(workflow_input.memory_snapshot.get("last_focus", "") or ""),
        ]
    )
    business_entities = collect_entities(
        workflow_input.meeting_title,
        workflow_input.meeting_description,
        attachment_titles,
        related_resource_titles,
    )
    candidate_projects = score_candidate_projects(
        workflow_input=workflow_input,
        memory_projects=memory_projects,
        text_fields=text_fields,
        attendee_names=attendee_names,
    )
    top_project = candidate_projects[0] if candidate_projects else None

    topic_parts = unique_topic_parts(
        top_project.name if top_project and top_project.score >= 0.35 else "",
        infer_topic_phrase(workflow_input.meeting_title, workflow_input.meeting_description),
        *business_entities[:3],
    )
    topic = " / ".join(topic_parts[:3])
    if not topic:
        topic = workflow_input.project_id or "待确认会议主题"

    missing_context: list[str] = []
    if not workflow_input.meeting_title:
        missing_context.append("meeting_title")
    if is_weak_meeting_title(workflow_input.meeting_title) and not attachment_titles and not related_resource_titles:
        missing_context.append("topic_evidence")
    if not workflow_input.participants:
        missing_context.append("participants")
    if not candidate_projects and workflow_input.project_id:
        missing_context.append("project_memory")

    confidence = 0.20
    if workflow_input.meeting_title and not is_weak_meeting_title(workflow_input.meeting_title):
        confidence += 0.25
    elif workflow_input.meeting_title:
        confidence += 0.10
    if workflow_input.meeting_description:
        confidence += 0.12
    if attachment_titles or related_resource_titles:
        confidence += 0.18
    if attendee_names:
        confidence += 0.10
    if top_project:
        confidence += min(top_project.score, 0.25)
    if workflow_input.memory_snapshot:
        confidence += 0.08
    confidence = min(confidence, 0.95)
    if "topic_evidence" in missing_context:
        confidence = min(confidence, 0.55)

    query_hints = unique_non_empty(
        [
            topic,
            top_project.name if top_project else "",
            workflow_input.project_id,
            *business_entities,
            *attachment_titles,
            *related_resource_titles,
        ]
    )
    reason = build_topic_reason(top_project, business_entities, missing_context)
    return MeetingTopicSignal(
        topic=topic,
        candidate_projects=candidate_projects,
        business_entities=business_entities,
        attendee_signals=unique_non_empty(attendee_names),
        confidence=confidence,
        missing_context=unique_non_empty(missing_context),
        query_hints=query_hints,
        needs_confirmation=confidence < 0.60 or bool(missing_context),
        reason=reason,
    )


def extract_memory_projects(workflow_input: PreMeetingBriefInput) -> list[dict[str, Any]]:
    """从项目记忆里读取候选项目配置。

    兼容当前轻量 JSON 结构：既支持单项目记忆，也支持 `projects` /
    `related_projects` 列表。字段不存在时会用 `project_id` 生成一个候选。
    """

    memory = workflow_input.memory_snapshot
    raw_projects: list[Any] = []
    for key in ("projects", "related_projects", "candidate_projects"):
        value = memory.get(key)
        if isinstance(value, list):
            raw_projects.extend(value)

    projects: list[dict[str, Any]] = []
    for item in raw_projects:
        if isinstance(item, dict):
            projects.append(item)
        elif item:
            projects.append({"name": str(item), "project_id": str(item)})

    current_project = {
        "project_id": memory.get("project_id") or workflow_input.project_id,
        "name": memory.get("project_name") or memory.get("name") or workflow_input.project_id,
        "aliases": memory.get("aliases") or memory.get("project_aliases") or [],
        "keywords": memory.get("keywords") or memory.get("key_entities") or [],
        "owners": memory.get("owners") or memory.get("core_members") or [],
    }
    if current_project["project_id"] or current_project["name"]:
        projects.append(current_project)
    return dedupe_project_dicts(projects)


def score_candidate_projects(
    workflow_input: PreMeetingBriefInput,
    memory_projects: list[dict[str, Any]],
    text_fields: list[str],
    attendee_names: list[str],
) -> list[CandidateProject]:
    """根据显式文本、项目记忆和参会人线索给候选项目打分。"""

    candidates: list[CandidateProject] = []
    haystack = "\n".join(text_fields).lower()
    attendees_text = "\n".join(attendee_names).lower()
    for project in memory_projects:
        project_id = str(project.get("project_id") or project.get("id") or project.get("key") or "").strip()
        name = str(project.get("name") or project.get("project_name") or project_id).strip()
        aliases = normalize_string_list(project.get("aliases") or project.get("project_aliases") or [])
        keywords = normalize_string_list(project.get("keywords") or project.get("key_entities") or [])
        owners = normalize_string_list(project.get("owners") or project.get("core_members") or [])

        score = 0.0
        matched: list[str] = []
        for label, weight in [(name, 0.35), (project_id, 0.25)]:
            if label and label.lower() in haystack:
                score += weight
                matched.append(label)
        for alias in aliases:
            if alias.lower() in haystack:
                score += 0.25
                matched.append(alias)
        for keyword in keywords:
            if keyword.lower() in haystack:
                score += 0.12
                matched.append(keyword)
        for owner in owners:
            if owner.lower() in attendees_text:
                score += 0.08
                matched.append(f"参会人:{owner}")
        if project_id and project_id == workflow_input.project_id:
            score += 0.10
            matched.append(f"project_id:{project_id}")
        if score <= 0:
            continue
        candidates.append(
            CandidateProject(
                project_id=project_id or name,
                name=name or project_id,
                score=round(min(score, 0.95), 3),
                matched_signals=unique_non_empty(matched),
                source="memory",
            )
        )

    return sorted(candidates, key=lambda item: item.score, reverse=True)


def infer_topic_phrase(meeting_title: str, meeting_description: str) -> str:
    """从标题和描述中提取一个可读主题短语。"""

    title = meeting_title.strip()
    if title and not is_weak_meeting_title(title):
        return title
    description = meeting_description.strip()
    if description:
        return description[:40]
    return title


def is_weak_meeting_title(title: str) -> bool:
    """判断标题是否过短或过于泛化。"""

    normalized = title.strip().lower()
    if not normalized:
        return True
    weak_titles = {
        "同步",
        "周会",
        "例会",
        "会议",
        "讨论",
        "对齐",
        "sync",
        "weekly",
        "meeting",
        "review",
    }
    return normalized in weak_titles or len(normalized) <= 3


def build_topic_reason(
    top_project: CandidateProject | None,
    business_entities: list[str],
    missing_context: list[str],
) -> str:
    """生成主题识别解释，便于后续审计和答辩展示。"""

    parts: list[str] = []
    if top_project:
        parts.append(
            f"候选项目 {top_project.name} 命中 {', '.join(top_project.matched_signals[:5])}"
        )
    if business_entities:
        parts.append(f"识别到实体 {', '.join(business_entities[:5])}")
    if missing_context:
        parts.append(f"缺少上下文 {', '.join(missing_context)}")
    return "；".join(parts) or "仅使用默认项目和会议上下文生成低置信主题。"


def render_pre_meeting_card_payload(brief: MeetingBrief) -> PreMeetingCardPayload:
    """把 `MeetingBrief` 转成当前卡片工具可直接消费的 payload。"""

    facts = [
        {"label": "会议主题", "value": brief.topic},
        {"label": "背景摘要", "value": brief.summary},
        {"label": "置信度", "value": f"{brief.confidence:.2f}"},
    ]
    if brief.needs_confirmation:
        facts.append({"label": "状态", "value": "上下文不足，建议人工确认后再推送"})
    if brief.last_decisions:
        facts.append(
            {
                "label": "上次结论",
                "value": "；".join(item.title for item in brief.last_decisions[:3]),
            }
        )
    if brief.current_questions:
        facts.append(
            {
                "label": "当前问题",
                "value": "；".join(item.title for item in brief.current_questions[:3]),
            }
        )
    if brief.risks:
        facts.append(
            {
                "label": "风险点",
                "value": "；".join(item.title for item in brief.risks[:3]),
            }
        )
    if brief.must_read_resources:
        facts.append(
            {
                "label": "待读资料",
                "value": "；".join(item.title for item in brief.must_read_resources[:3]),
            }
        )
    if brief.possible_related_resources:
        facts.append(
            {
                "label": "可能相关资料",
                "value": "；".join(item.title for item in brief.possible_related_resources[:3]),
            }
        )
    return PreMeetingCardPayload(
        title=f"MeetFlow 会前背景卡：{brief.topic}",
        summary=brief.summary,
        facts=facts,
        source_meeting_id=brief.meeting_id,
        idempotency_key=f"pre_meeting_brief:{brief.meeting_id or brief.calendar_event_id}",
    )


def normalize_dict_list(value: Any) -> list[dict[str, Any]]:
    """把 payload 中的附件等列表统一清洗成字典列表。"""

    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            items.append(item)
        elif item:
            items.append({"title": str(item)})
    return items


def normalize_string_list(value: Any) -> list[str]:
    """把项目记忆里的字符串或列表字段统一转成字符串列表。"""

    if isinstance(value, list):
        return unique_non_empty([str(item) for item in value if item])
    if isinstance(value, str):
        return unique_non_empty([item for item in value.replace("，", ",").split(",")])
    return []


def normalize_resource_type(value: str) -> str:
    """把飞书资源类型和项目记忆字段名归一到 M3 检索类型。"""

    normalized = value.strip().lower()
    mapping = {
        "feishu_document": "doc",
        "document": "doc",
        "documents": "doc",
        "docs": "doc",
        "docx": "doc",
        "sheet": "sheet",
        "sheets": "sheet",
        "bitable": "sheet",
        "minutes": "minute",
        "minute": "minute",
        "meeting_minutes": "minute",
        "tasks": "task",
        "task": "task",
        "attachment": "doc",
        "calendar.attachment": "doc",
        "resources": "doc",
        "recent_resources": "doc",
    }
    return mapping.get(normalized, normalized or "unknown")


def estimate_freshness_score(updated_at: str) -> float:
    """根据更新时间给资源一个小的排序加权。

    支持秒级时间戳、毫秒级时间戳和常见 ISO 日期字符串。无法解析时不加分。
    """

    timestamp = parse_timestamp(updated_at)
    if timestamp <= 0:
        return 0.0
    age_days = max((int(time.time()) - timestamp) / 86400, 0)
    if age_days <= 7:
        return 0.10
    if age_days <= 30:
        return 0.07
    if age_days <= 90:
        return 0.04
    return 0.01


def parse_timestamp(value: str) -> int:
    """解析资源更新时间。"""

    text = value.strip()
    if not text:
        return 0
    if text.isdigit():
        number = int(text)
        if number > 10_000_000_000:
            return number // 1000
        return number
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(text[:19], fmt).timestamp())
        except ValueError:
            continue
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def dedupe_project_dicts(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 project_id/name 对项目候选去重。"""

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for project in projects:
        project_id = str(project.get("project_id") or project.get("id") or "").strip()
        name = str(project.get("name") or project.get("project_name") or "").strip()
        key = project_id or name
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(project)
    return result


def first_non_empty(data: dict[str, Any], *keys: str) -> str:
    """按顺序读取第一个非空字段。"""

    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        return str(value)
    return ""


def unique_non_empty(values: list[str]) -> list[str]:
    """保序去重并移除空字符串。"""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def unique_topic_parts(*values: str) -> list[str]:
    """生成可读主题片段，避免项目名和标题里的重复词反复出现。"""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        if any(lowered in item.lower() or item.lower() in lowered for item in result):
            continue
        seen.add(lowered)
        result.append(normalized)
    return result


def collect_entities(
    meeting_title: str,
    meeting_description: str,
    attachment_titles: list[str],
    related_resource_titles: list[str],
) -> list[str]:
    """提取首版实体线索。

    T3.2 会升级为更完整的主题识别。这里先用轻量规则保留项目名、版本号、
    文档标题等显式信号，确保 T3.1 的结构可以被后续检索阶段消费。
    """

    raw_texts = [meeting_title, meeting_description, *attachment_titles, *related_resource_titles]
    candidates: list[str] = []
    for text in raw_texts:
        for token in str(text).replace("，", " ").replace(",", " ").split():
            cleaned = token.strip("：:;；、()（）[]【】")
            if len(cleaned) >= 2:
                candidates.append(cleaned)
    return unique_non_empty(candidates)
