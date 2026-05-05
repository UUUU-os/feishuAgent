from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import JobSettings, StorageSettings
from core.migrations import MigrationRunner
from core.observability import emit_structured_event, safe_error_message


TERMINAL_STATUSES = {"succeeded", "failed", "dead_letter", "cancelled"}
RETRYABLE_STATUSES = {"pending", "retrying"}


@dataclass(slots=True)
class JobRecord:
    """一条可恢复执行的后台任务。"""

    job_id: str
    queue_name: str
    job_type: str
    status: str
    priority: int
    payload: dict[str, Any]
    idempotency_key: str
    attempts: int
    max_attempts: int
    available_at: int
    locked_by: str = ""
    locked_until: int = 0
    last_error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    updated_at: int = 0

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "JobRecord":
        """从 SQLite 行构造任务对象。"""

        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        try:
            result = json.loads(row["result_json"] or "{}")
        except json.JSONDecodeError:
            result = {}
        return cls(
            job_id=str(row["job_id"]),
            queue_name=str(row["queue_name"]),
            job_type=str(row["job_type"]),
            status=str(row["status"]),
            priority=int(row["priority"]),
            payload=payload if isinstance(payload, dict) else {},
            idempotency_key=str(row["idempotency_key"] or ""),
            attempts=int(row["attempts"] or 0),
            max_attempts=int(row["max_attempts"] or 0),
            available_at=int(row["available_at"] or 0),
            locked_by=str(row["locked_by"] or ""),
            locked_until=int(row["locked_until"] or 0),
            last_error=str(row["last_error"] or ""),
            result=result if isinstance(result, dict) else {},
            created_at=int(row["created_at"] or 0),
            updated_at=int(row["updated_at"] or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        """转成适合日志和测试断言的字典。"""

        return {
            "job_id": self.job_id,
            "queue_name": self.queue_name,
            "job_type": self.job_type,
            "status": self.status,
            "priority": self.priority,
            "payload": self.payload,
            "idempotency_key": self.idempotency_key,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "available_at": self.available_at,
            "locked_by": self.locked_by,
            "locked_until": self.locked_until,
            "last_error": self.last_error,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobQueue:
    """基于 SQLite 的轻量任务队列。

    队列的职责是保存“要做什么”和“执行到哪一步”，真正的业务副作用仍由
    worker 调用既有 workflow/脚本，并继续经过 `AgentPolicy` 和飞书客户端封装。
    """

    def __init__(self, storage: StorageSettings | str | Path, *, ensure_schema: bool = True) -> None:
        self.db_path = Path(getattr(storage, "db_path", storage))
        if ensure_schema:
            MigrationRunner(self.db_path).apply_pending()

    def enqueue(
        self,
        *,
        queue_name: str,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str = "",
        priority: int = 100,
        available_at: int | None = None,
        max_attempts: int = 3,
        job_id: str = "",
    ) -> JobRecord:
        """写入一条 pending job；相同幂等键会返回已有 job。"""

        now = int(time.time())
        normalized_payload = dict(payload or {})
        normalized_idempotency_key = str(idempotency_key or "").strip()
        final_job_id = job_id or build_job_id(
            queue_name=queue_name,
            job_type=job_type,
            idempotency_key=normalized_idempotency_key,
            payload=normalized_payload,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if normalized_idempotency_key:
                existing = conn.execute(
                    """
                    SELECT *
                    FROM workflow_jobs
                    WHERE queue_name = ? AND job_type = ? AND idempotency_key = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (queue_name, job_type, normalized_idempotency_key),
                ).fetchone()
                if existing is not None:
                    return JobRecord.from_row(existing)
            conn.execute(
                """
                INSERT OR IGNORE INTO workflow_jobs (
                    job_id,
                    queue_name,
                    job_type,
                    status,
                    priority,
                    payload_json,
                    idempotency_key,
                    attempts,
                    max_attempts,
                    available_at,
                    locked_by,
                    locked_until,
                    last_error,
                    result_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, 0, ?, ?, '', 0, '', '{}', ?, ?)
                """,
                (
                    final_job_id,
                    queue_name,
                    job_type,
                    int(priority),
                    json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True),
                    normalized_idempotency_key,
                    max(int(max_attempts or 3), 1),
                    int(available_at or now),
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM workflow_jobs WHERE job_id = ?", (final_job_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"workflow job not found after enqueue job_id={final_job_id}")
        record = JobRecord.from_row(row)
        emit_job_event("job_enqueued", record)
        return record

    def get_job(self, job_id: str) -> JobRecord | None:
        """按 job_id 读取任务。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM workflow_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return JobRecord.from_row(row) if row is not None else None

    def claim_due_job(
        self,
        *,
        worker_id: str,
        queues: list[str] | tuple[str, ...],
        lock_seconds: int = 300,
        now: int | None = None,
    ) -> JobRecord | None:
        """领取一条到期任务，并设置 worker 锁。"""

        queue_names = [item for item in queues if item]
        if not queue_names:
            return None
        now_ts = int(now or time.time())
        lock_until = now_ts + max(int(lock_seconds or 300), 30)
        placeholders = ",".join("?" for _ in queue_names)
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"""
                SELECT *
                FROM workflow_jobs
                WHERE queue_name IN ({placeholders})
                  AND available_at <= ?
                  AND (
                    status IN ('pending', 'retrying')
                    OR (status = 'running' AND locked_until <= ?)
                  )
                ORDER BY priority ASC, available_at ASC, created_at ASC
                LIMIT 1
                """,
                (*queue_names, now_ts, now_ts),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute(
                """
                UPDATE workflow_jobs
                SET status = 'running',
                    locked_by = ?,
                    locked_until = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (worker_id, lock_until, now_ts, row["job_id"]),
            )
            conn.execute("COMMIT")
            updated = conn.execute("SELECT * FROM workflow_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
        record = JobRecord.from_row(updated)
        emit_job_event("job_claimed", record, worker_id=worker_id)
        return record

    def mark_succeeded(self, job_id: str, result: dict[str, Any] | None = None) -> JobRecord:
        """标记任务成功。"""

        record = self._update_status(
            job_id,
            status="succeeded",
            result=result or {},
            last_error="",
            clear_lock=True,
        )
        emit_job_event("job_succeeded", record)
        return record

    def mark_retry(
        self,
        job_id: str,
        *,
        error: BaseException | str,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 600,
        dead_letter_after_attempts: int = 4,
    ) -> JobRecord:
        """把失败任务放回队列，或在超过次数后进入死信。"""

        current = self.get_job(job_id)
        if current is None:
            raise RuntimeError(f"workflow job not found job_id={job_id}")
        if current.attempts >= min(current.max_attempts, int(dead_letter_after_attempts or current.max_attempts)):
            return self.mark_dead_letter(job_id, error=error)
        now = int(time.time())
        delay = compute_retry_delay(
            current.attempts,
            base_seconds=retry_base_seconds,
            max_seconds=retry_max_seconds,
        )
        record = self._update_status(
            job_id,
            status="retrying",
            available_at=now + delay,
            last_error=safe_error_message(error),
            clear_lock=True,
        )
        emit_job_event("job_retry_scheduled", record, retry_delay_seconds=delay)
        return record

    def mark_failed(self, job_id: str, *, error: BaseException | str) -> JobRecord:
        """标记不可重试失败。"""

        record = self._update_status(
            job_id,
            status="failed",
            last_error=safe_error_message(error),
            clear_lock=True,
        )
        emit_job_event("job_failed", record, error_type=error.__class__.__name__)
        return record

    def mark_dead_letter(self, job_id: str, *, error: BaseException | str) -> JobRecord:
        """标记死信，等待人工排查。"""

        record = self._update_status(
            job_id,
            status="dead_letter",
            last_error=safe_error_message(error),
            clear_lock=True,
        )
        emit_job_event("job_dead_letter", record, error_type=error.__class__.__name__)
        return record

    def list_jobs(self, *, status: str = "", limit: int = 50) -> list[JobRecord]:
        """按状态列出最近任务，便于测试和排查。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM workflow_jobs
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (status, max(int(limit or 50), 1)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM workflow_jobs
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (max(int(limit or 50), 1),),
                ).fetchall()
        return [JobRecord.from_row(row) for row in rows]

    def _update_status(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        last_error: str = "",
        available_at: int | None = None,
        clear_lock: bool = False,
    ) -> JobRecord:
        now = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE workflow_jobs
                SET status = ?,
                    available_at = COALESCE(?, available_at),
                    locked_by = CASE WHEN ? THEN '' ELSE locked_by END,
                    locked_until = CASE WHEN ? THEN 0 ELSE locked_until END,
                    last_error = ?,
                    result_json = COALESCE(?, result_json),
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    available_at,
                    1 if clear_lock else 0,
                    1 if clear_lock else 0,
                    last_error,
                    json.dumps(result, ensure_ascii=False, sort_keys=True) if result is not None else None,
                    now,
                    job_id,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM workflow_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"workflow job not found job_id={job_id}")
        return JobRecord.from_row(row)


def build_job_id(
    *,
    queue_name: str,
    job_type: str,
    idempotency_key: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    """根据业务类型、幂等键和 payload 生成稳定 job_id。"""

    material = {
        "queue_name": queue_name,
        "job_type": job_type,
        "idempotency_key": idempotency_key,
        "payload": payload or {},
    }
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"job_{digest[:32]}"


def compute_retry_delay(attempts: int, *, base_seconds: int = 30, max_seconds: int = 600) -> int:
    """按尝试次数计算指数退避时间。"""

    safe_attempts = max(int(attempts or 1), 1)
    base = max(int(base_seconds or 30), 1)
    max_delay = max(int(max_seconds or 600), base)
    return min(base * (4 ** (safe_attempts - 1)), max_delay)


def is_retryable_error(error: BaseException) -> bool:
    """按错误类型粗分是否值得重试。"""

    status_code = int(getattr(error, "status_code", 0) or getattr(error, "http_status", 0) or 0)
    if status_code == 429 or status_code >= 500:
        return True
    if status_code in {400, 401, 403, 404}:
        return False
    error_name = error.__class__.__name__.lower()
    message = safe_error_message(error).lower()
    retryable_markers = ("timeout", "temporarily", "rate limit", "database is locked", "connection")
    if any(marker in error_name or marker in message for marker in retryable_markers):
        return True
    non_retryable_markers = ("policy", "permission", "invalid", "auth", "forbidden")
    if any(marker in error_name or marker in message for marker in non_retryable_markers):
        return False
    return False


def enqueue_agent_input_job(
    queue: JobQueue,
    *,
    agent_input: Any,
    queue_name: str,
    allow_write: bool,
    agent_provider: str = "dry-run",
    priority: int = 100,
    max_attempts: int = 3,
) -> JobRecord:
    """把卡片动作产生的 AgentInput 写入后台任务队列。"""

    payload = {
        "agent_input": agent_input.to_dict() if hasattr(agent_input, "to_dict") else dict(agent_input),
        "allow_write": bool(allow_write),
        "agent_provider": agent_provider,
    }
    idempotency_key = build_agent_input_job_idempotency_key(payload["agent_input"])
    return queue.enqueue(
        queue_name=queue_name,
        job_type="agent_input.run",
        payload=payload,
        idempotency_key=idempotency_key,
        priority=priority,
        max_attempts=max_attempts,
    )


def build_agent_input_job_idempotency_key(agent_input: dict[str, Any]) -> str:
    """从 AgentInput 中提取幂等键，避免同一按钮事件重复入队。"""

    event_id = str(agent_input.get("event_id") or "").strip()
    event_type = str(agent_input.get("event_type") or "").strip()
    trace_id = str(agent_input.get("trace_id") or "").strip()
    if event_id:
        return f"agent_input:{event_type}:{event_id}"
    return f"agent_input:{event_type}:{trace_id or build_job_id(queue_name='agent', job_type=event_type, payload=agent_input)}"


def queue_from_settings(storage: StorageSettings, jobs: JobSettings | None = None) -> JobQueue:
    """按项目配置创建队列对象。"""

    return JobQueue(storage, ensure_schema=True)


def emit_job_event(event_type: str, record: JobRecord, **fields: Any) -> None:
    """写入 job 结构化事件，同时避免把完整 payload 放进日志。"""

    idempotency_hash = (
        hashlib.sha256(record.idempotency_key.encode("utf-8")).hexdigest()[:16]
        if record.idempotency_key
        else ""
    )
    emit_structured_event(
        event_type,
        job_id=record.job_id,
        queue_name=record.queue_name,
        job_type=record.job_type,
        status=record.status,
        attempts=record.attempts,
        max_attempts=record.max_attempts,
        idempotency_key_hash=idempotency_hash,
        **fields,
    )
