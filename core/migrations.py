from __future__ import annotations

import hashlib
import inspect
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any


MigrationApply = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class Migration:
    """描述一次 MeetFlow 本地数据库结构升级。

    migration 需要幂等，因为本项目已经有一批由 `CREATE TABLE IF NOT EXISTS`
    创建出来的旧库。升级时优先补齐缺失结构，而不是假设所有用户都从空库开始。
    """

    version: int
    name: str
    apply: MigrationApply
    notes: tuple[str, ...] = ()

    @property
    def checksum(self) -> str:
        """生成稳定校验值，用于发现同版本 migration 被意外改写。"""

        try:
            source = inspect.getsource(self.apply)
        except OSError:
            source = repr(self.apply)
        raw = "\n".join([str(self.version), self.name, *self.notes, source])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MigrationError(RuntimeError):
    """数据库迁移失败或 schema 校验失败。"""


class MigrationRunner:
    """执行 MeetFlow SQLite schema 迁移。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def apply_pending(self) -> list[Migration]:
        """应用所有尚未执行的内置 migration。"""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        applied_migrations: list[Migration] = []
        with sqlite3.connect(self.db_path) as conn:
            ensure_schema_migrations_table(conn)
            applied = get_applied_migrations(conn)
            for migration in get_builtin_migrations():
                existing_checksum = applied.get(migration.version)
                if existing_checksum:
                    if existing_checksum != migration.checksum:
                        raise MigrationError(
                            f"migration checksum mismatch version={migration.version} name={migration.name}"
                        )
                    continue
                migration.apply(conn)
                conn.execute(
                    """
                    INSERT INTO schema_migrations (version, name, checksum, applied_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (migration.version, migration.name, migration.checksum, int(time.time())),
                )
                conn.commit()
                applied_migrations.append(migration)
        return applied_migrations

    def status(self) -> dict[str, Any]:
        """返回 migration 应用状态，供脚本和健康检查展示。"""

        rows: list[tuple[Any, ...]] = []
        applied: dict[int, str] = {}
        if self.db_path.exists():
            with sqlite3.connect(self.db_path) as conn:
                applied = get_applied_migrations(conn)
                if table_exists(conn, "schema_migrations"):
                    rows = conn.execute(
                        """
                        SELECT version, name, checksum, applied_at
                        FROM schema_migrations
                        ORDER BY version
                        """
                    ).fetchall()
        builtin = get_builtin_migrations()
        return {
            "db_path": str(self.db_path),
            "applied_count": len(applied),
            "pending_count": sum(1 for migration in builtin if migration.version not in applied),
            "applied": [
                {
                    "version": int(row[0]),
                    "name": str(row[1]),
                    "checksum": str(row[2]),
                    "applied_at": int(row[3]),
                }
                for row in rows
            ],
            "pending": [
                {"version": migration.version, "name": migration.name, "checksum": migration.checksum}
                for migration in builtin
                if migration.version not in applied
            ],
        }

    def verify(self) -> None:
        """校验当前库是否具备运行 MeetFlow 所需的关键表和字段。"""

        with sqlite3.connect(self.db_path) as conn:
            missing: list[str] = []
            required_tables = {
                "schema_migrations": ("version", "name", "checksum", "applied_at"),
                "workflow_results": ("trace_id", "workflow_name", "status", "payload_json", "created_at"),
                "idempotency_keys": ("idempotency_key", "workflow_name", "trace_id", "created_at"),
                "task_mappings": (
                    "item_id",
                    "task_id",
                    "meeting_id",
                    "minute_token",
                    "title",
                    "owner",
                    "due_date",
                    "status",
                    "evidence_refs_json",
                    "source_url",
                    "updated_at",
                ),
                "risk_notifications": (
                    "id",
                    "risk_key",
                    "task_id",
                    "risk_type",
                    "severity",
                    "status",
                    "trace_id",
                    "recipient",
                    "payload_json",
                    "notified_at",
                    "suppressed_until",
                ),
                "workflow_jobs": (
                    "job_id",
                    "queue_name",
                    "job_type",
                    "status",
                    "payload_json",
                    "idempotency_key",
                    "attempts",
                    "max_attempts",
                    "available_at",
                    "locked_by",
                    "locked_until",
                    "last_error",
                    "result_json",
                    "created_at",
                    "updated_at",
                ),
                "assistant_sessions": (
                    "session_id",
                    "actor",
                    "source",
                    "workflow_type",
                    "status",
                    "memory_json",
                    "last_trace_id",
                    "created_at",
                    "updated_at",
                ),
                "pending_actions": (
                    "action_id",
                    "session_id",
                    "trace_id",
                    "workflow_type",
                    "tool_name",
                    "tool_arguments_json",
                    "missing_fields_json",
                    "status",
                    "policy_reason",
                    "idempotency_key",
                    "recovery_prompt",
                    "metadata_json",
                    "created_at",
                    "updated_at",
                ),
                "clarification_questions": (
                    "question_id",
                    "action_id",
                    "session_id",
                    "question",
                    "missing_fields_json",
                    "status",
                    "answer",
                    "created_at",
                    "answered_at",
                ),
                "review_sessions": (
                    "review_session_id",
                    "workflow_type",
                    "meeting_id",
                    "minute_token",
                    "chat_id",
                    "status",
                    "pending_count",
                    "created_count",
                    "rejected_count",
                    "payload_json",
                    "created_at",
                    "updated_at",
                ),
            }
            for table_name, columns in required_tables.items():
                if not table_exists(conn, table_name):
                    missing.append(f"table:{table_name}")
                    continue
                existing_columns = get_table_columns(conn, table_name)
                for column_name in columns:
                    if column_name not in existing_columns:
                        missing.append(f"column:{table_name}.{column_name}")
            if missing:
                raise MigrationError("schema verify failed missing=" + ",".join(missing))


def ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    """确保 migration 元数据表存在。"""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def get_applied_migrations(conn: sqlite3.Connection) -> dict[int, str]:
    """读取已应用 migration 版本和校验值。"""

    if not table_exists(conn, "schema_migrations"):
        return {}
    rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {int(row[0]): str(row[1]) for row in rows}


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """判断表是否存在。"""

    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """读取表字段集合。"""

    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    """旧库补列，避免重复 ALTER TABLE。"""

    if column_name in get_table_columns(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def create_index_if_missing(conn: sqlite3.Connection, index_name: str, sql: str) -> None:
    """创建索引；SQLite 原生支持 IF NOT EXISTS，但这里统一入口便于测试。"""

    conn.execute(sql)


def get_builtin_migrations() -> tuple[Migration, ...]:
    """返回项目内置 migration 列表。"""

    return (
        Migration(
            version=1,
            name="initial_workflow_tables",
            apply=_migration_0001_initial_workflow_tables,
            notes=("workflow_results", "idempotency_keys", "task_mappings"),
        ),
        Migration(
            version=2,
            name="task_mappings_m4_fields",
            apply=_migration_0002_task_mappings_m4_fields,
            notes=("minute_token", "title", "evidence_refs_json", "source_url"),
        ),
        Migration(
            version=3,
            name="risk_notifications",
            apply=_migration_0003_risk_notifications,
            notes=("risk_notifications",),
        ),
        Migration(
            version=4,
            name="workflow_jobs",
            apply=_migration_0004_workflow_jobs,
            notes=("workflow_jobs",),
        ),
        Migration(
            version=5,
            name="callback_review_session_fields",
            apply=_migration_0005_callback_review_session_fields,
            notes=("review_session_id", "confirmation_status", "confirmed_at"),
        ),
        Migration(
            version=6,
            name="assistant_memory_and_review_sessions",
            apply=_migration_0006_assistant_memory_and_review_sessions,
            notes=("assistant_sessions", "pending_actions", "clarification_questions", "review_sessions"),
        ),
        Migration(
            version=7,
            name="assistant_memory_schema_backfill",
            apply=_migration_0007_assistant_memory_schema_backfill,
            notes=("assistant_sessions_backfill", "pending_actions_backfill", "review_sessions_backfill"),
        ),
    )


def _migration_0001_initial_workflow_tables(conn: sqlite3.Connection) -> None:
    """创建 MVP 阶段已有的核心业务表。"""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_results (
            trace_id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            idempotency_key TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_mappings (
            item_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            meeting_id TEXT NOT NULL DEFAULT '',
            minute_token TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            owner TEXT NOT NULL,
            due_date TEXT NOT NULL,
            status TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            source_url TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL
        )
        """
    )
    for column_name, column_sql in {
        "meeting_id": "TEXT NOT NULL DEFAULT ''",
        "minute_token": "TEXT NOT NULL DEFAULT ''",
        "title": "TEXT NOT NULL DEFAULT ''",
        "evidence_refs_json": "TEXT NOT NULL DEFAULT '[]'",
        "source_url": "TEXT NOT NULL DEFAULT ''",
    }.items():
        add_column_if_missing(conn, "task_mappings", column_name, column_sql)


def _migration_0002_task_mappings_m4_fields(conn: sqlite3.Connection) -> None:
    """补齐 M4/M5 闭环依赖的任务来源字段。"""

    if not table_exists(conn, "task_mappings"):
        _migration_0001_initial_workflow_tables(conn)
    for column_name, column_sql in {
        "meeting_id": "TEXT NOT NULL DEFAULT ''",
        "minute_token": "TEXT NOT NULL DEFAULT ''",
        "title": "TEXT NOT NULL DEFAULT ''",
        "evidence_refs_json": "TEXT NOT NULL DEFAULT '[]'",
        "source_url": "TEXT NOT NULL DEFAULT ''",
    }.items():
        add_column_if_missing(conn, "task_mappings", column_name, column_sql)


def _migration_0003_risk_notifications(conn: sqlite3.Connection) -> None:
    """创建 M5 风险提醒历史表。"""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            risk_key TEXT NOT NULL,
            task_id TEXT NOT NULL,
            risk_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            recipient TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            notified_at INTEGER NOT NULL,
            suppressed_until INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    create_index_if_missing(
        conn,
        "idx_risk_notifications_key_time",
        """
        CREATE INDEX IF NOT EXISTS idx_risk_notifications_key_time
        ON risk_notifications (risk_key, notified_at)
        """,
    )


def _migration_0004_workflow_jobs(conn: sqlite3.Connection) -> None:
    """创建后台任务队列表，让回调和 daemon 触发的工作可恢复。"""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_jobs (
            job_id TEXT PRIMARY KEY,
            queue_name TEXT NOT NULL,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 100,
            payload_json TEXT NOT NULL,
            idempotency_key TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            available_at INTEGER NOT NULL,
            locked_by TEXT NOT NULL DEFAULT '',
            locked_until INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    create_index_if_missing(
        conn,
        "idx_workflow_jobs_status_available",
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_jobs_status_available
        ON workflow_jobs(status, available_at, priority)
        """,
    )
    create_index_if_missing(
        conn,
        "idx_workflow_jobs_idempotency",
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_jobs_idempotency
        ON workflow_jobs(idempotency_key)
        """,
    )


def _migration_0005_callback_review_session_fields(conn: sqlite3.Connection) -> None:
    """给任务映射预留卡片确认会话字段。

    当前 pending registry 主要保存在 JSON 文件中，这些列先作为审计和后续查询
    预留，不影响现有 `save_task_mapping()` 调用。
    """

    if not table_exists(conn, "task_mappings"):
        _migration_0001_initial_workflow_tables(conn)
    for column_name, column_sql in {
        "review_session_id": "TEXT NOT NULL DEFAULT ''",
        "confirmation_status": "TEXT NOT NULL DEFAULT ''",
        "confirmed_at": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        add_column_if_missing(conn, "task_mappings", column_name, column_sql)


def _migration_0006_assistant_memory_and_review_sessions(conn: sqlite3.Connection) -> None:
    """创建多轮会话、pending action 和 M4 review session 审计表。

    这些表把“用户补字段后恢复动作”从日志文本升级成结构化状态。外部写操作
    仍然由 ToolRegistry + AgentPolicy 执行，状态表只负责记忆和恢复现场。
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_sessions (
            session_id TEXT PRIMARY KEY,
            actor TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            workflow_type TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            memory_json TEXT NOT NULL DEFAULT '{}',
            last_trace_id TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_actions (
            action_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            workflow_type TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            tool_arguments_json TEXT NOT NULL DEFAULT '{}',
            missing_fields_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending',
            policy_reason TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            recovery_prompt TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clarification_questions (
            question_id TEXT PRIMARY KEY,
            action_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            question TEXT NOT NULL,
            missing_fields_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'open',
            answer TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            answered_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_sessions (
            review_session_id TEXT PRIMARY KEY,
            workflow_type TEXT NOT NULL DEFAULT 'post_meeting_followup',
            meeting_id TEXT NOT NULL DEFAULT '',
            minute_token TEXT NOT NULL DEFAULT '',
            chat_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            pending_count INTEGER NOT NULL DEFAULT 0,
            created_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    create_index_if_missing(
        conn,
        "idx_pending_actions_session_status",
        """
        CREATE INDEX IF NOT EXISTS idx_pending_actions_session_status
        ON pending_actions(session_id, status, updated_at)
        """,
    )
    create_index_if_missing(
        conn,
        "idx_review_sessions_meeting",
        """
        CREATE INDEX IF NOT EXISTS idx_review_sessions_meeting
        ON review_sessions(meeting_id, minute_token, updated_at)
        """,
    )


def _migration_0007_assistant_memory_schema_backfill(conn: sqlite3.Connection) -> None:
    """补齐早期实验库中不完整的助手记忆表。

    真实开发库可能已经由旧脚本创建过 `assistant_sessions` 或 `pending_actions`
    的半成品表。version 6 对新库没问题，但旧库需要继续幂等补列。
    """

    _migration_0006_assistant_memory_and_review_sessions(conn)
    for column_name, column_sql in {
        "actor": "TEXT NOT NULL DEFAULT ''",
        "source": "TEXT NOT NULL DEFAULT ''",
        "workflow_type": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "memory_json": "TEXT NOT NULL DEFAULT '{}'",
        "last_trace_id": "TEXT NOT NULL DEFAULT ''",
        "created_at": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        add_column_if_missing(conn, "assistant_sessions", column_name, column_sql)
    for column_name, column_sql in {
        "session_id": "TEXT NOT NULL DEFAULT ''",
        "trace_id": "TEXT NOT NULL DEFAULT ''",
        "workflow_type": "TEXT NOT NULL DEFAULT ''",
        "tool_name": "TEXT NOT NULL DEFAULT ''",
        "tool_arguments_json": "TEXT NOT NULL DEFAULT '{}'",
        "missing_fields_json": "TEXT NOT NULL DEFAULT '[]'",
        "status": "TEXT NOT NULL DEFAULT 'pending'",
        "policy_reason": "TEXT NOT NULL DEFAULT ''",
        "idempotency_key": "TEXT NOT NULL DEFAULT ''",
        "recovery_prompt": "TEXT NOT NULL DEFAULT ''",
        "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        add_column_if_missing(conn, "pending_actions", column_name, column_sql)
    for column_name, column_sql in {
        "action_id": "TEXT NOT NULL DEFAULT ''",
        "session_id": "TEXT NOT NULL DEFAULT ''",
        "question": "TEXT NOT NULL DEFAULT ''",
        "missing_fields_json": "TEXT NOT NULL DEFAULT '[]'",
        "status": "TEXT NOT NULL DEFAULT 'open'",
        "answer": "TEXT NOT NULL DEFAULT ''",
        "created_at": "INTEGER NOT NULL DEFAULT 0",
        "answered_at": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        add_column_if_missing(conn, "clarification_questions", column_name, column_sql)
