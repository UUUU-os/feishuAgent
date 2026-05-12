from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import StorageSettings
from core.logging import bind_trace_id, get_logger, get_trace_id, log_workflow_event, reset_trace_id


@dataclass(slots=True)
class AuditLogger:
    """负责将结构化审计事件写入 JSONL 文件。"""

    audit_log_path: str

    def append(self, record: dict[str, Any]) -> None:
        """追加一条审计记录。

        JSONL 的优点是：
        - 便于逐行追加
        - 便于后续 grep / jq / Python 读取
        - 适合记录工作流运行历史
        """

        path = Path(self.audit_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(slots=True)
class WorkflowRunRecorder:
    """记录一次工作流执行的开始、结束和异常信息。"""

    workflow_name: str
    storage: StorageSettings
    logger_name: str = "meetflow.workflow"
    logger: Any = field(init=False)
    audit_logger: AuditLogger = field(init=False)
    trace_id: str = field(init=False, default="-")
    start_time: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        # logger 和审计写入器都在初始化时就准备好，避免运行中临时创建。
        self.logger = get_logger(self.logger_name)
        self.audit_logger = AuditLogger(self.storage.audit_log_path)

    def start(self, **context: Any) -> str:
        """记录工作流开始事件，并绑定 trace_id。"""

        self.trace_id = bind_trace_id()
        self.start_time = time.time()

        log_workflow_event(
            self.logger,
            self.workflow_name,
            "started",
            **context,
        )
        self.audit_logger.append(
            {
                "trace_id": self.trace_id,
                "workflow": self.workflow_name,
                "stage": "started",
                "timestamp": int(self.start_time),
                "context": context,
            }
        )
        return self.trace_id

    def success(self, **result: Any) -> None:
        """记录工作流成功结束事件。"""

        duration_ms = int((time.time() - self.start_time) * 1000)
        log_workflow_event(
            self.logger,
            self.workflow_name,
            "finished",
            duration_ms=duration_ms,
            **result,
        )
        self.audit_logger.append(
            {
                "trace_id": get_trace_id(),
                "workflow": self.workflow_name,
                "stage": "finished",
                "timestamp": int(time.time()),
                "duration_ms": duration_ms,
                "result": result,
            }
        )
        reset_trace_id()

    def failure(self, error: Exception, **context: Any) -> None:
        """记录工作流失败事件，并保留错误类型和错误信息。"""

        duration_ms = int((time.time() - self.start_time) * 1000)
        log_workflow_event(
            self.logger,
            self.workflow_name,
            "failed",
            duration_ms=duration_ms,
            error_type=error.__class__.__name__,
            error_message=str(error),
            **context,
        )
        self.audit_logger.append(
            {
                "trace_id": get_trace_id(),
                "workflow": self.workflow_name,
                "stage": "failed",
                "timestamp": int(time.time()),
                "duration_ms": duration_ms,
                "error_type": error.__class__.__name__,
                "error_message": str(error),
                "context": context,
            }
        )
        reset_trace_id()
