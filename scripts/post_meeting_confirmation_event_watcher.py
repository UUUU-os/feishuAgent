from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/post_meeting_confirmation_event_watcher.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuClient, create_feishu_tool_registry
from config import load_settings
from core import (
    AgentPolicy,
    ConfirmationCommand,
    MeetFlowStorage,
    configure_logging,
    get_logger,
    parse_confirmation_command,
)
from scripts.meetflow_agent_live_test import save_token_bundle
from scripts.post_meeting_confirmation_watcher import (
    build_reply_confirmation_command,
    handle_confirmation_command,
    send_watcher_reply,
)


def parse_args() -> argparse.Namespace:
    """解析 WebSocket 监听参数。"""

    parser = argparse.ArgumentParser(description="M4 待确认任务飞书 WebSocket 监听器。")
    parser.add_argument("--chat-id", default="", help="监听的群 chat_id；不传使用配置 default_chat_id。")
    parser.add_argument("--event-types", default="im.message.receive_v1", help="传给 lark-cli event +subscribe 的事件类型。")
    parser.add_argument("--fallback-polling", action="store_true", help="WebSocket 启动失败时回退到现有轮询 watcher。")
    parser.add_argument("--fallback-interval", type=float, default=5.0, help="回退轮询模式的间隔秒数。")
    parser.add_argument("--once", action="store_true", help="处理到第一条确认事件后退出。")
    parser.add_argument("--dry-run", action="store_true", help="只解析事件，不执行任务创建或回复发送。")
    return parser.parse_args()


def main() -> int:
    """启动飞书长连接并把 IM 消息事件转换成 M4 确认命令。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.post_meeting.confirmation_event_watcher")
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(settings.feishu, user_token_callback=lambda bundle: save_token_bundle(settings, bundle))
    registry = create_feishu_tool_registry(client, default_chat_id=settings.feishu.default_chat_id)
    policy = AgentPolicy()
    chat_id = args.chat_id or settings.feishu.default_chat_id
    if not chat_id:
        raise SystemExit("请传入 --chat-id，或在配置中设置 feishu.default_chat_id")

    command = [
        "lark-cli",
        "event",
        "+subscribe",
        "--event-types",
        args.event_types,
        "--compact",
        "--quiet",
    ]
    logger.info("M4 WebSocket 确认监听器启动 chat_id=%s event_types=%s", chat_id, args.event_types)
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as error:
        logger.error("启动 lark-cli WebSocket 监听失败：%s", error)
        return run_polling_fallback(args, chat_id) if args.fallback_polling else 2

    try:
        return consume_events(
            process=process,
            args=args,
            settings=settings,
            client=client,
            registry=registry,
            policy=policy,
            storage=storage,
            chat_id=chat_id,
            logger=logger,
        )
    finally:
        if process.poll() is None:
            process.terminate()


def consume_events(
    process: subprocess.Popen[str],
    args: argparse.Namespace,
    settings: Any,
    client: FeishuClient,
    registry: Any,
    policy: AgentPolicy,
    storage: MeetFlowStorage,
    chat_id: str,
    logger: Any,
) -> int:
    """消费 `lark-cli event +subscribe` 输出的 NDJSON 事件。"""

    handled = 0
    assert process.stdout is not None
    for line in process.stdout:
        raw_line = line.strip()
        if not raw_line:
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            logger.warning("忽略非 JSON 事件行：%s", raw_line[:120])
            continue
        command = build_command_from_event(settings=settings, event=event, chat_id=chat_id)
        if not command:
            continue
        logger.info("WebSocket 识别到 M4 确认口令 action=%s item_id=%s", command.action, command.item_id)
        if args.dry_run:
            print({"action": command.action, "item_id": command.item_id, "message_id": command.message_id})
        else:
            result_text = handle_confirmation_command(
                command=command,
                settings=settings,
                client=client,
                registry=registry,
                policy=policy,
                storage=storage,
                chat_id=chat_id,
            )
            send_watcher_reply(
                registry=registry,
                policy=policy,
                storage=storage,
                chat_id=chat_id,
                text=result_text,
                idempotency_key=f"post_meeting_confirmation_event_reply:{command.message_id or command.item_id}:{command.action}",
            )
        handled += 1
        if args.once:
            return 0

    exit_code = process.wait()
    if exit_code != 0:
        stderr = ""
        if process.stderr is not None:
            stderr = process.stderr.read().strip()
        logger.error("lark-cli WebSocket 监听退出 exit_code=%s error=%s", exit_code, stderr[:500])
        if args.fallback_polling:
            return run_polling_fallback(args, chat_id)
    return exit_code


def build_command_from_event(settings: Any, event: dict[str, Any], chat_id: str) -> ConfirmationCommand | None:
    """把 compact IM 事件转换成现有确认命令结构。"""

    event_type = str(event.get("type") or event.get("event_type") or "")
    event_chat_id = str(event.get("chat_id") or "")
    if event_type and event_type != "im.message.receive_v1":
        return None
    if event_chat_id and event_chat_id != chat_id:
        return None

    text = str(event.get("content") or "")
    message_id = str(event.get("message_id") or event.get("id") or "")
    sender_id = str(event.get("sender_id") or "")
    command = parse_confirmation_command(text)
    if not command:
        command = build_reply_confirmation_command(
            settings=settings,
            message=event_to_message(event),
            text=text,
        )
    if not command:
        return None
    command.message_id = message_id
    command.sender_id = sender_id or command.sender_id
    return command


def event_to_message(event: dict[str, Any]) -> dict[str, Any]:
    """把 WebSocket compact 事件伪装成轮询 watcher 已支持的消息结构。"""

    message: dict[str, Any] = {
        "message_id": str(event.get("message_id") or event.get("id") or ""),
        "chat_id": str(event.get("chat_id") or ""),
        "content": str(event.get("content") or ""),
        "sender": {"id": {"open_id": str(event.get("sender_id") or "")}},
    }
    for key in ["parent_id", "root_id", "thread_id", "upper_message_id"]:
        if event.get(key):
            message[key] = str(event.get(key))
    parent = event.get("parent")
    if isinstance(parent, dict):
        message["parent"] = parent
    return message


def run_polling_fallback(args: argparse.Namespace, chat_id: str) -> int:
    """回退到已有的群消息轮询 watcher，避免 WebSocket 不可用时中断确认链路。"""

    fallback = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "post_meeting_confirmation_watcher.py"),
        "--chat-id",
        chat_id,
        "--interval",
        str(args.fallback_interval),
    ]
    if args.once:
        fallback.append("--once")
    if args.dry_run:
        fallback.append("--dry-run")
    return subprocess.call(fallback)


if __name__ == "__main__":
    raise SystemExit(main())
