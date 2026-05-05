from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/feishu_event_server.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters.feishu_client import FeishuClient
from config import load_settings
from core.agent import create_meetflow_agent
from core.feishu_callback_dispatcher import FeishuCallbackDispatcher
from core.llm import DryRunLLMProvider
from core.logging import configure_logging, get_logger
from core.observability import configure_structured_events, emit_structured_event, safe_error_message
from core.policy import AgentPolicy
from core.storage import MeetFlowStorage


class FeishuEventServerState:
    """HTTP 回调服务共享状态。

    标准库 HTTP server 会为每个请求创建 handler 实例，因此把配置、路由器
    和可选 Agent 放在共享状态里。
    """

    def __init__(
        self,
        dispatcher: FeishuCallbackDispatcher,
        paths: set[str],
        execute_agent: bool,
        allow_write: bool,
        agent_provider: str,
    ) -> None:
        self.dispatcher = dispatcher
        self.paths = paths
        self.execute_agent = execute_agent
        self.allow_write = allow_write
        self.agent_provider = agent_provider
        self.logger = get_logger("meetflow.feishu_event_server")


class MeetFlowEventRequestHandler(BaseHTTPRequestHandler):
    """处理飞书事件回调的最小 HTTP Handler。"""

    server_version = "MeetFlowFeishuEventServer/0.1"

    def do_GET(self) -> None:  # noqa: N802 - 标准库要求方法名。
        """健康检查入口。"""

        if self.path != "/healthz":
            self._write_json({"error": "not_found"}, status=404)
            return
        self._write_json({"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802 - 标准库要求方法名。
        """接收飞书 POST 回调。"""

        state: FeishuEventServerState = self.server.state  # type: ignore[attr-defined]
        request_path = self.path.split("?", maxsplit=1)[0]
        if request_path not in state.paths:
            self._write_json({"error": "not_found"}, status=404)
            return

        try:
            payload = self._read_json_body()
            result = state.dispatcher.dispatch_http_callback(payload)
            self._write_json(result.body)

            if state.execute_agent and result.agent_input is not None:
                thread = threading.Thread(
                    target=run_agent_in_background,
                    args=(result.agent_input, state.allow_write, state.agent_provider),
                    daemon=True,
                )
                thread.start()
        except Exception as error:  # noqa: BLE001 - 回调服务必须稳定返回 JSON。
            safe_message = safe_error_message(error)
            state.logger.exception("飞书事件回调处理失败")
            emit_structured_event(
                "card_action_failed",
                trace_id="-",
                status="failed",
                error_type=error.__class__.__name__,
                error_message=safe_message,
            )
            self._write_json(
                {
                    "toast": {
                        "type": "error",
                        "content": f"卡片动作处理失败：{safe_message}",
                    }
                },
                status=200,
            )

    def log_message(self, format: str, *args: Any) -> None:
        """把标准库访问日志接到项目 logger。"""

        state: FeishuEventServerState = self.server.state  # type: ignore[attr-defined]
        state.logger.info("%s - %s", self.address_string(), format % args)

    def _read_json_body(self) -> dict[str, Any]:
        """读取 JSON 请求体。"""

        length = int(self.headers.get("Content-Length", "0") or 0)
        raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as error:
            raise ValueError("请求体不是合法 JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("请求体 JSON 必须是对象")
        return payload

    def _write_json(self, data: dict[str, Any], status: int = 200) -> None:
        """写回 JSON 响应。"""

        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_agent_in_background(agent_input: Any, allow_write: bool, agent_provider: str) -> None:
    """异步执行 Agent，避免阻塞飞书卡片回调响应。"""

    logger = get_logger("meetflow.feishu_event_server")
    try:
        settings = load_settings()
        llm_provider = DryRunLLMProvider() if agent_provider == "dry-run" else None
        agent = create_meetflow_agent(settings, llm_provider=llm_provider)
        agent.run(agent_input, allow_write=allow_write)
    except Exception as error:  # noqa: BLE001 - 后台任务失败需要落日志而不是吞掉。
        logger.exception("卡片动作触发的后台 Agent 执行失败")
        emit_structured_event(
            "card_action_failed",
            trace_id=getattr(agent_input, "trace_id", "-"),
            action=getattr(agent_input, "event_type", ""),
            status="agent_failed",
            error_type=error.__class__.__name__,
            error_message=safe_error_message(error),
        )


def main() -> int:
    """启动本地飞书事件回调服务。"""

    settings = load_settings()
    configure_logging(settings.logging)
    configure_structured_events(settings.observability)

    parser = argparse.ArgumentParser(description="MeetFlow 飞书事件回调服务。")
    parser.add_argument("--host", default=settings.feishu.event_server_host, help="监听地址。")
    parser.add_argument("--port", type=int, default=settings.feishu.event_server_port, help="监听端口。")
    parser.add_argument("--execute-agent", action="store_true", help="收到卡片动作后异步执行 Agent。")
    parser.add_argument("--allow-write", action="store_true", help="允许后台 Agent 执行写工具。")
    parser.add_argument(
        "--agent-provider",
        choices=["configured", "dry-run"],
        default="dry-run",
        help="后台 Agent 使用的模型 provider；默认 dry-run 方便联调。",
    )
    args = parser.parse_args()

    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(settings.feishu)
    configured_paths = getattr(settings.feishu, "event_http_paths", []) or []
    paths = {str(path) for path in configured_paths if path}
    paths.update({"/feishu/events", "/feishu/card/actions", "/feishu/card/callback"})
    state = FeishuEventServerState(
        dispatcher=FeishuCallbackDispatcher(
            settings=settings,
            storage=storage,
            feishu_client=client,
            policy=AgentPolicy(),
        ),
        paths=paths,
        execute_agent=args.execute_agent,
        allow_write=args.allow_write,
        agent_provider=args.agent_provider,
    )
    server = ThreadingHTTPServer((args.host, args.port), MeetFlowEventRequestHandler)
    server.state = state  # type: ignore[attr-defined]
    state.logger.info(
        "飞书事件回调服务已启动 host=%s port=%s execute_agent=%s allow_write=%s",
        args.host,
        args.port,
        args.execute_agent,
        args.allow_write,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        state.logger.info("飞书事件回调服务收到退出信号")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
