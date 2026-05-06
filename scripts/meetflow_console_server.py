from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

# 允许直接通过 `python3 scripts/meetflow_console_server.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.console_api import (
    ConsoleAPIError,
    EvaluationRunRequest,
    M3SendCardRequest,
    M4ReadMinuteRequest,
    M4SendCardsRequest,
    M5RiskScanRequest,
    MeetFlowConsoleAPI,
    make_api,
)
from core.service_manager import ServiceManagerError, ServiceStartRequest


def parse_args() -> argparse.Namespace:
    """解析 MeetFlow Console 本地服务参数。"""

    parser = argparse.ArgumentParser(description="MeetFlow Console 本地 HTTP API 服务。")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认只监听本机。")
    parser.add_argument("--port", type=int, default=8787, help="监听端口。")
    parser.add_argument("--static-dir", default=str(PROJECT_ROOT / "frontend" / "dist"), help="前端静态资源目录。")
    return parser.parse_args()


def main() -> int:
    """启动本地控制台 HTTP 服务。"""

    args = parse_args()
    api = make_api()
    handler = build_handler(api=api, static_dir=Path(args.static_dir))
    server = ThreadingHTTPServer((args.host, int(args.port)), handler)
    print(f"MeetFlow Console API 已启动：http://{args.host}:{args.port}")
    print("API 健康检查：/api/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMeetFlow Console API 已停止。")
    finally:
        server.server_close()
    return 0


def build_handler(api: MeetFlowConsoleAPI, static_dir: Path) -> type[BaseHTTPRequestHandler]:
    """构造绑定 API 实例的 request handler。"""

    class MeetFlowConsoleHandler(BaseHTTPRequestHandler):
        """本地控制台 HTTP handler。"""

        server_version = "MeetFlowConsole/0.1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 固定方法名
            """处理 GET 请求。"""

            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/api/health":
                    self.write_json({"ok": True, "data": api.get_health(), "error": ""})
                    return
                if parsed.path == "/api/dashboard":
                    self.write_json({"ok": True, "data": api.get_dashboard(), "error": ""})
                    return
                if parsed.path == "/api/jobs":
                    self.write_json(
                        {
                            "ok": True,
                            "data": api.list_jobs(
                                limit=int(first_query(query, "limit", "50")),
                                status=first_query(query, "status", ""),
                                queue_name=first_query(query, "queue_name", ""),
                            ),
                            "error": "",
                        }
                    )
                    return
                if parsed.path == "/api/reports/latest":
                    self.write_json(
                        {
                            "ok": True,
                            "data": api.get_latest_report(first_query(query, "type", "evaluation")),
                            "error": "",
                        }
                    )
                    return
                if parsed.path == "/api/migrations/status":
                    self.write_json({"ok": True, "data": api.get_migration_status(), "error": ""})
                    return
                if parsed.path == "/api/services":
                    self.write_json({"ok": True, "data": api.list_services(), "error": ""})
                    return
                if parsed.path == "/api/services/logs":
                    self.write_json(
                        {
                            "ok": True,
                            "data": api.tail_service_logs(
                                first_query(query, "name", ""),
                                tail=int(first_query(query, "tail", "200")),
                            ),
                            "error": "",
                        }
                    )
                    return
                if parsed.path == "/api/m4/review-sessions":
                    self.write_json(
                        {"ok": True, "data": api.list_review_sessions(limit=int(first_query(query, "limit", "20"))), "error": ""}
                    )
                    return
                if parsed.path == "/api/m4/pending-actions":
                    self.write_json(
                        {"ok": True, "data": api.list_pending_actions(limit=int(first_query(query, "limit", "20"))), "error": ""}
                    )
                    return
                if parsed.path == "/api/m4/task-mappings":
                    self.write_json(
                        {"ok": True, "data": api.list_task_mappings(limit=int(first_query(query, "limit", "20"))), "error": ""}
                    )
                    return
                if parsed.path == "/api/m5/risk-notifications":
                    self.write_json(
                        {
                            "ok": True,
                            "data": api.list_risk_notifications(limit=int(first_query(query, "limit", "20"))),
                            "error": "",
                        }
                    )
                    return
                self.serve_static(parsed.path)
            except Exception as error:  # noqa: BLE001 - API 层需要统一错误响应。
                self.write_error(error)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 固定方法名
            """处理 POST 请求。"""

            parsed = urlparse(self.path)
            try:
                payload = self.read_json_body()
                if parsed.path == "/api/evaluation/run":
                    request = EvaluationRunRequest(
                        suite=str(payload.get("suite") or "agent_trajectory"),
                        case_id=str(payload.get("case_id") or ""),
                        provider=str(payload.get("provider") or "scripted_debug"),
                        fail_under=float(payload.get("fail_under") or 0.95),
                        write_report=bool(payload.get("write_report", True)),
                    )
                    self.write_json({"ok": True, "data": api.run_agent_evaluation(request), "error": ""})
                    return
                if parsed.path == "/api/m3/send-card":
                    request = M3SendCardRequest(
                        date=str(payload.get("date") or "tomorrow"),
                        event_title=str(payload.get("event_title") or ""),
                        event_id=str(payload.get("event_id") or ""),
                        llm_provider=str(payload.get("llm_provider") or "scripted_debug"),
                        project_id=str(payload.get("project_id") or "meetflow"),
                        allow_write=bool(payload.get("allow_write", False)),
                        write_report=bool(payload.get("write_report", True)),
                        force_index=bool(payload.get("force_index", False)),
                        idempotency_suffix=str(payload.get("idempotency_suffix") or ""),
                    )
                    self.write_json({"ok": True, "data": api.run_m3_send_card(request), "error": ""})
                    return
                if parsed.path == "/api/worker/run-once":
                    self.write_json(
                        {
                            "ok": True,
                            "data": api.run_worker_once(dry_run=bool(payload.get("dry_run", True))),
                            "error": "",
                        }
                    )
                    return
                if parsed.path == "/api/services/start":
                    request = ServiceStartRequest(
                        name=str(payload.get("name") or ""),
                        profile=str(payload.get("profile") or "default"),
                        force_restart=bool(payload.get("force_restart", False)),
                    )
                    self.write_json({"ok": True, "data": api.start_service(request), "error": ""})
                    return
                if parsed.path == "/api/services/stop":
                    self.write_json({"ok": True, "data": api.stop_service(str(payload.get("name") or "")), "error": ""})
                    return
                if parsed.path == "/api/m4/read-minute":
                    request = M4ReadMinuteRequest(
                        minute=str(payload.get("minute") or ""),
                        identity=str(payload.get("identity") or "user"),
                        content_limit=int(payload.get("content_limit") or 800),
                        show_card_json=bool(payload.get("show_card_json", False)),
                        timeout_seconds=int(payload.get("timeout_seconds") or 180),
                    )
                    self.write_json({"ok": True, "data": api.run_m4_read_minute(request), "error": ""})
                    return
                if parsed.path == "/api/m4/send-cards":
                    request = M4SendCardsRequest(
                        minute=str(payload.get("minute") or ""),
                        identity=str(payload.get("identity") or "user"),
                        chat_id=str(payload.get("chat_id") or ""),
                        receive_id_type=str(payload.get("receive_id_type") or "chat_id"),
                        content_limit=int(payload.get("content_limit") or 300),
                        related_top_n=int(payload.get("related_top_n") or 5),
                        skip_related_knowledge=bool(payload.get("skip_related_knowledge", False)),
                        show_card_json=bool(payload.get("show_card_json", False)),
                        allow_write=bool(payload.get("allow_write", False)),
                        timeout_seconds=int(payload.get("timeout_seconds") or 180),
                    )
                    self.write_json({"ok": True, "data": api.run_m4_send_cards(request), "error": ""})
                    return
                if parsed.path == "/api/m5/risk-scan":
                    request = M5RiskScanRequest(
                        backend=str(payload.get("backend") or "local"),
                        mode=str(payload.get("mode") or "direct"),
                        chat_id=str(payload.get("chat_id") or ""),
                        identity=str(payload.get("identity") or "user"),
                        send_identity=str(payload.get("send_identity") or "tenant"),
                        completed=str(payload.get("completed") or "false"),
                        page_size=int(payload.get("page_size") or 50),
                        page_limit=int(payload.get("page_limit") or 20),
                        stale_update_days=int(payload.get("stale_update_days") or 0),
                        due_soon_hours=int(payload.get("due_soon_hours") or 0),
                        max_reminders=int(payload.get("max_reminders") or 0),
                        show_card=bool(payload.get("show_card", True)),
                        allow_write=bool(payload.get("allow_write", False)),
                        timeout_seconds=int(payload.get("timeout_seconds") or 180),
                    )
                    self.write_json({"ok": True, "data": api.run_m5_risk_scan(request), "error": ""})
                    return
                self.write_json({"ok": False, "data": {}, "error": "not found"}, status=404)
            except Exception as error:  # noqa: BLE001 - API 层需要统一错误响应。
                self.write_error(error)

        def read_json_body(self) -> dict[str, Any]:
            """读取 JSON body。"""

            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body or "{}")

        def write_json(self, payload: dict[str, Any], status: int = 200) -> None:
            """写 JSON 响应。"""

            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 固定方法名
            """处理浏览器 CORS 预检。"""

            self.write_json({"ok": True, "data": {}, "error": ""})

        def write_error(self, error: BaseException) -> None:
            """写统一错误响应。"""

            status = 400 if isinstance(error, (ConsoleAPIError, ServiceManagerError, ValueError, json.JSONDecodeError)) else 500
            self.write_json({"ok": False, "data": {}, "error": str(error)}, status=status)

        def serve_static(self, request_path: str) -> None:
            """服务 frontend/dist 静态资源；缺失时返回 API 提示。"""

            if not static_dir.exists():
                self.write_json(
                    {
                        "ok": True,
                        "data": {"message": "MeetFlow Console API running", "static_dir": str(static_dir)},
                        "error": "",
                    }
                )
                return
            relative = request_path.lstrip("/") or "index.html"
            path = (static_dir / relative).resolve()
            if not str(path).startswith(str(static_dir.resolve())) or not path.exists() or path.is_dir():
                path = static_dir / "index.html"
            data = path.read_bytes()
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 父类签名如此。
            """压缩 HTTP 访问日志，避免干扰脚本输出。"""

            sys.stderr.write("[console] " + format % args + "\n")

    return MeetFlowConsoleHandler


def first_query(query: dict[str, list[str]], key: str, default: str) -> str:
    """读取 query 参数第一个值。"""

    values = query.get(key) or []
    return str(values[0]) if values else default


if __name__ == "__main__":
    raise SystemExit(main())
