from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from config import StorageSettings
from core.logging import get_logger
from core.models import WorkflowResult


class MeetFlowStorage:
    """MeetFlow 的本地存储入口。

    当前存储策略采用混合方案：
    - SQLite：保存结构化、需要查询的运行数据
    - JSON：保存项目长期记忆
    - JSONL：保存行动项快照等按时间追加的数据
    """

    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.logger = get_logger("meetflow.storage")
        self.db_path = Path(settings.db_path)
        self.project_memory_dir = Path(settings.project_memory_dir)
        self.audit_log_path = Path(settings.audit_log_path)
        self.action_item_log_path = self.db_path.parent / "action_items.jsonl"

    def initialize(self) -> None:
        """初始化本地存储目录和 SQLite 表结构。"""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.project_memory_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.action_item_log_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 记录工作流运行结果，便于后续查询某次执行的输出。
            cursor.execute(
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

            # 记录幂等键，避免同一个工作流被重复执行。
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )

            # 记录任务映射关系，为后续任务同步、风险扫描做准备。
            cursor.execute(
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
            self._ensure_task_mapping_columns(cursor)

            # 记录风险提醒历史，用于 M5 巡检降噪和后续审计。
            cursor.execute(
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
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_risk_notifications_key_time
                ON risk_notifications (risk_key, notified_at)
                """
            )

            conn.commit()

        self.logger.info("本地存储初始化完成 db_path=%s", self.db_path)

    def save_workflow_result(self, result: WorkflowResult) -> None:
        """保存一次工作流执行结果。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO workflow_results (
                    trace_id,
                    workflow_name,
                    status,
                    summary,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result.trace_id,
                    result.workflow_name,
                    result.status,
                    result.summary,
                    json.dumps(result.payload, ensure_ascii=False),
                    result.created_at,
                ),
            )
            conn.commit()

    def get_workflow_result(self, trace_id: str) -> dict[str, Any] | None:
        """按 trace_id 读取一条工作流结果。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM workflow_results WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()

        if row is None:
            return None

        data = dict(row)
        data["payload_json"] = json.loads(data["payload_json"])
        return data

    def find_latest_workflow_context_payload(
        self,
        workflow_name: str,
        meeting_id: str = "",
        calendar_event_id: str = "",
        limit: int = 50,
    ) -> dict[str, Any] | None:
        """按会议维度回查最近一次工作流上下文 payload。

        这个能力主要服务会前卡片刷新：
        如果当前回调 payload 只带 `meeting_id/calendar_event_id`，可以从本地
        已保存的工作流结果里补回最近一次已知的会议标题、参与人和附件，
        避免确定性阶段只拿到一个很薄的点击事件。
        """

        normalized_workflow = str(workflow_name or "").strip()
        normalized_meeting_id = str(meeting_id or "").strip()
        normalized_calendar_event_id = str(calendar_event_id or "").strip()
        if not normalized_workflow or (not normalized_meeting_id and not normalized_calendar_event_id):
            return None

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT trace_id, payload_json, created_at
                FROM workflow_results
                WHERE workflow_name = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (normalized_workflow, max(int(limit or 50), 1)),
            ).fetchall()

        for row in rows:
            try:
                payload_json = json.loads(str(row["payload_json"] or "{}"))
            except json.JSONDecodeError:
                continue
            payload = self._extract_context_payload_from_workflow_result(payload_json)
            if not payload:
                continue
            result_meeting_id = self._first_non_empty(payload, "meeting_id", "meetingId")
            result_calendar_event_id = self._first_non_empty(payload, "calendar_event_id", "event_id", "eventId")
            meeting_matches = not normalized_meeting_id or result_meeting_id == normalized_meeting_id
            calendar_matches = not normalized_calendar_event_id or result_calendar_event_id == normalized_calendar_event_id
            if meeting_matches and calendar_matches:
                return payload
        return None

    def record_idempotency_key(
        self,
        idempotency_key: str,
        workflow_name: str,
        trace_id: str,
    ) -> None:
        """记录某个幂等键已经执行过。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO idempotency_keys (
                    idempotency_key,
                    workflow_name,
                    trace_id,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    workflow_name,
                    trace_id,
                    int(time.time()),
                ),
            )
            conn.commit()

    def is_idempotency_key_processed(self, idempotency_key: str) -> bool:
        """判断某个幂等键是否已经存在。"""

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM idempotency_keys WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return row is not None

    def save_task_mapping(
        self,
        item_id: str,
        task_id: str,
        owner: str,
        due_date: str,
        status: str,
        meeting_id: str = "",
        minute_token: str = "",
        title: str = "",
        evidence_refs: list[dict[str, Any]] | None = None,
        source_url: str = "",
    ) -> None:
        """保存行动项和飞书任务之间的映射关系。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_mappings (
                    item_id,
                    task_id,
                    meeting_id,
                    minute_token,
                    title,
                    owner,
                    due_date,
                    status,
                    evidence_refs_json,
                    source_url,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    task_id,
                    meeting_id,
                    minute_token,
                    title,
                    owner,
                    due_date,
                    status,
                    json.dumps(evidence_refs or [], ensure_ascii=False),
                    source_url,
                    int(time.time()),
                ),
            )
            conn.commit()

    @staticmethod
    def _extract_context_payload_from_workflow_result(payload_json: dict[str, Any]) -> dict[str, Any]:
        """从工作流结果 payload 中提取最适合回放的上下文 payload。"""

        workflow_payload = payload_json.get("payload")
        if not isinstance(workflow_payload, dict):
            return {}
        context = workflow_payload.get("context")
        if not isinstance(context, dict):
            return {}
        raw_context = context.get("raw_context")
        if isinstance(raw_context, dict):
            raw_payload = raw_context.get("payload")
            if isinstance(raw_payload, dict) and raw_payload:
                return dict(raw_payload)
        event = context.get("event")
        if isinstance(event, dict):
            event_payload = event.get("payload")
            if isinstance(event_payload, dict) and event_payload:
                return dict(event_payload)
        return {}

    @staticmethod
    def _first_non_empty(data: dict[str, Any], *keys: str) -> str:
        """按顺序读取字典中的首个非空字符串。"""

        for key in keys:
            value = data.get(key)
            if value is None or value == "":
                continue
            return str(value)
        return ""

    def get_task_mapping(self, item_id: str) -> dict[str, Any] | None:
        """读取行动项和任务之间的映射关系。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM task_mappings WHERE item_id = ?",
                (item_id,),
            ).fetchone()

        if row is None:
            return None
        data = dict(row)
        if "evidence_refs_json" in data:
            try:
                data["evidence_refs"] = json.loads(data.get("evidence_refs_json") or "[]")
            except json.JSONDecodeError:
                data["evidence_refs"] = []
        return data

    def get_task_mapping_by_task_id(self, task_id: str) -> dict[str, Any] | None:
        """按飞书任务 ID 读取 M4 任务来源映射。

        M5 巡检读取到的是飞书任务 ID，而不是 M4 内部的 action item ID。
        这个查询把“任务当前风险”接回“会后由哪场会议产生、证据来自哪里”。
        """

        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return None

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM task_mappings
                WHERE task_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (normalized_task_id,),
            ).fetchone()

        return self._normalize_task_mapping_row(row)

    def find_task_mappings_by_meeting(
        self,
        meeting_id: str = "",
        minute_token: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """按会议或妙记读取任务映射，便于演示 M4/M5 闭环。"""

        normalized_meeting_id = str(meeting_id or "").strip()
        normalized_minute_token = str(minute_token or "").strip()
        if not normalized_meeting_id and not normalized_minute_token:
            return []

        clauses: list[str] = []
        params: list[Any] = []
        if normalized_meeting_id:
            clauses.append("meeting_id = ?")
            params.append(normalized_meeting_id)
        if normalized_minute_token:
            clauses.append("minute_token = ?")
            params.append(normalized_minute_token)
        params.append(max(int(limit or 20), 1))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM task_mappings
                WHERE {" OR ".join(clauses)}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [item for row in rows if (item := self._normalize_task_mapping_row(row))]

    @staticmethod
    def _normalize_task_mapping_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        """把 task_mappings 行转换成业务字典，并解析 evidence_refs。"""

        if row is None:
            return None
        data = dict(row)
        try:
            data["evidence_refs"] = json.loads(data.get("evidence_refs_json") or "[]")
        except json.JSONDecodeError:
            data["evidence_refs"] = []
        return data

    def _ensure_task_mapping_columns(self, cursor: sqlite3.Cursor) -> None:
        """为旧版本 task_mappings 表补齐 M4/M5 对接字段。"""

        existing_columns = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(task_mappings)").fetchall()
        }
        column_specs = {
            "meeting_id": "TEXT NOT NULL DEFAULT ''",
            "minute_token": "TEXT NOT NULL DEFAULT ''",
            "title": "TEXT NOT NULL DEFAULT ''",
            "evidence_refs_json": "TEXT NOT NULL DEFAULT '[]'",
            "source_url": "TEXT NOT NULL DEFAULT ''",
        }
        for column_name, column_spec in column_specs.items():
            if column_name not in existing_columns:
                cursor.execute(f"ALTER TABLE task_mappings ADD COLUMN {column_name} {column_spec}")

    def record_risk_notification(
        self,
        risk_key: str,
        task_id: str,
        risk_type: str,
        severity: str,
        status: str,
        trace_id: str,
        recipient: str,
        summary: str,
        payload: dict[str, Any],
        notified_at: int,
        suppressed_until: int,
    ) -> None:
        """记录一次风险提醒或降噪决策。

        这里保存的是“是否提醒”的业务事实，不保存完整飞书任务 raw payload，
        避免风险巡检表变成新的敏感数据聚集点。
        """

        now = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO risk_notifications (
                    risk_key,
                    task_id,
                    risk_type,
                    severity,
                    status,
                    trace_id,
                    recipient,
                    summary,
                    payload_json,
                    notified_at,
                    suppressed_until,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    risk_key,
                    task_id,
                    risk_type,
                    severity,
                    status,
                    trace_id,
                    recipient,
                    summary,
                    json.dumps(payload, ensure_ascii=False),
                    notified_at,
                    suppressed_until,
                    now,
                    now,
                ),
            )
            conn.commit()

    def get_latest_risk_notification(self, risk_key: str) -> dict[str, Any] | None:
        """读取某个风险键最近一次提醒记录。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM risk_notifications
                WHERE risk_key = ?
                ORDER BY notified_at DESC, id DESC
                LIMIT 1
                """,
                (risk_key,),
            ).fetchone()

        if row is None:
            return None
        data = dict(row)
        data["payload_json"] = json.loads(data["payload_json"])
        return data

    def has_recent_risk_notification(self, risk_key: str, now: int) -> bool:
        """判断某个风险是否仍在降噪窗口内。"""

        latest = self.get_latest_risk_notification(risk_key)
        if latest is None:
            return self.is_idempotency_key_processed(risk_key)
        return int(latest.get("suppressed_until", 0) or 0) > now

    def save_project_memory(self, project_id: str, data: dict[str, Any]) -> Path:
        """将项目长期记忆保存为 JSON 文件。"""

        path = self.project_memory_dir / f"{project_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        return path

    def load_project_memory(self, project_id: str) -> dict[str, Any] | None:
        """读取项目长期记忆。"""

        path = self.project_memory_dir / f"{project_id}.json"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def append_action_item_snapshot(self, data: dict[str, Any]) -> None:
        """把行动项快照追加写入 JSONL。

        这个文件适合保存：
        - 每次抽取的行动项
        - 每次任务同步时的快照
        - 后续做评估时的原始样本
        """

        with self.action_item_log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False) + "\n")
