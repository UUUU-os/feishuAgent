from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import load_settings
from config.loader import Settings
from core.migrations import MigrationError, MigrationRunner
from core.observability import safe_error_message


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_ROOT = PROJECT_ROOT / "storage" / "reports"
SENSITIVE_PATTERNS = [
    re.compile(r"(access_token['\"]?\s*[:=]\s*['\"])[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"(refresh_token['\"]?\s*[:=]\s*['\"])[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"(app_secret['\"]?\s*[:=]\s*['\"])[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"(api_key['\"]?\s*[:=]\s*['\"])[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"(Authorization:\s*Bearer\s+)[^\s]+", re.IGNORECASE),
]


@dataclass(slots=True)
class M3SendCardRequest:
    """MeetFlow Console 触发 M3 会前发卡的请求。"""

    date: str = "tomorrow"
    event_title: str = ""
    event_id: str = ""
    llm_provider: str = "scripted_debug"
    project_id: str = "meetflow"
    allow_write: bool = False
    write_report: bool = True
    force_index: bool = False
    idempotency_suffix: str = ""
    timeout_seconds: int = 120


@dataclass(slots=True)
class EvaluationRunRequest:
    """MeetFlow Console 触发 Agent 轨迹评测的请求。"""

    suite: str = "agent_trajectory"
    case_id: str = ""
    provider: str = "scripted_debug"
    fail_under: float = 0.95
    write_report: bool = True


class ConsoleAPIError(RuntimeError):
    """MeetFlow Console API 的业务错误。"""


class MeetFlowConsoleAPI:
    """本地控制台 API facade。

    这里不绕过现有 Agent/Policy/ToolRegistry/FeishuClient，只把命令行和本地
    存储能力包装成前端可以消费的结构化 JSON。
    """

    def __init__(self, settings: Settings | None = None, *, project_root: Path = PROJECT_ROOT) -> None:
        self.settings = settings or load_settings()
        self.project_root = project_root
        self.report_root = project_root / "storage" / "reports"

    def get_health(self) -> dict[str, Any]:
        """返回配置、SQLite、migration 和报告目录健康状态。"""

        storage = self.settings.storage
        db_path = Path(storage.db_path)
        migration_ok = True
        migration_error = ""
        try:
            MigrationRunner(db_path).verify()
        except MigrationError as error:
            migration_ok = False
            migration_error = safe_error_message(error)
        return {
            "app": {
                "name": self.settings.app.name,
                "env": self.settings.app.env,
                "timezone": self.settings.app.timezone,
            },
            "storage": {
                "db_path": str(db_path),
                "db_exists": db_path.exists(),
                "reports_dir": str(self.report_root),
                "reports_dir_exists": self.report_root.exists(),
            },
            "migration": {
                "ok": migration_ok,
                "error": migration_error,
            },
            "evaluation_latest_exists": (self.report_root / "evaluation" / "agent_trajectory_latest.json").exists(),
        }

    def get_dashboard(self) -> dict[str, Any]:
        """聚合工作台首页所需的关键状态。"""

        return {
            "health": self.get_health(),
            "evaluation": self.get_latest_report("evaluation"),
            "m3": self.get_latest_report("m3"),
            "m4": self.get_latest_report("m4"),
            "job_status_counts": self.get_job_status_counts(),
            "recent_jobs": self.list_jobs(limit=10),
        }

    def get_latest_report(self, report_type: str) -> dict[str, Any]:
        """读取最新报告摘要。"""

        normalized = str(report_type or "").strip().lower()
        if normalized == "evaluation":
            latest_path = self.report_root / "evaluation" / "agent_trajectory_latest.json"
            return read_json_report(latest_path)
        if normalized == "m3":
            return read_latest_glob_report(self.report_root / "m3", "*.json")
        if normalized == "m4":
            return read_latest_glob_report(self.report_root / "m4", "*.json")
        raise ConsoleAPIError(f"未知报告类型：{report_type}")

    def list_jobs(self, *, limit: int = 50, status: str = "", queue_name: str = "") -> dict[str, Any]:
        """读取 workflow_jobs，支持按状态和队列筛选。"""

        rows = query_jobs(
            db_path=Path(self.settings.storage.db_path),
            limit=limit,
            status=status,
            queue_name=queue_name,
        )
        return {
            "items": rows,
            "limit": limit,
            "status": status,
            "queue_name": queue_name,
        }

    def get_job_status_counts(self) -> dict[str, int]:
        """按 status 聚合 workflow_jobs 数量。"""

        db_path = Path(self.settings.storage.db_path)
        if not db_path.exists():
            return {}
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM workflow_jobs
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def get_migration_status(self) -> dict[str, Any]:
        """返回 migration status 和 verify 结果。"""

        runner = MigrationRunner(self.settings.storage.db_path)
        status = runner.status()
        try:
            runner.verify()
            verify = {"ok": True, "error": ""}
        except MigrationError as error:
            verify = {"ok": False, "error": safe_error_message(error)}
        return {"status": status, "verify": verify}

    def run_agent_evaluation(self, request: EvaluationRunRequest) -> dict[str, Any]:
        """运行 Agent 轨迹评测，并按需写入 latest 报告。"""

        from scripts.agent_eval_suite import DEFAULT_FIXTURES_DIR, run_agent_eval_suite

        report = run_agent_eval_suite(
            fixtures_dir=DEFAULT_FIXTURES_DIR,
            suite=request.suite,
            case_id=request.case_id,
        )
        payload = report.to_dict()
        payload["provider"] = request.provider
        payload["passed_threshold"] = report.score >= float(request.fail_under) and report.safety_score == 1.0
        payload["fail_under"] = float(request.fail_under)
        output_path = ""
        if request.write_report:
            report_dir = self.report_root / "evaluation"
            report_dir.mkdir(parents=True, exist_ok=True)
            output = report_dir / f"{request.suite}_{int(time.time())}.json"
            latest = report_dir / f"{request.suite}_latest.json"
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            output.write_text(text, encoding="utf-8")
            latest.write_text(text, encoding="utf-8")
            output_path = str(output)
        payload["report_path"] = output_path
        return payload

    def run_m3_send_card(self, request: M3SendCardRequest) -> dict[str, Any]:
        """触发 M3 会前发卡。未显式 allow_write 时只 dry-run 打印命令。"""

        validate_m3_request(request)
        suffix = request.idempotency_suffix or f"m3-{time.strftime('%Y%m%d%H%M%S')}"
        command = [
            sys.executable,
            str(self.project_root / "scripts" / "card_send_live.py"),
            "m3",
            "--date",
            request.date,
            "--llm-provider",
            request.llm_provider,
            "--project-id",
            request.project_id,
            "--idempotency-suffix",
            suffix,
        ]
        if request.event_title:
            command.extend(["--event-title", request.event_title])
        if request.event_id:
            command.extend(["--event-id", request.event_id])
        if request.force_index:
            command.append("--force-index")
        if request.write_report:
            command.append("--write-report")
        if not request.allow_write:
            command.append("--dry-run")
        completed = subprocess.run(
            command,
            cwd=self.project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=max(int(request.timeout_seconds or 120), 10),
            check=False,
        )
        output = redact_sensitive(completed.stdout or "")
        parsed = parse_m3_stdout(output)
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "dry_run": not request.allow_write,
            "command": command_for_display(command),
            "idempotency_suffix": suffix,
            "stdout": output[-12000:],
            "parsed": parsed,
        }

    def run_worker_once(self, *, dry_run: bool = True, timeout_seconds: int = 60) -> dict[str, Any]:
        """执行一次 worker 健康检查。第一阶段只允许 dry-run。"""

        if not dry_run:
            raise ConsoleAPIError("Console 第一阶段只允许 worker dry-run。")
        command = [
            sys.executable,
            str(self.project_root / "scripts" / "meetflow_worker.py"),
            "--once",
            "--dry-run",
        ]
        completed = subprocess.run(
            command,
            cwd=self.project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=max(int(timeout_seconds or 60), 10),
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "command": command_for_display(command),
            "stdout": redact_sensitive(completed.stdout or "")[-12000:],
        }


def validate_m3_request(request: M3SendCardRequest) -> None:
    """校验 M3 请求，避免前端传入不受控参数。"""

    if request.llm_provider not in {"scripted_debug", "dry-run", "configured", "deepseek"}:
        raise ConsoleAPIError(f"不支持的 llm_provider：{request.llm_provider}")
    if not request.event_title and not request.event_id:
        raise ConsoleAPIError("请至少提供 event_title 或 event_id。")
    if request.date and not re.match(r"^(today|tomorrow|\d{4}-\d{2}-\d{2})$", request.date):
        raise ConsoleAPIError("date 只支持 today / tomorrow / YYYY-MM-DD。")


def query_jobs(db_path: Path, *, limit: int = 50, status: str = "", queue_name: str = "") -> list[dict[str, Any]]:
    """直接查询 workflow_jobs，补充 JobQueue 当前不支持的队列筛选。"""

    if not db_path.exists():
        return []
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if queue_name:
        clauses.append("queue_name = ?")
        params.append(queue_name)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT job_id, queue_name, job_type, status, priority, idempotency_key,
                   attempts, max_attempts, available_at, locked_by, locked_until,
                   last_error, created_at, updated_at
            FROM workflow_jobs
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*params, max(int(limit or 50), 1)),
        ).fetchall()
    return [dict(row) for row in rows]


def read_json_report(path: Path) -> dict[str, Any]:
    """读取单个 JSON 报告并附带文件信息。"""

    if not path.exists():
        return {"exists": False, "path": str(path), "data": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"exists": True, "path": str(path), "error": safe_error_message(error), "data": {}}
    return {
        "exists": True,
        "path": str(path),
        "mtime": int(path.stat().st_mtime),
        "data": summarize_report_data(data),
    }


def read_latest_glob_report(directory: Path, pattern: str) -> dict[str, Any]:
    """读取目录下最新 JSON 报告。"""

    paths = [path for path in directory.rglob(pattern) if path.is_file()]
    if not paths:
        return {"exists": False, "path": "", "data": {}}
    latest = max(paths, key=lambda item: item.stat().st_mtime)
    return read_json_report(latest)


def summarize_report_data(data: dict[str, Any]) -> dict[str, Any]:
    """压缩报告内容，避免 Dashboard 一次返回过大 JSON。"""

    if "score" in data and "results" in data:
        return {
            "suite": data.get("suite", ""),
            "provider": data.get("provider", ""),
            "score": data.get("score", 0),
            "safety_score": data.get("safety_score", 0),
            "total_cases": data.get("total_cases", 0),
            "passed_cases": data.get("passed_cases", 0),
            "generated_at": data.get("generated_at", 0),
            "results": data.get("results", []),
        }
    event = data.get("event") if isinstance(data.get("event"), dict) else {}
    agent_result = data.get("agent_result") if isinstance(data.get("agent_result"), dict) else {}
    return {
        "trace_id": data.get("trace_id") or agent_result.get("trace_id") or "",
        "workflow_type": data.get("workflow_type") or agent_result.get("workflow_type") or "",
        "status": data.get("status") or agent_result.get("status") or "",
        "summary": event.get("summary") or data.get("summary") or "",
        "event_id": event.get("event_id") or "",
        "allow_write": data.get("allow_write", False),
        "identity": data.get("identity", ""),
    }


def parse_m3_stdout(output: str) -> dict[str, Any]:
    """从 M3 live stdout 中提取关键字段，完整报告仍以 report path 为准。"""

    parsed: dict[str, Any] = {
        "trace_id": "",
        "workflow_type": "",
        "status": "",
        "report_markdown": "",
        "report_json": "",
    }
    for key in ("trace_id", "workflow_type", "status"):
        match = re.search(rf"{key}:\s*([^\s]+)", output)
        if match:
            parsed[key] = match.group(1)
    for key in ("report_markdown", "report_json"):
        match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', output)
        if match:
            parsed[key] = match.group(1)
    return parsed


def redact_sensitive(text: str) -> str:
    """脱敏命令输出，避免前端展示敏感字段。"""

    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(r"\1***", redacted)
    return redacted


def command_for_display(command: list[str]) -> list[str]:
    """返回可展示命令，隐藏本地实现不需要暴露的细节。"""

    return [redact_sensitive(part) for part in command]


def make_api(settings: Settings | None = None) -> MeetFlowConsoleAPI:
    """创建默认 Console API 实例，便于 server 和测试复用。"""

    return MeetFlowConsoleAPI(settings=settings)
