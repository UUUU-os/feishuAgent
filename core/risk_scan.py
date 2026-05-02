from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from core.models import ActionItem, BaseModel, RiskAlert
from core.observability import duration_ms_since, emit_structured_event

if TYPE_CHECKING:
    from core.storage import MeetFlowStorage


COMPLETED_STATUSES = {
    "done",
    "completed",
    "complete",
    "closed",
    "finished",
    "finish",
    "已完成",
}

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(slots=True)
class TaskSnapshot(BaseModel):
    """风险巡检使用的任务快照。

    飞书任务、会后 ActionItem 和本地 mock 的字段形态不完全一样，M5 先把它们
    统一到这个模型中，避免风险规则里到处散落字段兼容逻辑。
    """

    task_id: str
    title: str
    status: str = "todo"
    owner: str = ""
    due_timestamp: int = 0
    updated_at: int = 0
    completed_at: int = 0
    url: str = ""
    source: str = "task"
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RiskRuleResult(BaseModel):
    """单条风险规则命中结果。"""

    risk_id: str
    task_id: str
    risk_type: str
    severity: str
    reason: str
    suggestion: str
    task: TaskSnapshot
    dedupe_key: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RiskScanResult(BaseModel):
    """一次风险巡检的聚合结果。"""

    scanned_count: int
    risk_count: int
    risks: list[RiskRuleResult] = field(default_factory=list)
    skipped_count: int = 0
    generated_at: int = 0
    summary: str = ""


@dataclass(slots=True)
class RiskNotificationDecision(BaseModel):
    """风险提醒降噪后的发送决策。"""

    should_notify: bool
    reason: str
    notify_risks: list[RiskRuleResult] = field(default_factory=list)
    suppressed_risks: list[RiskRuleResult] = field(default_factory=list)
    idempotency_key: str = ""
    notification_keys: list[str] = field(default_factory=list)


def parse_task_timestamp(value: Any) -> int:
    """兼容秒、毫秒、字符串、ISO 时间和飞书 due 对象，统一返回秒级时间戳。"""

    if value is None or value == "":
        return 0
    if isinstance(value, dict):
        for key in ("timestamp", "due_timestamp", "due_timestamp_ms", "time", "value"):
            parsed = parse_task_timestamp(value.get(key))
            if parsed:
                return parsed
        return 0
    if isinstance(value, (int, float)):
        timestamp = int(value)
        if timestamp > 10_000_000_000:
            return timestamp // 1000
        return timestamp
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return parse_task_timestamp(int(text))
    try:
        normalized = text.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp())
    except ValueError:
        return 0


def is_task_completed(task: TaskSnapshot) -> bool:
    """判断任务是否已完成，已完成任务不再触发风险提醒。"""

    return task.status.strip().lower() in COMPLETED_STATUSES or task.completed_at > 0


def task_snapshot_from_action_item(item: ActionItem) -> TaskSnapshot:
    """把当前项目已有 `ActionItem` 转成风险扫描任务快照。"""

    extra = item.extra if isinstance(item.extra, dict) else {}
    task_id = first_non_empty(
        extra,
        "task_id",
        "guid",
    ) or item.item_id
    return TaskSnapshot(
        task_id=task_id,
        title=item.title or "未命名任务",
        status=item.status or "todo",
        owner=item.owner or extract_owner_from_extra(extra),
        due_timestamp=parse_task_timestamp(item.due_date or extra.get("due") or extra.get("due_timestamp_ms")),
        updated_at=parse_task_timestamp(extra.get("updated_at")),
        completed_at=parse_task_timestamp(extra.get("completed_at")),
        url=str(extra.get("url", "") or ""),
        source="action_item",
        raw_payload=item.to_dict(),
    )


def task_snapshot_from_dict(data: dict[str, Any]) -> TaskSnapshot:
    """兼容工具序列化结果、本地 mock 和飞书 raw dict，统一生成任务快照。"""

    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    raw_payload = extra.get("raw_payload") if isinstance(extra.get("raw_payload"), dict) else data
    task_id = (
        first_non_empty(extra, "task_id", "guid")
        or first_non_empty(data, "task_id", "guid", "item_id", "id")
        or stable_fallback_task_id(data)
    )
    title = first_non_empty(data, "title", "summary", "name") or first_non_empty(raw_payload, "summary", "title")
    owner = first_non_empty(data, "owner", "assignee", "owner_name") or extract_owner_from_extra(extra or raw_payload)
    due_value = (
        data.get("due_timestamp")
        or data.get("due_timestamp_ms")
        or data.get("due_date")
        or extra.get("due_timestamp_ms")
        or extra.get("due")
        or raw_payload.get("due")
    )
    updated_value = data.get("updated_at") or extra.get("updated_at") or raw_payload.get("updated_at")
    completed_value = data.get("completed_at") or extra.get("completed_at") or raw_payload.get("completed_at")
    return TaskSnapshot(
        task_id=task_id,
        title=title or "未命名任务",
        status=first_non_empty(data, "status") or first_non_empty(raw_payload, "status") or "todo",
        owner=owner,
        due_timestamp=parse_task_timestamp(due_value),
        updated_at=parse_task_timestamp(updated_value),
        completed_at=parse_task_timestamp(completed_value),
        url=first_non_empty(extra, "url") or first_non_empty(data, "url") or first_non_empty(raw_payload, "url"),
        source=str(data.get("source", "") or "dict"),
        raw_payload=data,
    )


def normalize_task_snapshots(items: list[ActionItem | dict[str, Any]]) -> list[TaskSnapshot]:
    """把多来源任务列表统一成 `TaskSnapshot`，跳过无法识别的空条目。"""

    snapshots: list[TaskSnapshot] = []
    for item in items:
        if isinstance(item, TaskSnapshot):
            snapshots.append(item)
        elif isinstance(item, ActionItem):
            snapshots.append(task_snapshot_from_action_item(item))
        elif isinstance(item, dict):
            snapshots.append(task_snapshot_from_dict(item))
    return snapshots


def scan_task_risks(
    task: TaskSnapshot,
    now: int,
    stale_update_days: int,
    due_soon_hours: int,
) -> list[RiskRuleResult]:
    """对单个任务执行风险规则。"""

    if is_task_completed(task):
        return []

    risks: list[RiskRuleResult] = []
    if task.due_timestamp and task.due_timestamp < now:
        overdue_seconds = now - task.due_timestamp
        severity = "high" if overdue_seconds >= 24 * 60 * 60 else "medium"
        risks.append(
            build_risk_result(
                task=task,
                risk_type="overdue",
                severity=severity,
                reason=f"任务已逾期 {max(overdue_seconds // 3600, 1)} 小时仍未完成。",
                suggestion="请确认任务是否仍需推进，并补充最新状态或调整截止时间。",
                now=now,
                evidence={"due_timestamp": task.due_timestamp, "overdue_seconds": overdue_seconds},
            )
        )

    due_soon_seconds = due_soon_hours * 60 * 60
    if task.due_timestamp and 0 <= task.due_timestamp - now <= due_soon_seconds:
        risks.append(
            build_risk_result(
                task=task,
                risk_type="due_soon",
                severity="medium",
                reason=f"任务将在 {due_soon_hours} 小时内截止，当前仍未完成。",
                suggestion="请提前确认进展，必要时同步风险或拆分下一步动作。",
                now=now,
                evidence={"due_timestamp": task.due_timestamp, "due_soon_seconds": task.due_timestamp - now},
            )
        )

    stale_seconds = stale_update_days * 24 * 60 * 60
    if task.updated_at and now - task.updated_at >= stale_seconds:
        risks.append(
            build_risk_result(
                task=task,
                risk_type="stale_update",
                severity="medium",
                reason=f"任务已超过 {stale_update_days} 天没有更新。",
                suggestion="请补充最新进展，避免会议行动项失去跟踪。",
                now=now,
                evidence={"updated_at": task.updated_at, "stale_seconds": now - task.updated_at},
            )
        )

    if not task.owner.strip():
        risks.append(
            build_risk_result(
                task=task,
                risk_type="missing_owner",
                severity="high",
                reason="任务缺少明确负责人。",
                suggestion="请先明确负责人，再继续推进或提醒。",
                now=now,
                evidence={"owner": task.owner},
            )
        )

    return risks


def scan_risks(
    tasks: list[TaskSnapshot],
    now: int,
    stale_update_days: int,
    due_soon_hours: int,
) -> RiskScanResult:
    """对任务列表执行风险扫描，并返回按严重程度排序的结果。"""

    perf_started_at = time.perf_counter()
    emit_structured_event(
        "risk_scan_started",
        workflow_type="risk_scan",
        scanned_count=len(tasks),
        stale_update_days=stale_update_days,
        due_soon_hours=due_soon_hours,
    )
    risks: list[RiskRuleResult] = []
    skipped_count = 0
    for task in tasks:
        task_risks = scan_task_risks(
            task=task,
            now=now,
            stale_update_days=stale_update_days,
            due_soon_hours=due_soon_hours,
        )
        if not task_risks:
            skipped_count += 1
        for risk in task_risks:
            emit_structured_event(
                "risk_rule_matched",
                workflow_type="risk_scan",
                task_id=risk.task_id,
                risk_type=risk.risk_type,
                severity=risk.severity,
                dedupe_key=risk.dedupe_key,
            )
            risks.append(risk)

    risks.sort(key=lambda risk: (SEVERITY_ORDER.get(risk.severity, 99), risk.task.due_timestamp or 9_999_999_999))
    result = RiskScanResult(
        scanned_count=len(tasks),
        risk_count=len(risks),
        risks=risks,
        skipped_count=skipped_count,
        generated_at=now,
        summary=build_scan_summary(len(tasks), risks),
    )
    emit_structured_event(
        "risk_scan_finished",
        workflow_type="risk_scan",
        scanned_count=result.scanned_count,
        risk_count=result.risk_count,
        skipped_count=result.skipped_count,
        duration_ms=duration_ms_since(perf_started_at),
    )
    return result


def build_risk_dedupe_key(task_id: str, risk_type: str, now: int) -> str:
    """构造同一任务同一风险当天只提醒一次的降噪键。"""

    day_bucket = time.strftime("%Y%m%d", time.localtime(now))
    return f"risk_scan:{task_id}:{risk_type}:{day_bucket}"


def build_notification_idempotency_key(notification_keys: list[str], now: int) -> str:
    """构造聚合风险卡片的发送幂等键。"""

    day_bucket = time.strftime("%Y%m%d", time.localtime(now))
    joined = "|".join(sorted(notification_keys))
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12] if joined else "empty"
    return f"risk_scan:notification:{day_bucket}:{digest}"


def decide_risk_notification(
    scan_result: RiskScanResult,
    storage: "MeetFlowStorage | None",
    max_reminders_per_day: int,
    now: int,
) -> RiskNotificationDecision:
    """根据风险结果、每日上限和历史提醒记录决定是否提醒。"""

    if not scan_result.risks:
        decision = RiskNotificationDecision(should_notify=False, reason="本次巡检没有命中风险。")
        emit_risk_notification_decision(decision)
        return decision

    notify_risks: list[RiskRuleResult] = []
    suppressed_risks: list[RiskRuleResult] = []
    limit = max(max_reminders_per_day, 0)

    for risk in scan_result.risks:
        if is_risk_recently_notified(storage, risk.dedupe_key, now):
            suppressed_risks.append(risk)
            emit_structured_event(
                "risk_notification_suppressed",
                workflow_type="risk_scan",
                task_id=risk.task_id,
                risk_type=risk.risk_type,
                severity=risk.severity,
                dedupe_key=risk.dedupe_key,
                reason="recently_notified",
            )
            continue
        if limit and len(notify_risks) >= limit:
            suppressed_risks.append(risk)
            continue
        notify_risks.append(risk)

    if not notify_risks:
        decision = RiskNotificationDecision(
            should_notify=False,
            reason="风险均已在降噪窗口内提醒或超过每日提醒上限。",
            suppressed_risks=suppressed_risks,
        )
        emit_risk_notification_decision(decision)
        return decision

    notification_keys = [risk.dedupe_key for risk in notify_risks]
    decision = RiskNotificationDecision(
        should_notify=True,
        reason=f"本次巡检发现 {scan_result.risk_count} 条风险，其中 {len(notify_risks)} 条需要提醒。",
        notify_risks=notify_risks,
        suppressed_risks=suppressed_risks,
        idempotency_key=build_notification_idempotency_key(notification_keys, now),
        notification_keys=notification_keys,
    )
    emit_risk_notification_decision(decision)
    return decision


def risk_result_to_alert(risk: RiskRuleResult) -> RiskAlert:
    """把 M5 规则结果转换为项目已有公共 `RiskAlert` 模型。"""

    return RiskAlert(
        risk_id=risk.risk_id,
        task_id=risk.task_id,
        risk_type=risk.risk_type,
        severity=risk.severity,
        reason=risk.reason,
        owner=risk.task.owner,
        due_date=str(risk.task.due_timestamp or ""),
        suggestion=risk.suggestion,
    )


def build_risk_result(
    task: TaskSnapshot,
    risk_type: str,
    severity: str,
    reason: str,
    suggestion: str,
    now: int,
    evidence: dict[str, Any] | None = None,
) -> RiskRuleResult:
    """构造单条规则结果，集中生成 risk_id 和 dedupe_key。"""

    dedupe_key = build_risk_dedupe_key(task.task_id, risk_type, now)
    risk_id = hashlib.sha1(f"{task.task_id}:{risk_type}".encode("utf-8")).hexdigest()[:16]
    return RiskRuleResult(
        risk_id=risk_id,
        task_id=task.task_id,
        risk_type=risk_type,
        severity=severity,
        reason=reason,
        suggestion=suggestion,
        task=task,
        dedupe_key=dedupe_key,
        evidence=evidence or {},
    )


def is_risk_recently_notified(storage: "MeetFlowStorage | None", risk_key: str, now: int) -> bool:
    """兼容新版风险提醒表和旧幂等表的降噪查询。"""

    if storage is None:
        return False
    if hasattr(storage, "has_recent_risk_notification"):
        return bool(storage.has_recent_risk_notification(risk_key, now))
    return storage.is_idempotency_key_processed(risk_key)


def emit_risk_notification_decision(decision: RiskNotificationDecision) -> None:
    """记录风险提醒决策，避免只在最终卡片发送时才知道降噪结果。"""

    emit_structured_event(
        "risk_notification_decision",
        workflow_type="risk_scan",
        should_notify=decision.should_notify,
        reason=decision.reason,
        notify_count=len(decision.notify_risks),
        suppressed_count=len(decision.suppressed_risks),
        idempotency_key=decision.idempotency_key,
    )


def build_scan_summary(scanned_count: int, risks: list[RiskRuleResult]) -> str:
    """生成巡检摘要，供 CLI、日志和卡片复用。"""

    if not risks:
        return f"已扫描 {scanned_count} 个任务，未发现需要提醒的风险。"
    high_count = sum(1 for risk in risks if risk.severity == "high")
    medium_count = sum(1 for risk in risks if risk.severity == "medium")
    return f"已扫描 {scanned_count} 个任务，发现 {len(risks)} 条风险：高风险 {high_count} 条，中风险 {medium_count} 条。"


def extract_owner_from_extra(extra: dict[str, Any]) -> str:
    """从飞书任务 members 等结构中尽量提取可读负责人。"""

    members = extra.get("members")
    if not isinstance(members, list):
        return ""
    for member in members:
        if not isinstance(member, dict):
            continue
        for key in ("name", "display_name", "user_name", "open_id", "id"):
            value = member.get(key)
            if value:
                return str(value)
    return ""


def first_non_empty(data: dict[str, Any], *keys: str) -> str:
    """读取第一个非空字段。"""

    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return str(value)
    return ""


def stable_fallback_task_id(data: dict[str, Any]) -> str:
    """为本地 mock 等缺少 ID 的任务生成稳定降噪 ID。"""

    title = first_non_empty(data, "title", "summary", "name")
    raw = f"{title}:{data.get('due_date', '')}:{data.get('updated_at', '')}"
    return "task_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
