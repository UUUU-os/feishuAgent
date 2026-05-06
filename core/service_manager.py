from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ManagedServiceStatus:
    """Console 管理的本地长期服务状态。

    这里只记录进程和日志位置，避免把飞书 token、LLM key 等敏感配置带到前端。
    """

    name: str
    profile: str
    status: str
    pid: int
    started_at: int
    command: list[str]
    log_path: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转成前端可直接消费的字典。"""

        return asdict(self)


@dataclass(slots=True)
class ServiceStartRequest:
    """启动本地长期服务的请求。"""

    name: str
    profile: str = "default"
    force_restart: bool = False


class ServiceManagerError(RuntimeError):
    """本地服务管理错误。"""


class ServiceManager:
    """管理 MeetFlow Console 启动的长期服务进程。

    Console 只允许启动固定 profile，避免前端把本地控制台变成任意命令执行器。
    """

    def __init__(
        self,
        project_root: Path,
        *,
        runtime_dir: Path | None = None,
        profiles: dict[str, dict[str, list[str]]] | None = None,
    ) -> None:
        self.project_root = project_root
        self.runtime_dir = runtime_dir or project_root / "storage" / "runtime"
        self.logs_dir = self.runtime_dir / "logs"
        self.state_path = self.runtime_dir / "services.json"
        self.profiles = profiles or build_default_profiles(project_root)

    def list_services(self) -> dict[str, Any]:
        """返回所有白名单服务的状态，并刷新已退出进程。"""

        state = self._read_state()
        items: list[dict[str, Any]] = []
        changed = False
        for name, profiles in self.profiles.items():
            raw = state.get(name)
            if isinstance(raw, dict):
                status = self._status_from_raw(raw)
            else:
                status = self._stopped_status(name=name, profile=next(iter(profiles)))
            refreshed = self._refresh_status(status)
            changed = changed or refreshed.status != status.status
            state[name] = refreshed.to_dict()
            items.append(refreshed.to_dict())
        if changed:
            self._write_state(state)
        return {"items": items}

    def start_service(self, request: ServiceStartRequest) -> dict[str, Any]:
        """按白名单 profile 启动服务。"""

        name = normalize_name(request.name)
        profile = normalize_name(request.profile or "default")
        command = self._command_for(name=name, profile=profile)
        state = self._read_state()
        existing = self._refresh_status(
            self._status_from_raw(state[name]) if isinstance(state.get(name), dict) else self._stopped_status(name, profile)
        )
        if existing.status == "running" and not request.force_restart:
            state[name] = existing.to_dict()
            self._write_state(state)
            return existing.to_dict()
        if existing.status == "running":
            self._stop_status(existing)

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / f"{name}.log"
        log_file = log_path.open("ab")
        try:
            process = subprocess.Popen(
                command,
                cwd=self.project_root,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_file.close()
        status = ManagedServiceStatus(
            name=name,
            profile=profile,
            status="running",
            pid=int(process.pid),
            started_at=int(time.time()),
            command=command_for_display(command),
            log_path=str(log_path),
        )
        state[name] = status.to_dict()
        self._write_state(state)
        return status.to_dict()

    def stop_service(self, name: str) -> dict[str, Any]:
        """停止由 Console 启动并记录的服务。"""

        service_name = normalize_name(name)
        state = self._read_state()
        raw = state.get(service_name)
        status = self._status_from_raw(raw) if isinstance(raw, dict) else self._stopped_status(service_name, "default")
        refreshed = self._refresh_status(status)
        if refreshed.status == "running":
            self._stop_status(refreshed)
        stopped = ManagedServiceStatus(
            name=service_name,
            profile=refreshed.profile,
            status="stopped",
            pid=0,
            started_at=refreshed.started_at,
            command=refreshed.command,
            log_path=refreshed.log_path,
            error="",
        )
        state[service_name] = stopped.to_dict()
        self._write_state(state)
        return stopped.to_dict()

    def tail_logs(self, name: str, *, tail: int = 200) -> dict[str, Any]:
        """读取服务日志尾部，避免前端一次加载过大的日志文件。"""

        service_name = normalize_name(name)
        state = self._read_state()
        raw = state.get(service_name)
        status = self._status_from_raw(raw) if isinstance(raw, dict) else self._stopped_status(service_name, "default")
        log_path = Path(status.log_path) if status.log_path else self.logs_dir / f"{service_name}.log"
        if not log_path.exists():
            return {"name": service_name, "log_path": str(log_path), "content": ""}
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        limit = max(1, min(int(tail or 200), 2000))
        return {"name": service_name, "log_path": str(log_path), "content": "\n".join(lines[-limit:])}

    def _command_for(self, *, name: str, profile: str) -> list[str]:
        """读取白名单服务命令。"""

        if name not in self.profiles:
            raise ServiceManagerError(f"未知服务：{name}")
        profiles = self.profiles[name]
        if profile not in profiles:
            raise ServiceManagerError(f"服务 {name} 不支持 profile：{profile}")
        return [str(part) for part in profiles[profile]]

    def _status_from_raw(self, raw: dict[str, Any]) -> ManagedServiceStatus:
        """从状态文件恢复服务状态。"""

        return ManagedServiceStatus(
            name=str(raw.get("name") or ""),
            profile=str(raw.get("profile") or "default"),
            status=str(raw.get("status") or "stopped"),
            pid=int(raw.get("pid") or 0),
            started_at=int(raw.get("started_at") or 0),
            command=[str(item) for item in raw.get("command") or []],
            log_path=str(raw.get("log_path") or ""),
            error=str(raw.get("error") or ""),
        )

    def _stopped_status(self, name: str, profile: str) -> ManagedServiceStatus:
        """生成默认 stopped 状态。"""

        command = self.profiles.get(name, {}).get(profile, [])
        return ManagedServiceStatus(
            name=name,
            profile=profile,
            status="stopped",
            pid=0,
            started_at=0,
            command=command_for_display(command),
            log_path=str(self.logs_dir / f"{name}.log"),
        )

    def _refresh_status(self, status: ManagedServiceStatus) -> ManagedServiceStatus:
        """根据 PID 存活情况刷新状态。"""

        if status.status != "running" or status.pid <= 0:
            return status
        if is_pid_alive(status.pid):
            return status
        status.status = "stopped"
        status.pid = 0
        return status

    def _stop_status(self, status: ManagedServiceStatus) -> None:
        """停止单个运行中的服务进程。"""

        if status.pid <= 0 or not is_pid_alive(status.pid):
            return
        try:
            os.killpg(status.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError as error:
            raise ServiceManagerError(f"没有权限停止服务 {status.name} pid={status.pid}") from error
        deadline = time.time() + 5
        while time.time() < deadline:
            if not is_pid_alive(status.pid):
                return
            time.sleep(0.1)
        try:
            os.killpg(status.pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def _read_state(self) -> dict[str, Any]:
        """读取服务状态文件。"""

        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, state: dict[str, Any]) -> None:
        """原子写入服务状态，避免进程退出时留下半截 JSON。"""

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.state_path)


def build_default_profiles(project_root: Path) -> dict[str, dict[str, list[str]]]:
    """构造 MeetFlow 本地联调服务白名单。"""

    meetflow_python = sys.executable
    sdk_python = str(project_root / ".venv-lark-oapi" / "bin" / "python")
    return {
        "worker": {
            "default": [
                meetflow_python,
                str(project_root / "scripts" / "meetflow_worker.py"),
                "--queues",
                "workflow,risk_scan,rag_refresh",
                "--poll-seconds",
                "2",
            ],
        },
        "sdk_callback": {
            "enqueue": [
                sdk_python,
                str(project_root / "scripts" / "feishu_event_sdk_server.py"),
                "--enqueue-agent",
                "--agent-provider",
                "dry-run",
                "--job-queue",
                "workflow",
                "--log-level",
                "info",
            ],
        },
        "m4_callback": {
            "default": [
                meetflow_python,
                str(project_root / "scripts" / "card_send_live.py"),
                "m4-callback",
                "--log-level",
                "info",
            ],
            "dry_run": [
                meetflow_python,
                str(project_root / "scripts" / "card_send_live.py"),
                "m4-callback",
                "--log-level",
                "info",
                "--dry-run",
            ],
        },
    }


def normalize_name(value: str) -> str:
    """标准化服务名和 profile 名。"""

    normalized = str(value or "").strip()
    if not normalized:
        raise ServiceManagerError("服务名不能为空。")
    if not all(char.isalnum() or char in {"_", "-"} for char in normalized):
        raise ServiceManagerError(f"服务名包含非法字符：{value}")
    return normalized


def is_pid_alive(pid: int) -> bool:
    """检查 PID 是否仍存活。"""

    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def command_for_display(command: list[str]) -> list[str]:
    """返回适合前端展示的命令副本。"""

    return [str(part) for part in command]
