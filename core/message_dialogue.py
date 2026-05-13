from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from adapters.feishu_tools import create_feishu_tool_registry
from config.loader import Settings
from core.knowledge import KnowledgeIndexStore
from core.llm import GenerationSettings, create_llm_provider
from core.logging import get_logger
from core.models import AgentMessage, AgentToolCall, Event, WorkflowContext, WorkflowResult
from core.observability import emit_structured_event, safe_error_message
from core.policy import AgentPolicy
from core.storage import MeetFlowStorage


SUMMARY_KEYWORDS = ("总结", "梳理", "整理", "归纳", "概括", "回顾", "复盘")
BLOCKED_INTENT_KEYWORDS = (
    "创建",
    "新建",
    "建任务",
    "创建任务",
    "发消息",
    "发送",
    "提醒",
    "查日程",
    "查询日程",
    "会议安排",
    "预约",
    "预定",
    "删除",
    "修改",
    "更新",
    "审批",
    "打卡",
    "翻译",
    "写代码",
    "天气",
    "新闻",
    "你好",
    "您好",
    "hello",
    "hi",
    "在吗",
    "你是谁",
    "讲个笑话",
)
QUESTION_MARKERS = ("?", "？", "吗", "么", "谁", "哪里", "为什么", "怎么", "能不能", "是否")
MAX_REPLY_CHARS = 1800
MAX_LLM_EVIDENCE_CHARS = 3200


@dataclass(slots=True)
class MessageDialogueRequest:
    """群里 @ 机器人后归一化出的主动对话请求。"""

    event_type: str
    event_id: str
    message_id: str
    chat_id: str
    chat_type: str
    sender_open_id: str
    message_type: str
    text: str
    mentions: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MessageDialogueResult:
    """主动对话入口的处理结果。"""

    status: str
    reply_text: str = ""
    topic: str = ""
    sent: bool = False
    send_result: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    trace_id: str = "-"
    payload: dict[str, Any] = field(default_factory=dict)


def is_message_receive_event(payload: dict[str, Any]) -> bool:
    """判断 payload 是否是飞书消息接收事件。"""

    event_type = extract_event_type(payload)
    return event_type in {"im.message.receive_v1", "message.receive", "im.message.receive"}


def handle_message_dialogue_event(
    *,
    payload: dict[str, Any],
    settings: Settings,
    storage: MeetFlowStorage,
    feishu_client: Any,
    policy: AgentPolicy,
    allow_write: bool = False,
    source: str = "http",
) -> MessageDialogueResult:
    """处理群 @ 机器人主动请求。

    这个入口只服务“从 RAG 中总结主题”这一件事。它不进入通用聊天，
    也不让 LLM 自由选择写工具，从而降低临近提交前引入回归的风险。
    """

    logger = get_logger("meetflow.message_dialogue")
    request = parse_message_dialogue_request(payload)
    trace_id = build_message_trace_id(request)
    emit_structured_event(
        "message_dialogue_received",
        trace_id=trace_id,
        source=source,
        feishu_event_type=request.event_type,
        message_id=request.message_id,
        chat_id=request.chat_id,
        chat_type=request.chat_type,
        message_type=request.message_type,
        status="parsed",
    )

    result = build_message_dialogue_reply(
        request=request,
        settings=settings,
        storage=storage,
        trace_id=trace_id,
    )
    if result.status == "ignored":
        return result

    if not request.chat_id:
        result.status = "blocked"
        result.reason = "缺少 chat_id，无法回复群聊。"
        result.reply_text = result.reply_text or "MeetFlow 无法识别当前群聊，暂时不能回复。"
        save_message_dialogue_result(storage, result)
        return result

    send_result = send_message_dialogue_reply(
        request=request,
        result=result,
        settings=settings,
        storage=storage,
        feishu_client=feishu_client,
        policy=policy,
        allow_write=allow_write,
        trace_id=trace_id,
    )
    result.sent = send_result.status == "sent"
    result.send_result = send_result.payload
    if send_result.status != "sent":
        result.status = "send_blocked" if send_result.status == "blocked" else "send_failed"
        result.reason = send_result.reason
        logger.warning(
            "主动对话回复未发送 trace_id=%s status=%s reason=%s",
            trace_id,
            result.status,
            result.reason,
        )
    save_message_dialogue_result(storage, result)
    return result


def parse_message_dialogue_request(payload: dict[str, Any]) -> MessageDialogueRequest:
    """从飞书消息事件中提取文本、群聊和发送人。"""

    header = as_dict(payload.get("header"))
    event = as_dict(payload.get("event"))
    message = as_dict(event.get("message"))
    sender = as_dict(event.get("sender"))
    sender_id = as_dict(sender.get("sender_id"))
    content = parse_message_content(message.get("content"))
    mentions = normalize_mentions(message.get("mentions"))
    text = strip_mentions(str(content.get("text") or ""), mentions)
    return MessageDialogueRequest(
        event_type=extract_event_type(payload),
        event_id=str(header.get("event_id") or payload.get("event_id") or ""),
        message_id=str(message.get("message_id") or ""),
        chat_id=str(message.get("chat_id") or ""),
        chat_type=str(message.get("chat_type") or ""),
        sender_open_id=str(sender_id.get("open_id") or sender_id.get("user_id") or ""),
        message_type=str(message.get("message_type") or content.get("message_type") or ""),
        text=normalize_space(text),
        mentions=mentions,
        raw_payload=payload,
    )


def build_message_dialogue_reply(
    *,
    request: MessageDialogueRequest,
    settings: Settings,
    storage: MeetFlowStorage,
    trace_id: str,
) -> MessageDialogueResult:
    """根据意图门禁和 RAG 检索结果构造回复文本。"""

    if request.chat_type and request.chat_type != "group":
        return MessageDialogueResult(status="ignored", trace_id=trace_id, reason="非群聊消息不处理。")
    if not request.mentions:
        return MessageDialogueResult(status="ignored", trace_id=trace_id, reason="未 @ 机器人，不主动响应。")
    if request.message_type and request.message_type != "text":
        reply = "MeetFlow 目前只支持群里 @ 我后用文本主题做 RAG 总结。"
        return MessageDialogueResult(status="rejected", reply_text=reply, trace_id=trace_id, reason="非文本消息。")

    intent = classify_summary_intent(request.text)
    if intent["status"] != "allowed":
        reply = (
            "MeetFlow 是会议知识闭环 Agent，目前群聊主动对话只支持“基于 RAG 总结主题”。"
            "请用类似“@MeetFlow 总结 D7 RAG 评测”的格式重试。"
        )
        return MessageDialogueResult(
            status="rejected",
            reply_text=reply,
            trace_id=trace_id,
            reason=str(intent["reason"]),
            payload={"intent": intent},
        )

    topic = str(intent["topic"])
    knowledge_store = KnowledgeIndexStore(
        settings.storage,
        embedding_settings=settings.embedding,
        reranker_settings=settings.reranker,
        search_settings=settings.knowledge_search,
    )
    search_result = knowledge_store.search_chunks(
        query=topic,
        project_id="meetflow",
        top_k=20,
        top_n=5,
        evidence_token_budget=900,
        max_snippet_tokens=160,
    )
    search_payload = search_result.to_dict()
    fallback_reply = build_rag_summary_reply(topic=topic, search_result=search_payload)
    reply, polish_payload = build_polished_rag_summary_reply(
        topic=topic,
        search_result=search_payload,
        fallback_reply=fallback_reply,
        settings=settings,
        trace_id=trace_id,
    )
    status = "answered" if search_result.hits else "no_evidence"
    return MessageDialogueResult(
        status=status,
        reply_text=reply,
        topic=topic,
        trace_id=trace_id,
        payload={
            "intent": intent,
            "rag_search": {
                "hit_count": len(search_result.hits),
                "low_confidence": search_result.low_confidence,
                "reason": search_result.reason,
                "hits": [hit.to_dict() for hit in search_result.hits],
            },
            "llm_polish": polish_payload,
        },
    )


def classify_summary_intent(text: str) -> dict[str, Any]:
    """只放行 RAG 总结意图，拒绝通用聊天和外部副作用请求。"""

    normalized = normalize_space(text)
    if not normalized:
        return {"status": "rejected", "reason": "缺少主题", "topic": ""}
    if any(keyword in normalized for keyword in BLOCKED_INTENT_KEYWORDS):
        return {"status": "rejected", "reason": "包含非总结类动作", "topic": ""}

    has_summary_keyword = any(keyword in normalized for keyword in SUMMARY_KEYWORDS)
    if not has_summary_keyword and any(marker in normalized for marker in QUESTION_MARKERS):
        return {"status": "rejected", "reason": "疑似通用问答", "topic": ""}

    topic = extract_summary_topic(normalized, has_summary_keyword=has_summary_keyword)
    if len(topic) < 2:
        return {"status": "rejected", "reason": "主题过短", "topic": topic}
    return {"status": "allowed", "reason": "summary_topic", "topic": topic}


def extract_summary_topic(text: str, has_summary_keyword: bool) -> str:
    """从用户文本中提取要总结的主题。"""

    topic = text
    if has_summary_keyword:
        pattern = "|".join(re.escape(keyword) for keyword in SUMMARY_KEYWORDS)
        topic = re.sub(rf"^(请|帮我|麻烦|麻烦你|请你)?({pattern})(一下|下)?", "", topic).strip()
    topic = re.sub(r"^(一下|下|关于|有关|主题|内容|资料|：|:)+", "", topic).strip()
    topic = re.sub(r"(的)?(相关)?(内容|资料)?$", "", topic).strip()
    return normalize_space(topic)


def build_rag_summary_reply(topic: str, search_result: dict[str, Any]) -> str:
    """把 RAG 检索结果压成适合飞书文本消息的总结。"""

    hits = list(search_result.get("hits") or [])
    if not hits:
        reason = str(search_result.get("reason") or "RAG 未召回到相关资料。")
        return truncate_reply(
            f"MeetFlow RAG 总结：{topic}\n"
            f"没有在已索引的会议知识中找到足够相关的内容。\n"
            f"检索说明：{reason}\n"
            "我不会基于未检索到的资料编造结论。"
        )

    bullets = build_summary_bullets(topic, hits)
    evidence_lines = build_evidence_lines(hits)

    confidence_note = "低置信度，请人工复核。" if search_result.get("low_confidence") else "基于已索引证据生成。"
    reply = (
        f"MeetFlow RAG 总结：{topic}\n"
        "要点：\n"
        + "\n".join(f"- {line}" for line in bullets)
        + "\n证据：\n"
        + "\n".join(evidence_lines)
        + f"\n说明：{confidence_note}"
    )
    return truncate_reply(reply)


def build_polished_rag_summary_reply(
    *,
    topic: str,
    search_result: dict[str, Any],
    fallback_reply: str,
    settings: Settings,
    trace_id: str,
) -> tuple[str, dict[str, Any]]:
    """在证据边界内调用 LLM 润色 RAG 总结，失败时回退到抽取式回复。

    群聊主动入口不能退化为通用聊天机器人，所以这里不暴露任何工具，也不
    让模型决定证据来源。LLM 只负责把已召回片段整理成更自然的结论和要点，
    最终证据列表仍由本地代码确定性生成。
    """

    hits = list(search_result.get("hits") or [])
    if not hits:
        return fallback_reply, {"enabled": False, "status": "skipped", "reason": "no_evidence"}

    llm_settings = getattr(settings, "llm", None)
    if llm_settings is None:
        return fallback_reply, {"enabled": False, "status": "skipped", "reason": "missing_llm_settings"}

    provider_name = str(getattr(llm_settings, "provider", "") or "").strip().lower()
    if provider_name in {"", "dry-run", "dry_run", "mock"}:
        return fallback_reply, {"enabled": False, "status": "skipped", "reason": "non_live_llm_provider"}

    try:
        provider = create_llm_provider(llm_settings)
        response = provider.chat(
            messages=build_rag_polish_messages(topic=topic, search_result=search_result),
            tools=None,
            settings=GenerationSettings(
                model=str(getattr(llm_settings, "model", "") or ""),
                temperature=0.1,
                max_tokens=min(int(getattr(llm_settings, "max_tokens", 1200) or 1200), 1200),
                reasoning_effort=str(getattr(llm_settings, "reasoning_effort", "") or ""),
                timeout_seconds=30,
            ),
        )
        polished_body = normalize_polished_summary(response.content)
        if not polished_body:
            return fallback_reply, {"enabled": True, "status": "fallback", "reason": "empty_llm_response"}
        reply = compose_polished_rag_reply(
            topic=topic,
            polished_body=polished_body,
            search_result=search_result,
        )
        emit_structured_event(
            "message_dialogue_llm_polish",
            trace_id=trace_id,
            status="success",
            provider=provider_name,
            model=response.model or str(getattr(llm_settings, "model", "") or ""),
            finish_reason=response.finish_reason,
            usage=response.usage,
        )
        return reply, {
            "enabled": True,
            "status": "success",
            "provider": provider_name,
            "model": response.model or str(getattr(llm_settings, "model", "") or ""),
            "finish_reason": response.finish_reason,
        }
    except Exception as error:
        emit_structured_event(
            "message_dialogue_llm_polish",
            trace_id=trace_id,
            status="fallback",
            provider=provider_name,
            error_type=error.__class__.__name__,
            error_message=safe_error_message(error),
        )
        return fallback_reply, {
            "enabled": True,
            "status": "fallback",
            "reason": safe_error_message(error),
            "error_type": error.__class__.__name__,
        }


def build_rag_polish_messages(topic: str, search_result: dict[str, Any]) -> list[AgentMessage]:
    """构造受约束的 RAG 润色提示词。"""

    evidence_payload = build_llm_evidence_payload(search_result)
    system_prompt = (
        "你是 MeetFlow 的会议知识总结器，只能基于用户提供的 RAG 证据回答。"
        "不要使用外部知识，不要编造数字、人名、结论或来源；证据不足时必须明确写“证据不足”。"
        "你不是通用聊天机器人，只做会议知识总结。"
        "输出中文，最多 6 行，格式必须为：\n"
        "结论：...\n"
        "要点：\n"
        "- ...\n"
        "- ...\n"
        "待确认：..."
    )
    user_prompt = (
        f"主题：{topic}\n"
        "请把下面证据整理成适合发到飞书群里的简洁总结。"
        "每条要点都必须能在证据中找到依据，不要输出证据列表，证据列表会由系统追加。\n"
        f"RAG 证据：\n{json.dumps(evidence_payload, ensure_ascii=False, indent=2)}"
    )
    return [
        AgentMessage(role="system", content=system_prompt),
        AgentMessage(role="user", content=user_prompt),
    ]


def build_llm_evidence_payload(search_result: dict[str, Any]) -> list[dict[str, Any]]:
    """把检索命中压缩成 LLM 可读但不含敏感冗余的证据。"""

    payload: list[dict[str, Any]] = []
    total_chars = 0
    for index, hit in enumerate(list(search_result.get("hits") or [])[:8], start=1):
        snippet = normalize_space(str(hit.get("snippet") or ""))[:700]
        if not snippet:
            continue
        total_chars += len(snippet)
        if total_chars > MAX_LLM_EVIDENCE_CHARS:
            break
        payload.append(
            {
                "id": f"E{index}",
                "source_type": str(hit.get("source_type") or "unknown"),
                "title": str(hit.get("title") or "未命名资料"),
                "snippet": snippet,
            }
        )
    return payload


def normalize_polished_summary(content: str) -> str:
    """清理 LLM 回复，避免把模型客套话或证据列表混入最终消息。"""

    text = normalize_space_preserve_lines(content)
    if not text:
        return ""
    text = re.sub(r"^MeetFlow\s*RAG\s*总结[：:].*?\n", "", text).strip()
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^(证据|来源|参考)[：:]", line):
            break
        if re.match(r"^\d+\.\s*\[", line):
            break
        lines.append(line)
        if len(lines) >= 7:
            break
    return "\n".join(lines).strip()


def compose_polished_rag_reply(
    *,
    topic: str,
    polished_body: str,
    search_result: dict[str, Any],
) -> str:
    """拼接 LLM 润色正文和确定性证据列表。"""

    hits = list(search_result.get("hits") or [])
    evidence_lines = build_evidence_lines(hits)
    confidence_note = "低置信度，请人工复核。" if search_result.get("low_confidence") else "基于已索引证据生成，正文由 LLM 在证据范围内润色。"
    reply = (
        f"MeetFlow RAG 总结：{topic}\n"
        f"{polished_body}\n"
        "证据：\n"
        + "\n".join(evidence_lines)
        + f"\n说明：{confidence_note}"
    )
    return truncate_reply(reply)


def build_summary_bullets(topic: str, hits: list[dict[str, Any]]) -> list[str]:
    """从证据片段中抽取去重后的要点。"""

    query_terms = [term for term in re.split(r"\s+", topic) if term]
    bullets: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        snippet = normalize_space(str(hit.get("snippet") or ""))
        if not snippet:
            continue
        for sentence in pick_relevant_sentences(snippet, query_terms):
            sentence = sentence[:180].strip()
            key = re.sub(r"\W+", "", sentence)
            if not key or key in seen:
                continue
            seen.add(key)
            bullets.append(sentence)
            if len(bullets) >= 4:
                return bullets
    return bullets or ["已找到相关资料，但片段过短；请查看下方证据来源继续核验。"]


def pick_relevant_sentences(snippet: str, query_terms: list[str]) -> list[str]:
    """优先选择命中主题词且信息量足够的句子。"""

    candidates = split_summary_candidates(snippet)
    if not candidates:
        return []
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(candidates):
        if is_low_information_sentence(sentence):
            continue
        term_hits = sum(1 for term in query_terms if term and term in sentence)
        scored.append((term_hits, -index, sentence))
    scored.sort(reverse=True)
    return [sentence for _, _, sentence in scored[:3]]


def split_summary_candidates(snippet: str) -> list[str]:
    """把 evidence snippet 拆成候选要点，并过滤空白。"""

    normalized = normalize_space(snippet)
    raw_items = re.split(r"(?<=[。！？!?；;])|(?:\n+)|(?:\s{2,})|(?:[•·])", normalized)
    candidates: list[str] = []
    for item in raw_items:
        sentence = normalize_space(item).strip(" -:：")
        if sentence:
            candidates.append(sentence)
    return candidates


def is_low_information_sentence(sentence: str) -> bool:
    """过滤目录标题、字段名和过短片段，避免回复只剩“风险/当前问题”。"""

    text = normalize_space(sentence).strip(" -:：")
    if not text:
        return True
    compact = re.sub(r"[\W_]+", "", text)
    if len(compact) < 8:
        return True
    heading_words = {
        "上次结论",
        "当前问题",
        "风险",
        "背景",
        "目标",
        "结论",
        "问题",
        "建议",
        "行动项",
        "证据",
        "摘要",
    }
    if compact in heading_words:
        return True
    if re.fullmatch(r"第?[一二三四五六七八九十0-9]+[章节条点]?", compact):
        return True
    return False


def build_evidence_lines(hits: list[dict[str, Any]], limit: int = 5) -> list[str]:
    """按文档合并证据来源，避免同一文档重复刷屏。"""

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for hit in hits:
        title = str(hit.get("title") or "未命名资料").strip()
        source_type = str(hit.get("source_type") or "unknown").strip()
        source_url = str(hit.get("source_url") or "").strip()
        ref_id = str(hit.get("ref_id") or "").strip()
        key = (source_type, title, source_url or ref_id)
        item = grouped.setdefault(
            key,
            {
                "source_type": source_type,
                "title": title,
                "source_url": source_url,
                "ref_id": ref_id,
                "count": 0,
            },
        )
        item["count"] += 1

    evidence_lines: list[str] = []
    for index, item in enumerate(list(grouped.values())[:limit], start=1):
        suffix = f" {item['source_url']}" if item["source_url"] else f" ref={item['ref_id']}"
        count_text = f"（命中 {item['count']} 个片段）" if item["count"] > 1 else ""
        evidence_lines.append(f"{index}. [{item['source_type']}] {item['title']}{count_text}{suffix}")
    return evidence_lines


@dataclass(slots=True)
class ReplySendResult:
    """回复发送阶段的内部结果。"""

    status: str
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def send_message_dialogue_reply(
    *,
    request: MessageDialogueRequest,
    result: MessageDialogueResult,
    settings: Settings,
    storage: MeetFlowStorage,
    feishu_client: Any,
    policy: AgentPolicy,
    allow_write: bool,
    trace_id: str,
) -> ReplySendResult:
    """通过 im.send_text 工具和 AgentPolicy 发送群回复。"""

    registry = create_feishu_tool_registry(
        client=feishu_client,
        default_chat_id=getattr(settings.feishu, "default_chat_id", ""),
    )
    tool = registry.get("im.send_text")
    idempotency_key = build_message_idempotency_key(request)
    arguments = {
        "text": result.reply_text,
        "receive_id": request.chat_id,
        "receive_id_type": "chat_id",
        "idempotency_key": idempotency_key,
        "identity": "tenant",
    }
    context = build_message_workflow_context(request=request, trace_id=trace_id, idempotency_key=idempotency_key)
    tool_call = AgentToolCall(
        call_id=f"message_dialogue_reply:{request.message_id or int(time.time())}",
        tool_name=tool.llm_name,
        arguments=arguments,
    )
    decision = policy.authorize_tool_call(
        context=context,
        tool=tool,
        tool_call=tool_call,
        allow_write=allow_write,
        storage=storage,
    )
    if not decision.is_allowed():
        return ReplySendResult(status="blocked", reason=decision.reason, payload={"policy_decision": decision.to_dict()})

    tool_call.arguments = decision.patched_arguments
    tool_result = registry.execute(tool_call)
    if not tool_result.is_success():
        return ReplySendResult(status="failed", reason=tool_result.error_message, payload=tool_result.to_dict())
    storage.record_idempotency_key(
        idempotency_key=idempotency_key,
        workflow_name="message_rag_summary",
        trace_id=trace_id,
    )
    return ReplySendResult(status="sent", payload=tool_result.to_dict())


def build_message_workflow_context(
    *,
    request: MessageDialogueRequest,
    trace_id: str,
    idempotency_key: str,
) -> WorkflowContext:
    """构造最小 WorkflowContext，让写回复仍可经过 AgentPolicy。"""

    event = Event(
        event_id=request.event_id,
        event_type=request.event_type,
        event_time=str(int(time.time())),
        source="message_dialogue",
        actor=request.sender_open_id,
        payload=request.raw_payload,
        trace_id=trace_id,
    )
    return WorkflowContext(
        workflow_type="message_rag_summary",
        trace_id=trace_id,
        event=event,
        project_id="meetflow",
        raw_context={
            "decision": {"idempotency_key": idempotency_key},
            "message_dialogue": {
                "message_id": request.message_id,
                "chat_id": request.chat_id,
                "sender_open_id": request.sender_open_id,
            },
        },
    )


def save_message_dialogue_result(storage: MeetFlowStorage, result: MessageDialogueResult) -> None:
    """保存主动对话结果，便于演示时回查。"""

    storage.save_workflow_result(
        WorkflowResult(
            trace_id=result.trace_id,
            workflow_name="message_rag_summary",
            status=result.status,
            summary=result.reply_text[:160],
            payload={
                "topic": result.topic,
                "sent": result.sent,
                "reason": result.reason,
                "send_result": result.send_result,
                "payload": result.payload,
            },
            created_at=int(time.time()),
        )
    )


def build_message_idempotency_key(request: MessageDialogueRequest) -> str:
    """基于飞书消息 ID 构造稳定回复幂等键。"""

    base = request.message_id or request.event_id or f"{request.chat_id}:{request.text}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"message_rag_summary:{digest}"


def build_message_trace_id(request: MessageDialogueRequest) -> str:
    """为主动对话生成 trace_id。"""

    digest = hashlib.sha1((request.event_id or request.message_id or request.text).encode("utf-8")).hexdigest()[:12]
    return f"message_rag_summary:{digest}"


def extract_event_type(payload: dict[str, Any]) -> str:
    """读取飞书事件类型。"""

    header = as_dict(payload.get("header"))
    return str(header.get("event_type") or payload.get("type") or payload.get("event_type") or "")


def parse_message_content(raw_content: Any) -> dict[str, Any]:
    """兼容飞书 text content 的 JSON 字符串和字典形态。"""

    if isinstance(raw_content, dict):
        return dict(raw_content)
    if isinstance(raw_content, str) and raw_content.strip():
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return {"text": raw_content}
        if isinstance(parsed, dict):
            return parsed
    return {}


def normalize_mentions(raw_mentions: Any) -> list[dict[str, Any]]:
    """归一化飞书 mentions 字段。"""

    if not isinstance(raw_mentions, list):
        return []
    return [item for item in raw_mentions if isinstance(item, dict)]


def strip_mentions(text: str, mentions: list[dict[str, Any]]) -> str:
    """移除飞书文本里的 @ 占位符和展示名。"""

    cleaned = text
    for mention in mentions:
        key = str(mention.get("key") or "").strip()
        name = str(mention.get("name") or "").strip()
        if key:
            cleaned = cleaned.replace(key, " ")
        if name:
            cleaned = cleaned.replace(f"@{name}", " ")
    cleaned = re.sub(r"<at[^>]*>.*?</at>", " ", cleaned)
    cleaned = re.sub(r"@\S+", " ", cleaned)
    return normalize_space(cleaned)


def normalize_space(text: str) -> str:
    """压缩空白，保留中文内容。"""

    return re.sub(r"\s+", " ", str(text or "").strip())


def normalize_space_preserve_lines(text: str) -> str:
    """压缩每行空白但保留换行，便于控制 LLM 输出结构。"""

    lines = [normalize_space(line) for line in str(text or "").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def truncate_reply(text: str) -> str:
    """限制回复长度，避免群消息过长。"""

    if len(text) <= MAX_REPLY_CHARS:
        return text
    return text[: MAX_REPLY_CHARS - 20].rstrip() + "\n...（已截断）"


def as_dict(value: Any) -> dict[str, Any]:
    """安全转换 dict。"""

    return value if isinstance(value, dict) else {}


def safe_result_payload(result: MessageDialogueResult) -> dict[str, Any]:
    """构造回调响应体，不暴露过长内容。"""

    return {
        "status": result.status,
        "sent": result.sent,
        "topic": result.topic,
        "reason": result.reason,
        "trace_id": result.trace_id,
        "reply_preview": safe_error_message(result.reply_text[:240]) if result.reply_text else "",
    }
