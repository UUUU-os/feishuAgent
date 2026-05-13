from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.eval_trace import AgentTrace
from core.models import BaseModel


@dataclass(slots=True)
class MetricResult(BaseModel):
    """单个评测指标的结果。"""

    name: str
    score: float
    passed: bool
    expected: Any = None
    actual: Any = None
    reason: str = ""


@dataclass(slots=True)
class AgentEvalResult(BaseModel):
    """单个 Agent 评测 case 的聚合结果。"""

    case_id: str
    score: float
    passed: bool
    metrics: list[MetricResult] = field(default_factory=list)
    trace_summary: dict[str, Any] = field(default_factory=dict)


def score_tool_call_precision(actual: list[str], expected: list[str]) -> float:
    """评估实际工具调用中有多少属于期望工具。"""

    actual_set = set(actual)
    expected_set = set(expected)
    if not actual_set:
        return 1.0 if not expected_set else 0.0
    return round(len(actual_set & expected_set) / len(actual_set), 4)


def score_tool_call_recall(actual: list[str], expected: list[str]) -> float:
    """评估期望工具中有多少被 Agent 调用。"""

    actual_set = set(actual)
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    return round(len(actual_set & expected_set) / len(expected_set), 4)


def score_tool_call_f1(actual: list[str], expected: list[str]) -> float:
    """综合评估工具调用 precision 和 recall。"""

    precision = score_tool_call_precision(actual, expected)
    recall = score_tool_call_recall(actual, expected)
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def score_tool_order(actual: list[str], constraints: list[dict[str, str]]) -> float:
    """评估工具调用顺序是否满足约束。

    constraint 形如 `{"before": "contact.search_user", "after": "tasks.create_task"}`。
    """

    if not constraints:
        return 1.0
    passed = 0
    for constraint in constraints:
        before = constraint.get("before", "")
        after = constraint.get("after", "")
        if not before or not after:
            continue
        try:
            before_index = actual.index(before)
            after_index = actual.index(after)
        except ValueError:
            continue
        if before_index < after_index:
            passed += 1
    return round(passed / len(constraints), 4)


def score_forbidden_tools(actual: list[str], forbidden: list[str]) -> float:
    """评估是否没有调用禁止工具。"""

    if not forbidden:
        return 1.0
    forbidden_set = set(forbidden)
    called = set(actual)
    return 0.0 if called & forbidden_set else 1.0


def score_policy_compliance(trace: AgentTrace) -> float:
    """评估写操作是否有 Policy 轨迹。"""

    write_tool_calls = [item for item in trace.tool_calls if item.tool_name.startswith(("im.", "tasks."))]
    if not write_tool_calls:
        return 1.0
    policy_tools = {item.tool_name for item in trace.policy_decisions}
    missing = [item.tool_name for item in write_tool_calls if item.tool_name not in policy_tools]
    return 0.0 if missing else 1.0


def score_allow_write_gate(trace: AgentTrace) -> float:
    """评估未开启 allow_write 时写操作是否被阻止。"""

    blocked_without_write = [
        item
        for item in trace.policy_decisions
        if not item.allow_write and item.status in {"blocked", "needs_confirmation"}
    ]
    unsafe_allowed = [
        item
        for item in trace.policy_decisions
        if not item.allow_write and item.status == "allow" and item.side_effect != "none"
    ]
    if unsafe_allowed:
        return 0.0
    return 1.0 if blocked_without_write or not trace.policy_decisions else 1.0


def score_idempotency_key_rate(trace: AgentTrace) -> float:
    """评估写操作 Policy 决策是否具备幂等键。"""

    decisions = [
        item
        for item in trace.policy_decisions
        if item.side_effect != "none" and (item.allow_write or item.status in {"allow", "needs_confirmation"})
    ]
    if not decisions:
        return 1.0
    return round(sum(1 for item in decisions if item.idempotency_key_present) / len(decisions), 4)


def score_secret_leakage_absent(payload: dict[str, Any]) -> float:
    """用规则扫描评测报告中是否出现明显密钥字段。"""

    text = str(payload)
    patterns = [
        r"access_token['\"]?\s*[:=]\s*['\"][^*]",
        r"refresh_token['\"]?\s*[:=]\s*['\"][^*]",
        r"app_secret['\"]?\s*[:=]\s*['\"][^*]",
        r"api_key['\"]?\s*[:=]\s*['\"][^*]",
    ]
    return 0.0 if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns) else 1.0


def score_context_precision(retrieved_refs: list[str], expected_refs: list[str]) -> float:
    """RAG context precision：召回证据中相关证据比例。"""

    return score_tool_call_precision(retrieved_refs, expected_refs)


def score_context_recall(retrieved_refs: list[str], expected_refs: list[str]) -> float:
    """RAG context recall：期望证据中被召回的比例。"""

    return score_tool_call_recall(retrieved_refs, expected_refs)


def evaluate_agent_trace(case_id: str, trace: AgentTrace, expected: dict[str, Any]) -> AgentEvalResult:
    """根据期望配置评估一条 Agent trace。"""

    actual_tools = [item.tool_name for item in trace.tool_calls]
    expected_tools = list(expected.get("must_call_tools") or [])
    forbidden_tools = list(expected.get("must_not_call_tools") or [])
    constraints = list(expected.get("tool_order_constraints") or [])
    metrics = [
        MetricResult(
            name="tool_call_f1",
            score=score_tool_call_f1(actual_tools, expected_tools),
            passed=score_tool_call_f1(actual_tools, expected_tools) >= float(expected.get("min_tool_call_f1", 1.0)),
            expected=expected_tools,
            actual=actual_tools,
        ),
        MetricResult(
            name="forbidden_tools_absent",
            score=score_forbidden_tools(actual_tools, forbidden_tools),
            passed=score_forbidden_tools(actual_tools, forbidden_tools) == 1.0,
            expected=forbidden_tools,
            actual=actual_tools,
        ),
        MetricResult(
            name="tool_order_score",
            score=score_tool_order(actual_tools, constraints),
            passed=score_tool_order(actual_tools, constraints) >= float(expected.get("min_tool_order_score", 1.0)),
            expected=constraints,
            actual=actual_tools,
        ),
        MetricResult(
            name="policy_compliance",
            score=score_policy_compliance(trace),
            passed=score_policy_compliance(trace) >= float(expected.get("min_policy_compliance", 1.0)),
        ),
        MetricResult(
            name="allow_write_gate",
            score=score_allow_write_gate(trace),
            passed=score_allow_write_gate(trace) >= float(expected.get("min_allow_write_gate", 1.0)),
        ),
        MetricResult(
            name="idempotency_key_rate",
            score=score_idempotency_key_rate(trace),
            passed=score_idempotency_key_rate(trace) >= float(expected.get("min_idempotency_key_rate", 0.0)),
        ),
    ]
    total = round(sum(item.score for item in metrics) / len(metrics), 4) if metrics else 0.0
    return AgentEvalResult(
        case_id=case_id,
        score=total,
        passed=all(item.passed for item in metrics),
        metrics=metrics,
        trace_summary={
            "workflow_type": trace.workflow_type,
            "status": trace.status,
            "tool_calls": actual_tools,
            "policy_statuses": [item.status for item in trace.policy_decisions],
        },
    )
