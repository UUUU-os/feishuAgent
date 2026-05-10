from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from config import StorageSettings
from core.assistant_memory import AssistantSession, ClarificationQuestion, PendingAction
from core.logging import get_logger
from core.migrations import MigrationRunner
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

        applied = MigrationRunner(self.db_path).apply_pending()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 兼容早期开发库。长期结构演进由 MigrationRunner 负责，这里只保留
            # 对历史 task_mappings 补列的保险，避免用户从很旧的本地库启动失败。
            self._ensure_task_mapping_columns(cursor)
            conn.commit()
        MigrationRunner(self.db_path).verify()

        self.logger.info("本地存储初始化完成 db_path=%s migrations_applied=%s", self.db_path, len(applied))

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

    def find_recent_workflow_results(
        self,
        workflow_name: str,
        project_id: str = "",
        meeting_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """读取最近工作流结果，用于会前复用历史会议和风险事实。

        `workflow_results` 早期没有独立 project_id 列，因此这里从 payload 中
        解析项目和会议字段做过滤，避免为了 D2 首版强制迁移历史数据库。
        """

        normalized_workflow = str(workflow_name or "").strip()
        if not normalized_workflow:
            return []
        normalized_project_id = str(project_id or "").strip()
        normalized_meeting_id = str(meeting_id or "").strip()
        query_limit = max(int(limit or 20), 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT trace_id, workflow_name, status, summary, payload_json, created_at
                FROM workflow_results
                WHERE workflow_name = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (normalized_workflow, query_limit * 5),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            item = self._normalize_workflow_result_row(row)
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            item_project_id = self._extract_project_id_from_payload(payload)
            item_meeting_id = self._extract_meeting_id_from_payload(payload)
            if normalized_project_id and item_project_id and item_project_id != normalized_project_id:
                continue
            if normalized_meeting_id and item_meeting_id and item_meeting_id != normalized_meeting_id:
                continue
            results.append(item)
            if len(results) >= query_limit:
                break
        return results

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

    def save_assistant_session(self, session: AssistantSession) -> None:
        """保存或更新助手会话。

        会话只保存业务现场和非敏感摘要，不保存完整 token 或外部 API 原始响应。
        """

        now = int(time.time())
        created_at = int(session.created_at or now)
        updated_at = int(session.updated_at or now)
        with sqlite3.connect(self.db_path) as conn:
            table_columns = self._get_table_columns(conn, "assistant_sessions")
            memory_json = json.dumps(session.memory, ensure_ascii=False)
            legacy_state = {
                "actor": session.actor,
                "source": session.source,
                "workflow_type": session.workflow_type,
                "memory": session.memory,
            }
            values = {
                "session_id": session.session_id,
                "actor": session.actor,
                "source": session.source,
                "workflow_type": session.workflow_type,
                "status": session.status,
                "memory_json": memory_json,
                "last_trace_id": session.last_trace_id,
                "created_at": created_at,
                "updated_at": updated_at,
                # 兼容早期实验库遗留的 NOT NULL 字段。新代码以 actor/memory_json
                # 为准，但旧字段仍需要写入非空值，否则真实联调库会插入失败。
                "user_id": session.actor,
                "chat_id": str(session.memory.get("chat_id") or ""),
                "current_workflow": session.workflow_type,
                "current_meeting_id": str(session.memory.get("meeting_id") or ""),
                "current_project_id": str(session.memory.get("project_id") or ""),
                "state_json": json.dumps(legacy_state, ensure_ascii=False),
                "expires_at": updated_at + 30 * 24 * 60 * 60,
            }
            insert_columns = [column for column in values if column in table_columns]
            update_columns = [
                column
                for column in insert_columns
                if column not in {"session_id", "created_at"}
            ]
            placeholders = ", ".join("?" for _ in insert_columns)
            update_clause = ",\n                    ".join(
                f"{column} = excluded.{column}" for column in update_columns
            )
            conn.execute(
                f"""
                INSERT INTO assistant_sessions (
                    {", ".join(insert_columns)}
                ) VALUES ({placeholders})
                ON CONFLICT(session_id) DO UPDATE SET
                    {update_clause}
                """,
                tuple(values[column] for column in insert_columns),
            )
            conn.commit()

    def get_assistant_session(self, session_id: str) -> dict[str, Any] | None:
        """按 session_id 读取助手会话。"""

        if not session_id:
            return None
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM assistant_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._normalize_json_row(row, {"memory_json": "memory"})

    def find_latest_assistant_session(self, actor: str = "", workflow_type: str = "") -> dict[str, Any] | None:
        """按用户和工作流回查最近活跃会话，用于自然语言补字段。"""

        clauses = ["status = 'active'"]
        params: list[Any] = []
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if workflow_type:
            clauses.append("workflow_type = ?")
            params.append(workflow_type)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT *
                FROM assistant_sessions
                WHERE {" AND ".join(clauses)}
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._normalize_json_row(row, {"memory_json": "memory"})

    def save_pending_action(self, action: PendingAction) -> None:
        """保存一个可恢复 pending action。"""

        now = int(time.time())
        created_at = int(action.created_at or now)
        updated_at = int(action.updated_at or now)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO pending_actions (
                    action_id, session_id, trace_id, workflow_type, tool_name,
                    tool_arguments_json, missing_fields_json, status, policy_reason,
                    idempotency_key, recovery_prompt, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    trace_id = excluded.trace_id,
                    workflow_type = excluded.workflow_type,
                    tool_name = excluded.tool_name,
                    tool_arguments_json = excluded.tool_arguments_json,
                    missing_fields_json = excluded.missing_fields_json,
                    status = excluded.status,
                    policy_reason = excluded.policy_reason,
                    idempotency_key = excluded.idempotency_key,
                    recovery_prompt = excluded.recovery_prompt,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    action.action_id,
                    action.session_id,
                    action.trace_id,
                    action.workflow_type,
                    action.tool_name,
                    json.dumps(action.tool_arguments, ensure_ascii=False),
                    json.dumps(action.missing_fields, ensure_ascii=False),
                    action.status,
                    action.policy_reason,
                    action.idempotency_key,
                    action.recovery_prompt,
                    json.dumps(action.metadata, ensure_ascii=False),
                    created_at,
                    updated_at,
                ),
            )
            conn.commit()

    def get_pending_action(self, action_id: str) -> PendingAction | None:
        """读取 pending action 并恢复为模型。"""

        if not action_id:
            return None
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)).fetchone()
        return self._pending_action_from_row(row)

    def find_latest_pending_action(
        self,
        *,
        session_id: str = "",
        actor: str = "",
        workflow_type: str = "",
        statuses: set[str] | None = None,
    ) -> PendingAction | None:
        """查找最近一个仍可恢复的 pending action。"""

        status_values = statuses or {"pending", "ready_to_resume"}
        clauses = [f"pa.status IN ({','.join(['?'] * len(status_values))})"]
        params: list[Any] = list(status_values)
        if session_id:
            clauses.append("pa.session_id = ?")
            params.append(session_id)
        if workflow_type:
            clauses.append("pa.workflow_type = ?")
            params.append(workflow_type)
        if actor:
            clauses.append("s.actor = ?")
            params.append(actor)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT pa.*
                FROM pending_actions pa
                LEFT JOIN assistant_sessions s ON s.session_id = pa.session_id
                WHERE {" AND ".join(clauses)}
                ORDER BY pa.updated_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._pending_action_from_row(row)

    def update_pending_action_status(self, action_id: str, status: str) -> None:
        """更新 pending action 状态。"""

        if not action_id:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE pending_actions SET status = ?, updated_at = ? WHERE action_id = ?",
                (status, int(time.time()), action_id),
            )
            conn.commit()

    def save_clarification_question(self, question: ClarificationQuestion) -> None:
        """保存 pending action 对应的澄清问题。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO clarification_questions (
                    question_id, action_id, session_id, question, missing_fields_json,
                    status, answer, created_at, answered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question.question_id,
                    question.action_id,
                    question.session_id,
                    question.question,
                    json.dumps(question.missing_fields, ensure_ascii=False),
                    question.status,
                    question.answer,
                    int(question.created_at or time.time()),
                    int(question.answered_at or 0),
                ),
            )
            conn.commit()

    def mark_clarification_answered(self, action_id: str, answer: str) -> None:
        """用户补字段后关闭该 pending action 的澄清问题。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE clarification_questions
                SET status = 'answered', answer = ?, answered_at = ?
                WHERE action_id = ? AND status = 'open'
                """,
                (answer, int(time.time()), action_id),
            )
            conn.commit()

    def save_review_session(
        self,
        review_session_id: str,
        *,
        workflow_type: str = "post_meeting_followup",
        meeting_id: str = "",
        minute_token: str = "",
        chat_id: str = "",
        status: str = "pending",
        pending_count: int = 0,
        created_count: int = 0,
        rejected_count: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """保存 M4 人工确认会话审计。

        review_session_id 让同一妙记重复发卡时能区分新旧批次，真实回调中旧卡
        会被拦截，新卡可以重新创建本轮任务。
        """

        if not review_session_id:
            return
        now = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_sessions (
                    review_session_id, workflow_type, meeting_id, minute_token, chat_id,
                    status, pending_count, created_count, rejected_count,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_session_id) DO UPDATE SET
                    workflow_type = excluded.workflow_type,
                    meeting_id = excluded.meeting_id,
                    minute_token = excluded.minute_token,
                    chat_id = excluded.chat_id,
                    status = excluded.status,
                    pending_count = excluded.pending_count,
                    created_count = excluded.created_count,
                    rejected_count = excluded.rejected_count,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    review_session_id,
                    workflow_type,
                    meeting_id,
                    minute_token,
                    chat_id,
                    status,
                    int(pending_count or 0),
                    int(created_count or 0),
                    int(rejected_count or 0),
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()

    def get_review_session(self, review_session_id: str) -> dict[str, Any] | None:
        """读取 M4 review session 审计记录。"""

        if not review_session_id:
            return None
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM review_sessions WHERE review_session_id = ?",
                (review_session_id,),
            ).fetchone()
        return self._normalize_json_row(row, {"payload_json": "payload"})

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

    def find_task_mappings(
        self,
        project_id: str = "",
        meeting_id: str = "",
        title_query: str = "",
        statuses: set[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """按项目、会议或标题查询任务映射，服务 D2 遗留行动项。

        当前 `task_mappings` 未必有 project_id 列；首版优先用 meeting_id 和
        title 过滤。如果调用方传入 project_id，会在 evidence/source_url 等
        可用字段中做弱过滤，不命中时不强行排除，避免漏掉历史数据。
        """

        normalized_meeting_id = str(meeting_id or "").strip()
        normalized_title_query = str(title_query or "").strip().lower()
        normalized_project_id = str(project_id or "").strip().lower()
        clauses: list[str] = []
        params: list[Any] = []
        if normalized_meeting_id:
            clauses.append("meeting_id = ?")
            params.append(normalized_meeting_id)
        if normalized_title_query:
            clauses.append("LOWER(title) LIKE ?")
            params.append(f"%{normalized_title_query}%")
        where_clause = f"WHERE {' OR '.join(clauses)}" if clauses else ""
        params.append(max(int(limit or 20), 1) * 5)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM task_mappings
                {where_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        status_filter = {item.lower() for item in statuses} if statuses else set()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = self._normalize_task_mapping_row(row)
            if not item:
                continue
            status = str(item.get("status") or "").strip().lower()
            if status_filter and status not in status_filter:
                continue
            if normalized_project_id and not self._task_mapping_mentions_project(item, normalized_project_id):
                # 旧数据通常没有项目字段，不能把弱过滤变成硬过滤。
                if item.get("meeting_id") or item.get("source_url"):
                    continue
            results.append(item)
            if len(results) >= max(int(limit or 20), 1):
                break
        return results

    def find_recent_risk_notifications(
        self,
        task_ids: list[str] | None = None,
        statuses: set[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """读取最近风险提醒记录，用于会前展示持续风险。"""

        normalized_task_ids = [str(item).strip() for item in (task_ids or []) if str(item).strip()]
        clauses: list[str] = []
        params: list[Any] = []
        if normalized_task_ids:
            placeholders = ", ".join("?" for _ in normalized_task_ids)
            clauses.append(f"task_id IN ({placeholders})")
            params.extend(normalized_task_ids)
        status_filter = {item.lower() for item in statuses} if statuses else set()
        if status_filter:
            placeholders = ", ".join("?" for _ in status_filter)
            clauses.append(f"LOWER(status) IN ({placeholders})")
            params.extend(sorted(status_filter))
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(int(limit or 20), 1))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM risk_notifications
                {where_clause}
                ORDER BY notified_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            try:
                data["payload"] = json.loads(data.get("payload_json") or "{}")
            except json.JSONDecodeError:
                data["payload"] = {}
            results.append(data)
        return results

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

    @staticmethod
    def _normalize_workflow_result_row(row: sqlite3.Row | None) -> dict[str, Any]:
        """把 workflow_results 行转换成业务字典。"""

        if row is None:
            return {}
        data = dict(row)
        try:
            payload = json.loads(data.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        data["payload"] = payload if isinstance(payload, dict) else {}
        return data

    @classmethod
    def _extract_project_id_from_payload(cls, payload: dict[str, Any]) -> str:
        """从工作流 payload 中尽量解析 project_id。"""

        candidates = [
            payload,
            payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            payload.get("context") if isinstance(payload.get("context"), dict) else {},
        ]
        raw_context = {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        if isinstance(context.get("raw_context"), dict):
            raw_context = context["raw_context"]
            candidates.append(raw_context)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            value = cls._first_non_empty(candidate, "project_id", "current_project_id")
            if value:
                return value
        return ""

    @classmethod
    def _extract_meeting_id_from_payload(cls, payload: dict[str, Any]) -> str:
        """从工作流 payload 中尽量解析 meeting_id。"""

        candidates = [
            payload,
            payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            payload.get("context") if isinstance(payload.get("context"), dict) else {},
        ]
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        if isinstance(context.get("raw_context"), dict):
            candidates.append(context["raw_context"])
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            value = cls._first_non_empty(candidate, "meeting_id", "meetingId")
            if value:
                return value
        return ""

    @staticmethod
    def _task_mapping_mentions_project(mapping: dict[str, Any], project_id: str) -> bool:
        """判断 task mapping 是否包含项目线索。"""

        text_parts = [
            str(mapping.get("meeting_id") or ""),
            str(mapping.get("minute_token") or ""),
            str(mapping.get("title") or ""),
            str(mapping.get("source_url") or ""),
            json.dumps(mapping.get("evidence_refs") or [], ensure_ascii=False),
        ]
        haystack = "\n".join(text_parts).lower()
        return bool(project_id and project_id in haystack)

    @staticmethod
    def _normalize_json_row(row: sqlite3.Row | None, json_columns: dict[str, str]) -> dict[str, Any] | None:
        """把带 JSON 字段的 SQLite 行转换为业务字典。"""

        if row is None:
            return None
        data = dict(row)
        for source_key, target_key in json_columns.items():
            try:
                data[target_key] = json.loads(data.get(source_key) or "{}")
            except json.JSONDecodeError:
                data[target_key] = {}
        return data

    @staticmethod
    def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
        """读取表字段集合，用于兼容本地开发库的历史 schema。"""

        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}

    @staticmethod
    def _pending_action_from_row(row: sqlite3.Row | None) -> PendingAction | None:
        """把 pending_actions 行恢复为 PendingAction。"""

        if row is None:
            return None
        data = dict(row)
        try:
            tool_arguments = json.loads(data.get("tool_arguments_json") or "{}")
        except json.JSONDecodeError:
            tool_arguments = {}
        try:
            missing_fields = json.loads(data.get("missing_fields_json") or "[]")
        except json.JSONDecodeError:
            missing_fields = []
        try:
            metadata = json.loads(data.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            metadata = {}
        return PendingAction(
            action_id=str(data.get("action_id") or ""),
            session_id=str(data.get("session_id") or ""),
            trace_id=str(data.get("trace_id") or ""),
            workflow_type=str(data.get("workflow_type") or ""),
            tool_name=str(data.get("tool_name") or ""),
            tool_arguments=tool_arguments if isinstance(tool_arguments, dict) else {},
            missing_fields=[str(item) for item in (missing_fields if isinstance(missing_fields, list) else [])],
            status=str(data.get("status") or "pending"),
            policy_reason=str(data.get("policy_reason") or ""),
            idempotency_key=str(data.get("idempotency_key") or ""),
            recovery_prompt=str(data.get("recovery_prompt") or ""),
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at=int(data.get("created_at") or 0),
            updated_at=int(data.get("updated_at") or 0),
        )

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
