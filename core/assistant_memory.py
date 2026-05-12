from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from core.models import AgentToolCall, BaseModel, WorkflowContext


@dataclass(slots=True)
class AssistantSession(BaseModel):
    """一次可延续的助手会话。

    MeetFlow 的业务会话不是闲聊历史，而是“围绕同一用户、群、会议和待办”
    可以继续补字段的工作现场。后续用户说“负责人改成我”时，需要先回到
    这个现场，再判断要恢复哪个 pending action。
    """

    session_id: str
    actor: str = ""
    source: str = ""
    workflow_type: str = ""
    status: str = "active"
    memory: dict[str, Any] = field(default_factory=dict)
    last_trace_id: str = ""
    created_at: int = 0
    updated_at: int = 0


@dataclass(slots=True)
class PendingAction(BaseModel):
    """被 Policy 拦截后等待用户补充或确认的动作。"""

    action_id: str
    session_id: str
    trace_id: str
    workflow_type: str
    tool_name: str
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    status: str = "pending"
    policy_reason: str = ""
    idempotency_key: str = ""
    recovery_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    updated_at: int = 0


@dataclass(slots=True)
class ClarificationQuestion(BaseModel):
    """围绕 pending action 生成的一条澄清问题。"""

    question_id: str
    action_id: str
    session_id: str
    question: str
    missing_fields: list[str] = field(default_factory=list)
    status: str = "open"
    answer: str = ""
    created_at: int = 0
    answered_at: int = 0


def build_assistant_session(
    *,
    actor: str,
    source: str,
    workflow_type: str,
    payload: dict[str, Any],
    trace_id: str,
    now: int | None = None,
) -> AssistantSession:
    """根据输入构造稳定 session。

    优先复用显式 `assistant_session_id/session_id`。没有显式 ID 时，使用用户、
    来源、会议、妙记和任务等业务维度生成短哈希，让同一现场的补字段消息能
    自动命中最近 pending action。
    """

    created_at = int(now or time.time())
    explicit = first_non_empty(payload, "assistant_session_id", "session_id", "conversation_id")
    if explicit:
        session_id = explicit
    else:
        stable_parts = [
            actor,
            source,
            workflow_type,
            first_non_empty(payload, "chat_id", "receive_id", "group_id"),
            first_non_empty(payload, "meeting_id", "calendar_event_id", "event_id"),
            first_non_empty(payload, "minute_token", "minute_id", "task_id"),
        ]
        digest = hashlib.sha1("|".join(stable_parts).encode("utf-8")).hexdigest()[:16]
        session_id = f"asst_{digest}"
    return AssistantSession(
        session_id=session_id,
        actor=actor,
        source=source,
        workflow_type=workflow_type,
        memory={
            "chat_id": first_non_empty(payload, "chat_id", "receive_id", "group_id"),
            "meeting_id": first_non_empty(payload, "meeting_id", "calendar_event_id", "event_id"),
            "minute_token": first_non_empty(payload, "minute_token", "minute_id"),
            "task_id": first_non_empty(payload, "task_id", "guid"),
            "project_id": first_non_empty(payload, "project_id"),
        },
        last_trace_id=trace_id,
        created_at=created_at,
        updated_at=created_at,
    )


def create_pending_action_from_policy_decision(
    *,
    context: WorkflowContext,
    session_id: str,
    tool_name: str,
    tool_arguments: dict[str, Any],
    decision: Any,
    now: int | None = None,
) -> PendingAction:
    """把一次 `needs_confirmation` 策略决策转换成可恢复动作。"""

    created_at = int(now or time.time())
    digest_source = {
        "session_id": session_id,
        "trace_id": context.trace_id,
        "tool_name": tool_name,
        "idempotency_key": decision.idempotency_key,
        "arguments": tool_arguments,
    }
    digest = hashlib.sha1(repr(sorted(digest_source.items())).encode("utf-8")).hexdigest()[:16]
    action = PendingAction(
        action_id=f"pa_{digest}",
        session_id=session_id,
        trace_id=context.trace_id,
        workflow_type=context.workflow_type,
        tool_name=tool_name,
        tool_arguments=dict(decision.patched_arguments or tool_arguments or {}),
        missing_fields=list(decision.required_fields),
        status="pending",
        policy_reason=decision.reason,
        idempotency_key=decision.idempotency_key,
        metadata={
            "meeting_id": context.meeting_id,
            "calendar_event_id": context.calendar_event_id,
            "minute_token": context.minute_token,
            "project_id": context.project_id,
            "policy_decision": decision.to_dict(),
        },
        created_at=created_at,
        updated_at=created_at,
    )
    action.recovery_prompt = build_recovery_prompt(action)
    return action


def build_clarification_question(action: PendingAction, now: int | None = None) -> ClarificationQuestion:
    """为 pending action 生成面向用户的澄清问题。"""

    created_at = int(now or time.time())
    digest = hashlib.sha1(f"{action.action_id}:{','.join(action.missing_fields)}".encode("utf-8")).hexdigest()[:12]
    return ClarificationQuestion(
        question_id=f"cq_{digest}",
        action_id=action.action_id,
        session_id=action.session_id,
        question=action.recovery_prompt,
        missing_fields=list(action.missing_fields),
        status="open",
        created_at=created_at,
        answered_at=0,
    )


def apply_user_reply_to_pending_action(
    action: PendingAction,
    reply: str,
    *,
    actor_open_id: str = "",
    now: int | None = None,
) -> PendingAction:
    """把用户补充文本合并回 pending action。

    这里只做安全的字段补全，不直接产生外部副作用。补齐后仍要回到
    `AgentPolicy` 和 `ToolRegistry`，因为用户补字段不等于绕过安全审核。
    """

    patched = PendingAction(**action.to_dict())
    arguments = dict(patched.tool_arguments)
    reply_text = str(reply or "").strip()
    if not reply_text:
        return patched

    owner_text = extract_owner_text(reply_text)
    if "assignee_ids" in patched.missing_fields and owner_text:
        if owner_text in {"我", "本人", "自己"} and actor_open_id:
            arguments["assignee_ids"] = [actor_open_id]
            patched.metadata["owner_resolution"] = {"source": "current_user", "open_id": actor_open_id}
        else:
            arguments["owner_text"] = owner_text
            patched.metadata["owner_resolution"] = {
                "source": "needs_contact_search",
                "query": owner_text,
            }

    due_date_text = extract_due_date_text(reply_text)
    if "due_timestamp_ms" in patched.missing_fields and due_date_text:
        due_timestamp_ms = parse_due_date_text_to_timestamp_ms(due_date_text, now=now)
        if due_timestamp_ms:
            arguments["due_timestamp_ms"] = due_timestamp_ms
            patched.metadata["due_date_text"] = due_date_text

    patched.tool_arguments = arguments
    patched.missing_fields = [
        field_name
        for field_name in patched.missing_fields
        if not field_is_filled(field_name, arguments)
    ]
    patched.status = "ready_to_resume" if not patched.missing_fields else "pending"
    patched.updated_at = int(now or time.time())
    patched.recovery_prompt = build_recovery_prompt(patched)
    return patched


def build_resumed_tool_call(action: PendingAction) -> AgentToolCall:
    """从已补齐的 pending action 构造可重新审核执行的工具调用。"""

    llm_tool_name = action.tool_name.replace(".", "_")
    return AgentToolCall(
        call_id=f"resume:{action.action_id}:{int(time.time() * 1000)}",
        tool_name=llm_tool_name,
        arguments=dict(action.tool_arguments),
        raw_payload={"pending_action_id": action.action_id, "session_id": action.session_id},
    )


def build_recovery_prompt(action: PendingAction) -> str:
    """根据缺失字段生成下一轮用户可理解的问题。"""

    labels = {
        "human_confirmation": "是否确认执行",
        "assignee_ids": "负责人",
        "due_timestamp_ms": "截止时间",
        "idempotency_key": "幂等键",
        "confidence": "行动项置信度或证据",
    }
    fields = [labels.get(field, field) for field in action.missing_fields]
    if not fields:
        return "信息已补齐，可以继续恢复待执行动作。"
    return "请补充" + "、".join(fields) + "，我会恢复刚才被暂停的动作。"


def field_is_filled(field_name: str, arguments: dict[str, Any]) -> bool:
    """判断某个策略字段是否已经通过用户补充填好。"""

    value = arguments.get(field_name)
    if field_name == "assignee_ids":
        return isinstance(value, list) and any(str(item).strip() for item in value)
    if field_name == "due_timestamp_ms":
        return bool(str(value or "").strip())
    return bool(value)


def extract_owner_text(reply: str) -> str:
    """从自然语言补充里尽量提取负责人文本。"""

    text = reply.strip()
    if not text:
        return ""
    for pattern in (
        r"(?:负责人|owner|分配给|交给|由)\s*(?:是|为|:|：)?\s*([\w\u4e00-\u9fff-]{1,32})",
        r"(我|本人|自己)\s*(?:负责|来做|处理)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    if text in {"我", "本人", "自己"}:
        return text
    return ""


def extract_due_date_text(reply: str) -> str:
    """从用户补字段文本中提取截止时间。"""

    text = reply.strip()
    if not text:
        return ""
    full_date = re.search(r"(20\d{2}[-/]\d{1,2}[-/]\d{1,2})", text)
    if full_date:
        return full_date.group(1)
    for keyword in ("今天", "明天", "后天", "下周一", "下周五", "本周五"):
        if keyword in text:
            return keyword
    match = re.search(r"(?:截止|ddl|due|到期)\s*(?:是|为|:|：)?\s*([\w\u4e00-\u9fff/-]{1,20})", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_due_date_text_to_timestamp_ms(value: str, now: int | None = None) -> str:
    """把常见中文日期或 YYYY-MM-DD 转成毫秒时间戳字符串。"""

    base = datetime.fromtimestamp(int(now or time.time()), tz=timezone(timedelta(hours=8)))
    raw = value.strip()
    if raw in {"今天"}:
        target = base
    elif raw in {"明天"}:
        target = base + timedelta(days=1)
    elif raw in {"后天"}:
        target = base + timedelta(days=2)
    elif raw in {"本周五", "下周五", "下周一"}:
        weekday = 4 if raw.endswith("五") else 0
        days = (weekday - base.weekday()) % 7
        if raw.startswith("下周") or days == 0:
            days += 7
        target = base + timedelta(days=days)
    else:
        match = re.match(r"^(20\d{2})[-/](\d{1,2})[-/](\d{1,2})$", raw)
        if not match:
            return ""
        target = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tzinfo=timezone(timedelta(hours=8)),
        )
    end_of_day = target.replace(hour=23, minute=59, second=0, microsecond=0)
    return str(int(end_of_day.timestamp() * 1000))


def first_non_empty(data: dict[str, Any], *keys: str) -> str:
    """读取首个非空字段。"""

    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        return str(value).strip()
    return ""
