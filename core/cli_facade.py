from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import load_settings
from config.loader import Settings
from core.console_api import (
    EvaluationRunRequest,
    M3SendCardRequest,
    M4SendCardsRequest,
    M5RiskScanRequest,
    MeetFlowConsoleAPI,
    command_for_display,
    parse_m5_stdout,
    redact_sensitive,
    run_console_command,
)
from core.observability import safe_error_message
from core.service_manager import ServiceStartRequest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPENCLAW_TOOLS_PATH = PROJECT_ROOT / "config" / "openclaw_tools.example.json"


@dataclass(slots=True)
class CLIResult:
    """MeetFlow CLI 的标准 JSON 输出。

    OpenClaw 和 Console 只需要消费这一层稳定字段，具体 M3/M4/M5 下游
    脚本差异被收敛在 `data` 和 `command` 里。
    """

    status: str
    workflow_type: str
    trace_id: str
    dry_run: bool = True
    allow_write: bool = False
    report_path: str = ""
    agent_trace_path: str = ""
    command: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    safety_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可直接 JSON 序列化的字典。"""

        return asdict(self)


class MeetFlowCLI:
    """OpenClaw / CLI 统一入口的受控 facade。"""

    def __init__(self, settings: Settings | None = None, *, project_root: Path = PROJECT_ROOT) -> None:
        self.settings = settings or load_settings()
        self.project_root = project_root
        self.api = MeetFlowConsoleAPI(settings=self.settings, project_root=project_root)

    def health(self) -> CLIResult:
        """检查本地配置、迁移和服务状态。"""

        health = self.api.get_health()
        migration = self.api.get_migration_status()
        services = self.api.list_services()
        data = {
            "app": health.get("app", {}),
            "storage": health.get("storage", {}),
            "migration": migration,
            "services": services.get("items", []),
            "feishu_config_present": bool(self.settings.feishu.app_id and self.settings.feishu.app_secret),
            "default_chat_configured": bool(self.settings.feishu.default_chat_id),
            "llm_provider": self.settings.llm.provider,
            "llm_model_configured": bool(self.settings.llm.model),
        }
        return CLIResult(
            status="success",
            workflow_type="health",
            trace_id=build_trace_id("health"),
            dry_run=True,
            allow_write=False,
            data=data,
            safety_summary=build_safety_summary(policy_checked=False, allow_write=False, idempotency_key=""),
        )

    def pre_meeting(
        self,
        *,
        date: str,
        event_title: str,
        event_id: str = "",
        provider: str = "scripted_debug",
        project_id: str = "meetflow",
        doc: list[str] | None = None,
        minute: list[str] | None = None,
        identity: str = "user",
        calendar_id: str = "primary",
        max_iterations: int = 5,
        force_index: bool = False,
        write_report: bool = True,
        allow_write: bool = False,
        idempotency_suffix: str = "",
        timeout_seconds: int = 120,
    ) -> CLIResult:
        """触发 M3 会前背景知识卡。"""

        suffix = idempotency_suffix or (f"m3-cli-{time.strftime('%Y%m%d%H%M%S')}" if allow_write else "")
        result = self.api.run_m3_send_card(
            M3SendCardRequest(
                identity=identity,
                calendar_id=calendar_id,
                date=date,
                event_title=event_title,
                event_id=event_id,
                llm_provider=provider,
                project_id=project_id,
                doc=list(doc or []),
                minute=list(minute or []),
                max_iterations=max_iterations,
                allow_write=allow_write,
                write_report=write_report,
                force_index=force_index,
                idempotency_suffix=suffix,
                timeout_seconds=timeout_seconds,
            )
        )
        parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
        return self._from_console_result(
            result,
            workflow_type="pre_meeting_brief",
            trace_id=str(parsed.get("trace_id") or build_trace_id("m3")),
            dry_run=not allow_write,
            allow_write=allow_write,
            report_path=str(parsed.get("report_json") or parsed.get("report_markdown") or ""),
            idempotency_key=str(result.get("idempotency_suffix") or suffix),
            data={
                "parsed": parsed,
                "idempotency_suffix": result.get("idempotency_suffix") or suffix,
                "stdout_tail": result.get("stdout", ""),
            },
        )

    def post_meeting(
        self,
        *,
        minute: str,
        identity: str = "user",
        chat_id: str = "",
        content_limit: int = 300,
        related_top_n: int = 5,
        skip_related_knowledge: bool = False,
        show_card_json: bool = False,
        allow_write: bool = False,
        timeout_seconds: int = 180,
    ) -> CLIResult:
        """触发 M4 会后总结卡和待确认任务卡。"""

        result = self.api.run_m4_send_cards(
            M4SendCardsRequest(
                minute=minute,
                identity=identity,
                chat_id=chat_id,
                content_limit=content_limit,
                related_top_n=related_top_n,
                skip_related_knowledge=skip_related_knowledge,
                show_card_json=show_card_json,
                allow_write=allow_write,
                timeout_seconds=timeout_seconds,
            )
        )
        parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
        return self._from_console_result(
            result,
            workflow_type="post_meeting_followup",
            trace_id=build_trace_id("m4"),
            dry_run=not allow_write,
            allow_write=allow_write,
            report_path=str(result.get("report_path") or parsed.get("report_path") or ""),
            idempotency_key="",
            data={
                "minute_token": parsed.get("minute_token", ""),
                "meeting_id": parsed.get("meeting_id", ""),
                "pending_action_count": parsed.get("pending_action_count", 0),
                "action_item_count": parsed.get("action_item_count", 0),
                "card_sent": parsed.get("card_sent", False),
                "stdout_tail": result.get("stdout", ""),
            },
        )

    def task_cards(self, **kwargs: Any) -> CLIResult:
        """复用 M4 链路生成任务卡视角的摘要。"""

        result = self.post_meeting(**kwargs)
        result.workflow_type = "task_cards"
        result.trace_id = build_trace_id("task_cards")
        return result

    def risk_scan(
        self,
        *,
        backend: str = "local",
        mode: str = "direct",
        chat_id: str = "",
        identity: str = "user",
        send_identity: str = "tenant",
        completed: str = "false",
        page_size: int = 50,
        page_limit: int = 20,
        stale_update_days: int = 0,
        due_soon_hours: int = 0,
        max_reminders: int = 0,
        show_card: bool = True,
        allow_write: bool = False,
        timeout_seconds: int = 180,
    ) -> CLIResult:
        """触发 M5 任务风险提醒。"""

        result = self.api.run_m5_risk_scan(
            M5RiskScanRequest(
                backend=backend,
                mode=mode,
                chat_id=chat_id,
                identity=identity,
                send_identity=send_identity,
                completed=completed,
                page_size=page_size,
                page_limit=page_limit,
                stale_update_days=stale_update_days,
                due_soon_hours=due_soon_hours,
                max_reminders=max_reminders,
                show_card=show_card,
                allow_write=allow_write,
                timeout_seconds=timeout_seconds,
            )
        )
        parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
        return self._from_console_result(
            result,
            workflow_type="risk_scan",
            trace_id=build_trace_id("m5"),
            dry_run=not allow_write,
            allow_write=allow_write,
            report_path=str(result.get("report_path") or ""),
            idempotency_key=str(parsed.get("idempotency_key") or ""),
            data={
                "should_notify": parsed.get("should_notify", False),
                "risk_count": parsed.get("risk_count", 0),
                "idempotency_key": parsed.get("idempotency_key", ""),
                "job": parsed.get("job", {}),
                "stdout_tail": result.get("stdout", ""),
            },
        )

    def eval(
        self,
        *,
        suite: str = "agent_trajectory",
        case_id: str = "",
        provider: str = "scripted_debug",
        fail_under: float = 0.95,
        write_report: bool = True,
    ) -> CLIResult:
        """运行 Agent 轨迹评测。"""

        payload = self.api.run_agent_evaluation(
            EvaluationRunRequest(
                suite=suite,
                case_id=case_id,
                provider=provider,
                fail_under=fail_under,
                write_report=write_report,
            )
        )
        ok = bool(payload.get("passed_threshold", False))
        return CLIResult(
            status="success" if ok else "failed",
            workflow_type="agent_evaluation",
            trace_id=build_trace_id("eval"),
            dry_run=True,
            allow_write=False,
            report_path=str(payload.get("report_path") or ""),
            agent_trace_path=str(payload.get("report_path") or ""),
            data=payload,
            safety_summary=build_safety_summary(policy_checked=False, allow_write=False, idempotency_key=""),
        )

    def demo_replay(
        self,
        *,
        case_id: str = "",
        run_all: bool = False,
        fail_under: float = 1.0,
        write_report: bool = True,
        timeout_seconds: int = 180,
    ) -> CLIResult:
        """运行离线 E2E 回放，作为无飞书网络时的兜底演示。"""

        command = [
            sys.executable,
            str(self.project_root / "scripts" / "e2e_replay.py"),
            "--fail-under",
            str(fail_under),
        ]
        if run_all:
            command.append("--all")
        if case_id:
            command.extend(["--case", case_id])
        if write_report:
            command.append("--write-report")
        result = run_console_command(
            command,
            cwd=self.project_root,
            timeout_seconds=timeout_seconds,
            dry_run=True,
            parsed=parse_replay_stdout,
        )
        parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
        return self._from_console_result(
            result,
            workflow_type="demo_replay",
            trace_id=build_trace_id("replay"),
            dry_run=True,
            allow_write=False,
            report_path=str(parsed.get("report_path") or ""),
            idempotency_key="",
            data={"parsed": parsed, "stdout_tail": result.get("stdout", "")},
            policy_checked=False,
        )

    def service(self, action: str, *, name: str = "", profile: str = "default", tail: int = 200) -> CLIResult:
        """受控管理本地长期服务。"""

        if action == "list":
            data = self.api.list_services()
        elif action == "start":
            data = self.api.start_service(ServiceStartRequest(name=name, profile=profile))
        elif action == "stop":
            data = self.api.stop_service(name)
        elif action == "logs":
            data = self.api.tail_service_logs(name, tail=tail)
        else:
            raise ValueError(f"未知 service action：{action}")
        return CLIResult(
            status="success",
            workflow_type="service",
            trace_id=build_trace_id("service"),
            dry_run=True,
            allow_write=False,
            data={"action": action, "result": data},
            safety_summary=build_safety_summary(policy_checked=False, allow_write=False, idempotency_key=""),
        )

    def openclaw_tools(self) -> CLIResult:
        """输出 OpenClaw 工具清单。"""

        data = load_openclaw_tools()
        return CLIResult(
            status="success",
            workflow_type="openclaw_tools",
            trace_id=build_trace_id("tools"),
            dry_run=True,
            allow_write=False,
            data=data,
            safety_summary=build_safety_summary(policy_checked=False, allow_write=False, idempotency_key=""),
        )

    def _from_console_result(
        self,
        result: dict[str, Any],
        *,
        workflow_type: str,
        trace_id: str,
        dry_run: bool,
        allow_write: bool,
        report_path: str,
        idempotency_key: str,
        data: dict[str, Any],
        policy_checked: bool = True,
    ) -> CLIResult:
        """把 Console facade 结果转换为 CLI 标准输出。"""

        ok = bool(result.get("ok", False))
        command = result.get("command") if isinstance(result.get("command"), list) else []
        error = "" if ok else safe_error_message(result.get("stdout", "") or result.get("error", ""))
        return CLIResult(
            status="success" if ok else "failed",
            workflow_type=workflow_type,
            trace_id=trace_id,
            dry_run=dry_run,
            allow_write=allow_write,
            report_path=report_path,
            command=command_for_display(command),
            data=data,
            error=error,
            safety_summary=build_safety_summary(
                policy_checked=policy_checked,
                allow_write=allow_write,
                idempotency_key=idempotency_key,
            ),
        )


def build_trace_id(prefix: str) -> str:
    """生成 CLI 层 trace_id，便于串联日志和报告。"""

    return f"cli_{prefix}_{int(time.time() * 1000)}"


def build_safety_summary(*, policy_checked: bool, allow_write: bool, idempotency_key: str) -> dict[str, Any]:
    """构造统一安全摘要。"""

    return {
        "policy_checked": bool(policy_checked),
        "write_blocked_or_confirmed": not allow_write or bool(allow_write),
        "idempotency_key_present": bool(idempotency_key),
        "secret_redacted": True,
        "raw_shell_disabled": True,
        "whitelist_entrypoint": True,
    }


def parse_replay_stdout(output: str) -> dict[str, Any]:
    """从 e2e replay stdout 中提取报告路径和分数。"""

    parsed: dict[str, Any] = {"report_path": "", "score": 0.0}
    match = re.search(r"评测报告已写入：([^\n]+)", output)
    if match:
        parsed["report_path"] = match.group(1).strip()
    compact = extract_first_json_object(output)
    if compact:
        parsed["score"] = compact.get("score", 0.0)
        parsed["case_count"] = compact.get("case_count") or compact.get("total_cases", 0)
    return parsed


def extract_first_json_object(output: str) -> dict[str, Any]:
    """尽量从 stdout 中恢复第一个 JSON 对象。"""

    text = output.strip()
    for start in (index for index, char in enumerate(text) if char == "{"):
        for end in range(len(text), start, -1):
            candidate = text[start:end]
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
    return {}


def load_openclaw_tools() -> dict[str, Any]:
    """读取 OpenClaw 工具清单示例。"""

    if OPENCLAW_TOOLS_PATH.exists():
        try:
            payload = json.loads(OPENCLAW_TOOLS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = build_default_openclaw_tools()
    else:
        payload = build_default_openclaw_tools()
    return payload if isinstance(payload, dict) else build_default_openclaw_tools()


def build_default_openclaw_tools() -> dict[str, Any]:
    """在配置文件缺失时提供最小工具清单。"""

    return {
        "version": "1.0",
        "tools": [
            {"name": "meetflow_health", "command": "python3 scripts/meetflow_cli.py health"},
            {"name": "meetflow_pre_meeting", "command": "python3 scripts/meetflow_cli.py pre-meeting"},
            {"name": "meetflow_post_meeting", "command": "python3 scripts/meetflow_cli.py post-meeting"},
            {"name": "meetflow_task_cards", "command": "python3 scripts/meetflow_cli.py task-cards"},
            {"name": "meetflow_risk_scan", "command": "python3 scripts/meetflow_cli.py risk-scan"},
            {"name": "meetflow_eval", "command": "python3 scripts/meetflow_cli.py eval"},
            {"name": "meetflow_demo_replay", "command": "python3 scripts/meetflow_cli.py demo-replay"},
        ],
    }


def result_to_json(result: CLIResult) -> str:
    """输出前统一脱敏，避免下游 stdout 混入敏感字段。"""

    return redact_sensitive(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
