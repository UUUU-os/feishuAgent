from __future__ import annotations

import argparse
import json
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/post_meeting_card_button_ws_probe.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuClient, create_feishu_tool_registry
from config import load_settings
from core import AgentPolicy, AgentToolCall, Event, MeetFlowStorage, WorkflowContext, configure_logging
from scripts.meetflow_agent_live_test import save_token_bundle


def parse_args() -> argparse.Namespace:
    """解析卡片按钮 WebSocket 探针参数。"""

    parser = argparse.ArgumentParser(
        description="发送一张带按钮的测试卡，并用飞书 WebSocket 长连接探测按钮点击是否会产生事件。"
    )
    parser.add_argument("--chat-id", default="", help="测试群 chat_id；不传使用 feishu.default_chat_id。")
    parser.add_argument(
        "--event-types",
        default="card.action.trigger,im.message.receive_v1",
        help="传给 lark-cli event +subscribe 的事件类型，默认同时监听卡片动作候选事件和消息事件。",
    )
    parser.add_argument("--listen-seconds", type=int, default=90, help="发送卡片后等待按钮事件的秒数。")
    parser.add_argument("--probe-id", default="", help="自定义探针 ID；不传自动生成。")
    parser.add_argument("--no-send-card", action="store_true", help="不发送测试卡，只启动监听。")
    parser.add_argument(
        "--force-subscribe",
        action="store_true",
        help="给 lark-cli event +subscribe 追加 --force，用于处理上次异常退出后单实例锁未释放的情况。",
    )
    return parser.parse_args()


def main() -> int:
    """运行卡片按钮长连接探针。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    chat_id = args.chat_id or settings.feishu.default_chat_id
    if not chat_id:
        raise SystemExit("请传入 --chat-id，或在配置中设置 feishu.default_chat_id")
    probe_id = args.probe_id or f"card_button_probe_{int(time.time())}"

    process = start_event_subscription(args.event_types, force=args.force_subscribe)
    try:
        time.sleep(1.0)
        if process.poll() is not None:
            print_subscription_exit(process)
            return 2
        if not args.no_send_card:
            send_probe_card(settings=settings, storage=storage, chat_id=chat_id, probe_id=probe_id)
        print("\n请在飞书测试群里点击刚发送卡片上的“确认创建”或“拒绝创建”按钮。")
        print(f"probe_id: {probe_id}")
        print(f"监听事件类型: {args.event_types}")
        matched = consume_events(process=process, probe_id=probe_id, timeout_seconds=args.listen_seconds)
        if matched:
            print("\n结论：WebSocket 收到了包含 probe_id 的按钮相关事件，可以继续把按钮事件接入 M4 确认链路。")
            return 0
        print("\n结论：本次没有从 WebSocket 收到包含 probe_id 的按钮事件。")
        print("请确认飞书开放平台是否已开启长连接，并添加 card.action.trigger 事件；如果仍无事件，卡片按钮仍需公网回调。")
        return 1
    finally:
        if process.poll() is None:
            process.terminate()


def start_event_subscription(event_types: str, force: bool = False) -> subprocess.Popen[str]:
    """启动 lark-cli WebSocket 订阅。"""

    command = [
        "lark-cli",
        "event",
        "+subscribe",
        "--event-types",
        event_types,
        "--compact",
        "--quiet",
        "--as",
        "bot",
    ]
    if force:
        command.append("--force")
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def send_probe_card(settings: Any, storage: MeetFlowStorage, chat_id: str, probe_id: str) -> None:
    """通过 ToolRegistry + AgentPolicy 发送按钮探针卡片。"""

    client = FeishuClient(settings.feishu, user_token_callback=lambda bundle: save_token_bundle(settings, bundle))
    registry = create_feishu_tool_registry(client, default_chat_id=settings.feishu.default_chat_id)
    policy = AgentPolicy()
    idempotency_key = f"post_meeting_card_button_probe:{probe_id}"
    context = WorkflowContext(
        workflow_type="post_meeting_followup",
        trace_id=probe_id,
        event=Event(
            event_id=idempotency_key,
            event_type="card.button.probe",
            event_time=str(int(time.time())),
            source="post_meeting_card_button_ws_probe",
            actor="",
            payload={"probe_id": probe_id},
            trace_id=probe_id,
        ),
        raw_context={"decision": {"idempotency_key": idempotency_key}},
    )
    tool = registry.get("im.send_card")
    tool_call = AgentToolCall(
        call_id=f"{probe_id}:send_card",
        tool_name=tool.llm_name,
        arguments={
            "title": "MeetFlow 卡片按钮 WebSocket 探针",
            "summary": "测试卡片按钮点击是否能通过 WebSocket 长连接收到事件",
            "card": build_probe_card(probe_id),
            "receive_id": chat_id,
            "receive_id_type": "chat_id",
            "identity": "tenant",
            "idempotency_key": idempotency_key,
        },
    )
    decision = policy.authorize_tool_call(context=context, tool=tool, tool_call=tool_call, allow_write=True, storage=storage)
    if not decision.is_allowed():
        raise RuntimeError(f"发送探针卡片被 AgentPolicy 拦截：{decision.reason}")
    tool_call.arguments = decision.patched_arguments
    result = registry.execute(tool_call)
    if result.status != "success":
        raise RuntimeError(result.error_message or result.content or "发送探针卡片失败")
    print("已发送按钮探针卡片到测试群。")


def build_probe_card(probe_id: str) -> dict[str, Any]:
    """构造带确认/拒绝按钮的飞书 interactive card。"""

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "MeetFlow 按钮事件探针"},
        },
        "elements": [
            {
                "tag": "markdown",
                "content": "\n".join(
                    [
                        "**用途**：测试卡片按钮点击是否能通过飞书 WebSocket 长连接收到。",
                        f"probe_id：`{probe_id}`",
                        "请点击下方任一按钮，然后观察本地终端输出。",
                    ]
                ),
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "确认创建"},
                        "type": "primary",
                        "value": {
                            "probe_id": probe_id,
                            "action": "confirm_create_task",
                            "item_id": "action_probe_button",
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "拒绝创建"},
                        "type": "danger",
                        "value": {
                            "probe_id": probe_id,
                            "action": "reject_create_task",
                            "item_id": "action_probe_button",
                        },
                    },
                ],
            },
        ],
    }


def consume_events(process: subprocess.Popen[str], probe_id: str, timeout_seconds: int) -> bool:
    """在限定时间内打印 WebSocket 事件，并判断是否命中探针 ID。"""

    selector = selectors.DefaultSelector()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.time() + max(timeout_seconds, 1)
    matched = False
    while time.time() < deadline:
        if process.poll() is not None:
            print_subscription_exit(process)
            break
        timeout = max(0.2, min(1.0, deadline - time.time()))
        for key, _ in selector.select(timeout):
            line = key.fileobj.readline()
            if not line:
                continue
            stream_name = key.data
            text = line.strip()
            if not text:
                continue
            print(f"[{stream_name}] {text}")
            if probe_id in text:
                matched = True
    return matched


def print_subscription_exit(process: subprocess.Popen[str]) -> None:
    """打印订阅进程提前退出信息。"""

    stderr = ""
    if process.stderr is not None:
        try:
            stderr = process.stderr.read().strip()
        except ValueError:
            stderr = ""
    print(f"lark-cli event +subscribe 已退出，exit_code={process.poll()} error={stderr[:1000]}")


if __name__ == "__main__":
    raise SystemExit(main())
