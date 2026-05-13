from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/post_meeting_card_callback_server.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuClient
from config import load_settings
from core import (
    AgentPolicy,
    MeetFlowStorage,
    configure_logging,
    get_logger,
    handle_post_meeting_card_callback,
)
from scripts.meetflow_agent_live_test import save_token_bundle


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="MeetFlow M4 飞书卡片回调服务。")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0。")
    parser.add_argument("--port", type=int, default=8787, help="监听端口，默认 8787。")
    parser.add_argument("--path", default="/feishu/card/callback", help="回调路径。")
    return parser.parse_args()


def main() -> int:
    """启动飞书卡片回调 HTTP 服务。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(settings.feishu, user_token_callback=lambda bundle: save_token_bundle(settings, bundle))
    policy = AgentPolicy()
    logger = get_logger("meetflow.post_meeting.card_callback")

    class Handler(BaseHTTPRequestHandler):
        """单文件 HTTP 回调处理器，便于本地联调和公网转发。"""

        def do_POST(self) -> None:  # noqa: N802 - http.server 约定方法名。
            if self.path.split("?")[0] != args.path:
                self._write_json({"error": "not_found"}, status=404)
                return
            try:
                payload = self._read_json()
                logger.info("收到飞书卡片回调 path=%s keys=%s", self.path, sorted(payload.keys()))
                if "challenge" in payload:
                    self._write_json({"challenge": payload.get("challenge", "")})
                    return
                result = handle_post_meeting_card_callback(
                    payload=payload,
                    settings=settings,
                    client=client,
                    storage=storage,
                    policy=policy,
                )
                self._write_json(result.to_feishu_response())
            except Exception as error:  # pragma: no cover - 真实 HTTP 服务兜底
                logger.exception("处理飞书卡片回调失败")
                self._write_json({"toast": {"type": "error", "content": f"MeetFlow 处理失败：{error}"}}, status=200)

        def do_GET(self) -> None:  # noqa: N802 - http.server 约定方法名。
            if self.path.split("?")[0] == "/healthz":
                self._write_json({"status": "ok"})
                return
            self._write_json({"error": "not_found"}, status=404)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - http.server 约定参数名。
            logger.info("HTTP " + format, *args)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            parsed = json.loads(body or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("回调 body 必须是 JSON object")
            return parsed

        def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    logger.info("M4 卡片回调服务已启动 url=http://%s:%s%s", args.host, args.port, args.path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("M4 卡片回调服务已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
