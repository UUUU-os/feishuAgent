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
from core.service_manager import ServiceManager, ServiceStartRequest


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


@dataclass(slots=True)
class M4ReadMinuteRequest:
    """MeetFlow Console 触发 M4 妙记只读解析的请求。"""

    minute: str
    identity: str = "user"
    content_limit: int = 800
    show_card_json: bool = False
    timeout_seconds: int = 180


@dataclass(slots=True)
class M4SendCardsRequest:
    """MeetFlow Console 触发 M4 会后总结卡和待确认任务卡的请求。"""

    minute: str
    identity: str = "user"
    chat_id: str = ""
    receive_id_type: str = "chat_id"
    content_limit: int = 300
    related_top_n: int = 5
    skip_related_knowledge: bool = False
    show_card_json: bool = False
    allow_write: bool = False
    timeout_seconds: int = 180


@dataclass(slots=True)
class M5RiskScanRequest:
    """MeetFlow Console 触发 M5 风险巡检的请求。"""

    backend: str = "local"
    mode: str = "direct"
    chat_id: str = ""
    identity: str = "user"
    send_identity: str = "tenant"
    completed: str = "false"
    page_size: int = 50
    page_limit: int = 20
    stale_update_days: int = 0
    due_soon_hours: int = 0
    max_reminders: int = 0
    show_card: bool = True
    allow_write: bool = False
    timeout_seconds: int = 180


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
        self.service_manager = ServiceManager(project_root)

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
            "m5": self.get_latest_report("m5"),
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
        if normalized == "m5":
            return read_latest_glob_report(self.report_root / "m5", "*.json")
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

    def list_services(self) -> dict[str, Any]:
        """返回 Console 可管理的长期服务状态。"""

        return self.service_manager.list_services()

    def start_service(self, request: ServiceStartRequest) -> dict[str, Any]:
        """启动一个白名单长期服务。"""

        return self.service_manager.start_service(request)

    def stop_service(self, name: str) -> dict[str, Any]:
        """停止一个由 Console 启动的长期服务。"""

        return self.service_manager.stop_service(name)

    def tail_service_logs(self, name: str, *, tail: int = 200) -> dict[str, Any]:
        """读取长期服务日志尾部。"""

        return self.service_manager.tail_logs(name, tail=tail)

    def run_m4_read_minute(self, request: M4ReadMinuteRequest) -> dict[str, Any]:
        """只读解析真实飞书妙记，不发送卡片也不创建任务。"""

        validate_m4_read_minute_request(request)
        command = [
            sys.executable,
            str(self.project_root / "scripts" / "post_meeting_live_test.py"),
            "--minute",
            request.minute,
            "--identity",
            request.identity,
            "--read-only",
            "--content-limit",
            str(request.content_limit),
        ]
        if request.show_card_json:
            command.append("--show-card-json")
        return run_console_command(
            command,
            cwd=self.project_root,
            timeout_seconds=request.timeout_seconds,
            dry_run=True,
            parsed=parse_m4_stdout,
        )

    def run_m4_send_cards(self, request: M4SendCardsRequest) -> dict[str, Any]:
        """触发 M4 会后总结卡和待确认任务卡。未 allow_write 时只 dry-run 打印命令。"""

        validate_m4_send_cards_request(request)
        command = [
            sys.executable,
            str(self.project_root / "scripts" / "card_send_live.py"),
            "m4",
            "--minute",
            request.minute,
            "--identity",
            request.identity,
            "--receive-id-type",
            request.receive_id_type,
            "--content-limit",
            str(request.content_limit),
            "--related-top-n",
            str(request.related_top_n),
        ]
        if request.chat_id:
            command.extend(["--chat-id", request.chat_id])
        if request.skip_related_knowledge:
            command.append("--skip-related-knowledge")
        if request.show_card_json:
            command.append("--show-card-json")
        if not request.allow_write:
            command.append("--dry-run")
        return run_console_command(
            command,
            cwd=self.project_root,
            timeout_seconds=request.timeout_seconds,
            dry_run=not request.allow_write,
            parsed=parse_m4_stdout,
        )

    def run_m5_risk_scan(self, request: M5RiskScanRequest) -> dict[str, Any]:
        """触发 M5 风险巡检，支持直接执行或只入队。"""

        validate_m5_risk_scan_request(request)
        command = [
            sys.executable,
            str(self.project_root / "scripts" / "risk_scan_demo.py"),
            "--backend",
            request.backend,
            "--identity",
            request.identity,
            "--send-identity",
            request.send_identity,
            "--completed",
            request.completed,
            "--page-size",
            str(request.page_size),
            "--page-limit",
            str(request.page_limit),
        ]
        if request.chat_id:
            command.extend(["--chat-id", request.chat_id])
        for value, option in (
            (request.stale_update_days, "--stale-update-days"),
            (request.due_soon_hours, "--due-soon-hours"),
            (request.max_reminders, "--max-reminders"),
        ):
            if value:
                command.extend([option, str(value)])
        if request.show_card:
            command.append("--show-card")
        if request.allow_write:
            command.append("--allow-write")
        if request.mode == "enqueue":
            command.append("--enqueue")
        return run_console_command(
            command,
            cwd=self.project_root,
            timeout_seconds=request.timeout_seconds,
            dry_run=not request.allow_write,
            parsed=parse_m5_stdout,
        )

    def list_review_sessions(self, *, limit: int = 20) -> dict[str, Any]:
        """读取 M4 待确认任务 review session 摘要。"""

        return {"items": query_table_recent(Path(self.settings.storage.db_path), "review_sessions", limit=limit)}

    def list_pending_actions(self, *, limit: int = 20) -> dict[str, Any]:
        """读取 Agent pending action 摘要。"""

        return {"items": query_table_recent(Path(self.settings.storage.db_path), "pending_actions", limit=limit)}

    def list_task_mappings(self, *, limit: int = 20) -> dict[str, Any]:
        """读取 M4 到飞书任务的映射摘要，供 M5 排查。"""

        return {"items": query_table_recent(Path(self.settings.storage.db_path), "task_mappings", limit=limit)}

    def list_risk_notifications(self, *, limit: int = 20) -> dict[str, Any]:
        """读取 M5 风险提醒历史摘要。"""

        return {"items": query_table_recent(Path(self.settings.storage.db_path), "risk_notifications", limit=limit)}

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

    request.date = clean_text_argument("date", request.date)
    request.event_title = clean_text_argument("event_title", request.event_title)
    request.event_id = clean_text_argument("event_id", request.event_id)
    request.llm_provider = clean_text_argument("llm_provider", request.llm_provider)
    request.project_id = clean_text_argument("project_id", request.project_id)
    request.idempotency_suffix = clean_text_argument("idempotency_suffix", request.idempotency_suffix)
    if request.llm_provider not in {"scripted_debug", "dry-run", "configured", "deepseek"}:
        raise ConsoleAPIError(f"不支持的 llm_provider：{request.llm_provider}")
    if not request.event_title and not request.event_id:
        raise ConsoleAPIError("请至少提供 event_title 或 event_id。")
    if request.date and not re.match(r"^(today|tomorrow|\d{4}-\d{2}-\d{2})$", request.date):
        raise ConsoleAPIError("date 只支持 today / tomorrow / YYYY-MM-DD。")


def validate_m4_read_minute_request(request: M4ReadMinuteRequest) -> None:
    """校验 M4 妙记只读请求。"""

    request.minute = clean_text_argument("minute", request.minute)
    request.identity = clean_text_argument("identity", request.identity)
    if not str(request.minute or "").strip():
        raise ConsoleAPIError("请提供飞书妙记链接或 minute token。")
    if request.identity not in {"user", "tenant"}:
        raise ConsoleAPIError("identity 只支持 user / tenant。")
    validate_int_range("content_limit", request.content_limit, 100, 5000)
    validate_int_range("timeout_seconds", request.timeout_seconds, 10, 600)


def validate_m4_send_cards_request(request: M4SendCardsRequest) -> None:
    """校验 M4 发卡请求，避免前端传入不受控参数。"""

    request.minute = clean_text_argument("minute", request.minute)
    request.identity = clean_text_argument("identity", request.identity)
    request.chat_id = clean_text_argument("chat_id", request.chat_id)
    request.receive_id_type = clean_text_argument("receive_id_type", request.receive_id_type)
    if not str(request.minute or "").strip():
        raise ConsoleAPIError("请提供飞书妙记链接或 minute token。")
    if request.identity not in {"user", "tenant"}:
        raise ConsoleAPIError("identity 只支持 user / tenant。")
    if request.receive_id_type != "chat_id":
        raise ConsoleAPIError("第一阶段 receive_id_type 只支持 chat_id。")
    validate_int_range("content_limit", request.content_limit, 100, 5000)
    validate_int_range("related_top_n", request.related_top_n, 1, 8)
    validate_int_range("timeout_seconds", request.timeout_seconds, 10, 600)


def validate_m5_risk_scan_request(request: M5RiskScanRequest) -> None:
    """校验 M5 风险巡检请求。"""

    request.backend = clean_text_argument("backend", request.backend)
    request.mode = clean_text_argument("mode", request.mode)
    request.chat_id = clean_text_argument("chat_id", request.chat_id)
    request.identity = clean_text_argument("identity", request.identity)
    request.send_identity = clean_text_argument("send_identity", request.send_identity)
    request.completed = clean_text_argument("completed", request.completed)
    if request.backend not in {"local", "feishu"}:
        raise ConsoleAPIError("backend 只支持 local / feishu。")
    if request.mode not in {"direct", "enqueue"}:
        raise ConsoleAPIError("mode 只支持 direct / enqueue。")
    if request.identity not in {"user", "tenant"}:
        raise ConsoleAPIError("identity 只支持 user / tenant。")
    if request.send_identity not in {"user", "tenant"}:
        raise ConsoleAPIError("send_identity 只支持 user / tenant。")
    if request.completed not in {"true", "false", "all"}:
        raise ConsoleAPIError("completed 只支持 true / false / all。")
    validate_int_range("page_size", request.page_size, 1, 100)
    validate_int_range("page_limit", request.page_limit, 1, 100)
    validate_int_range("timeout_seconds", request.timeout_seconds, 10, 600)


def validate_int_range(name: str, value: int, minimum: int, maximum: int) -> None:
    """校验整数参数范围，避免脚本被异常大参数拖垮。"""

    if int(value) < minimum or int(value) > maximum:
        raise ConsoleAPIError(f"{name} 只支持 {minimum}..{maximum}。")


def clean_text_argument(name: str, value: str) -> str:
    """清洗前端传来的命令参数，避免不可见控制字符进入 subprocess。

    飞书链接和 chat_id 偶尔可能从网页复制时混入空字符；Python 在启动
    子进程时会直接抛出 `embedded null byte`，这里提前转成可读的业务错误。
    """

    text = str(value or "").strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ConsoleAPIError(f"{name} 包含不可见控制字符，请重新粘贴或手动输入。")
    return text


def validate_command_arguments(command: list[str]) -> None:
    """最后一道命令参数防线，避免 subprocess 抛出底层 ValueError。"""

    for index, part in enumerate(command):
        clean_text_argument(f"command[{index}]", part)


def run_console_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    dry_run: bool,
    parsed: Any | None = None,
) -> dict[str, Any]:
    """执行 Console 白名单命令，并统一脱敏输出。"""

    validate_command_arguments(command)
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=max(int(timeout_seconds or 60), 10),
        check=False,
    )
    output = redact_sensitive(completed.stdout or "")
    parsed_payload = parsed(output) if parsed else {}
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "dry_run": dry_run,
        "command": command_for_display(command),
        "stdout": output[-12000:],
        "stderr": "",
        "parsed": parsed_payload,
        "report_path": parsed_payload.get("report_path", "") if isinstance(parsed_payload, dict) else "",
        "job": parsed_payload.get("job", {}) if isinstance(parsed_payload, dict) else {},
    }


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


def query_table_recent(db_path: Path, table_name: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """读取指定运行表的最近记录；表不存在时返回空列表。"""

    allowed_tables = {"review_sessions", "pending_actions", "task_mappings", "risk_notifications"}
    if table_name not in allowed_tables or not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not table_exists(conn, table_name):
            return []
        columns = [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
        order_column = first_existing(columns, ["updated_at", "created_at", "notified_at", "applied_at"])
        order = f"ORDER BY {order_column} DESC" if order_column else ""
        rows = conn.execute(
            f"SELECT * FROM {table_name} {order} LIMIT ?",
            (max(int(limit or 20), 1),),
        ).fetchall()
    return [summarize_sql_row(dict(row)) for row in rows]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """判断 SQLite 表是否存在。"""

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def first_existing(columns: list[str], candidates: list[str]) -> str:
    """返回第一个存在的列名。"""

    for candidate in candidates:
        if candidate in columns:
            return candidate
    return ""


def summarize_sql_row(row: dict[str, Any]) -> dict[str, Any]:
    """压缩 SQLite 行，避免前端展示过大的 JSON 字段。"""

    summarized: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            summarized[key] = ""
            continue
        text = str(value)
        if key.endswith("_json") and len(text) > 1000:
            summarized[key] = text[:1000] + "...(truncated)"
        else:
            summarized[key] = value
    return summarized


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


def parse_m4_stdout(output: str) -> dict[str, Any]:
    """从 M4 stdout 中提取报告、妙记和任务确认摘要。"""

    parsed: dict[str, Any] = {
        "report_path": "",
        "minute_token": "",
        "meeting_id": "",
        "pending_action_count": 0,
        "action_item_count": 0,
        "card_sent": False,
    }
    compact = extract_last_json_object(output)
    if isinstance(compact, dict):
        parsed["report_path"] = str(compact.get("report_path") or "")
        workflow_input = compact.get("workflow_input") if isinstance(compact.get("workflow_input"), dict) else {}
        parsed["minute_token"] = str(workflow_input.get("minute_token") or workflow_input.get("source_id") or "")
        parsed["meeting_id"] = str(workflow_input.get("meeting_id") or "")
        for key, target in (
            ("pending_action_items", "pending_action_count"),
            ("action_items", "action_item_count"),
        ):
            value = compact.get(key)
            if isinstance(value, list):
                parsed[target] = len(value)
            elif isinstance(value, int):
                parsed[target] = value
        write_results = compact.get("write_results") if isinstance(compact.get("write_results"), dict) else {}
        parsed["card_sent"] = bool(write_results and not write_results.get("skipped", False))
    match = re.search(r'"report_path"\s*:\s*"([^"]+)"', output)
    if match and not parsed["report_path"]:
        parsed["report_path"] = match.group(1)
    return parsed


def parse_m5_stdout(output: str) -> dict[str, Any]:
    """从 M5 stdout 中提取风险巡检和入队摘要。"""

    parsed: dict[str, Any] = {
        "should_notify": False,
        "risk_count": 0,
        "idempotency_key": "",
        "job": {},
    }
    compact = extract_last_json_object(output)
    if isinstance(compact, dict):
        if "job_id" in compact:
            parsed["job"] = compact
        decision = compact.get("decision") if isinstance(compact.get("decision"), dict) else {}
        scan_result = compact.get("scan_result") if isinstance(compact.get("scan_result"), dict) else {}
        if decision:
            parsed["should_notify"] = bool(decision.get("should_notify", False))
            parsed["idempotency_key"] = str(decision.get("idempotency_key") or "")
        risks = scan_result.get("risks") if isinstance(scan_result.get("risks"), list) else compact.get("risks")
        if isinstance(risks, list):
            parsed["risk_count"] = len(risks)
    job_match = re.search(r'"job_id"\s*:\s*"([^"]+)"', output)
    if job_match and not parsed["job"]:
        parsed["job"] = {"job_id": job_match.group(1)}
    key_match = re.search(r'"idempotency_key"\s*:\s*"([^"]+)"', output)
    if key_match and not parsed["idempotency_key"]:
        parsed["idempotency_key"] = key_match.group(1)
    return parsed


def extract_last_json_object(output: str) -> dict[str, Any]:
    """尽量从脚本 stdout 尾部恢复一个 JSON 对象。"""

    text = output.strip()
    if not text:
        return {}
    for start in (index for index, char in enumerate(text) if char == "{"):
        candidate = text[start:]
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


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
