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
                    owner TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
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
    ) -> None:
        """保存行动项和飞书任务之间的映射关系。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_mappings (
                    item_id,
                    task_id,
                    owner,
                    due_date,
                    status,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    task_id,
                    owner,
                    due_date,
                    status,
                    int(time.time()),
                ),
            )
            conn.commit()

    def get_task_mapping(self, item_id: str) -> dict[str, Any] | None:
        """读取行动项和任务之间的映射关系。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM task_mappings WHERE item_id = ?",
                (item_id,),
            ).fetchone()

        return dict(row) if row is not None else None

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
