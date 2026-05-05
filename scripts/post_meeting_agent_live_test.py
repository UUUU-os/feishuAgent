from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/post_meeting_agent_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core.confirmation_commands import pending_actions_path


DEFAULT_MINUTE_TOKEN = "obcn7xk3bg1olx8lb811fq4i"


def parse_args() -> argparse.Namespace:
    """解析真实环境 M4 Agent 验收参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "真实环境测试 M4 Agent 化链路：minute.ready -> Agent Loop -> 发会后总结卡和待确认任务卡 -> "
            "保存待确认任务；不会自动创建任务。"
        )
    )
    parser.add_argument("--minute-token", default=DEFAULT_MINUTE_TOKEN, help="飞书妙记 token。")
    parser.add_argument("--llm-provider", default="scripted_debug", help="默认 scripted_debug；也可传 deepseek/settings。")
    parser.add_argument("--max-iterations", type=int, default=6, help="Agent Loop 最大轮数。")
    parser.add_argument("--enable-idempotency", action="store_true", help="启用写操作幂等去重。")
    parser.add_argument("--skip-agent", action="store_true", help="跳过发卡阶段，只打印待确认 registry 和 watcher 命令。")
    parser.add_argument("--listen-websocket", action="store_true", help="发卡后启动 WebSocket 确认监听器。")
    parser.add_argument("--watch-once", action="store_true", help="WebSocket 监听器处理到第一条确认事件后退出。")
    parser.add_argument("--watcher-dry-run", action="store_true", help="WebSocket 监听器只解析确认事件，不执行创建/回复。")
    parser.add_argument("--fallback-polling", action="store_true", help="WebSocket 不可用时回退到现有轮询 watcher。")
    return parser.parse_args()


def main() -> int:
    """执行真实环境 M4 Agent 冒烟测试。"""

    args = parse_args()
    settings = load_settings()
    chat_id = settings.feishu.default_chat_id
    if not chat_id:
        raise SystemExit("缺少 feishu.default_chat_id。请先在本地配置测试群，避免误发到生产群。")
    print("M4 Agent 真实环境测试")
    print(f"- minute_token: {args.minute_token}")
    print(f"- default_chat_id: {chat_id}")
    print("- 任务创建策略: 不自动创建；只有确认入口写入 human_confirmation 后才允许创建。")

    exit_code = 0
    if not args.skip_agent:
        exit_code = run_agent_stage(args)
        if exit_code != 0:
            return exit_code

    print_pending_registry(settings)
    print_next_steps(args)

    if args.listen_websocket:
        return run_websocket_watcher(args=args, chat_id=chat_id)
    return 0


def run_agent_stage(args: argparse.Namespace) -> int:
    """运行真实飞书 backend 的 M4 Agent 主链路。"""

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "agent_demo.py"),
        "--event-type",
        "minute.ready",
        "--backend",
        "feishu",
        "--llm-provider",
        args.llm_provider,
        "--minute-token",
        args.minute_token,
        "--max-iterations",
        str(args.max_iterations),
        "--allow-write",
    ]
    if args.enable_idempotency:
        command.append("--enable-idempotency")
    print("\n[1/2] 运行 M4 Agent 主链路，真实读取妙记并向测试群发送会后总结卡和待确认任务卡...")
    return subprocess.call(command, cwd=PROJECT_ROOT)


def print_pending_registry(settings: Any) -> None:
    """读取待确认任务 registry，确认待审核数据已经落盘。"""

    path = pending_actions_path(settings)
    print("\n[2/2] 待确认任务 registry")
    print(f"- path: {path}")
    if not path.exists():
        print("- status: missing")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"- status: invalid_json ({error})")
        return
    records = data.get("records") if isinstance(data, dict) else {}
    if not isinstance(records, dict):
        records = {}
    pending = [item_id for item_id, record in records.items() if isinstance(record, dict) and record.get("status") in {"pending", "", None}]
    print(f"- total_records: {len(records)}")
    print(f"- pending_records: {len(pending)}")
    if pending:
        print(f"- sample_item_ids: {', '.join(pending[:5])}")


def print_next_steps(args: argparse.Namespace) -> None:
    """打印用户下一步可直接执行的确认监听命令。"""

    watcher_command = [
        "python3",
        "scripts/post_meeting_confirmation_event_watcher.py",
        "--fallback-polling",
    ]
    if args.watch_once:
        watcher_command.append("--once")
    print("\n下一步优先直接点击待确认卡片里的“确认创建 / 修改信息 / 拒绝创建”按钮。")
    print("若需要回退到旧的消息确认模式，再启动下面的 watcher。")
    print("WebSocket 监听命令：")
    print(" ".join(watcher_command))


def run_websocket_watcher(args: argparse.Namespace, chat_id: str) -> int:
    """启动 WebSocket 确认监听器，必要时回退到轮询模式。"""

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "post_meeting_confirmation_event_watcher.py"),
        "--chat-id",
        chat_id,
    ]
    if args.watch_once:
        command.append("--once")
    if args.watcher_dry_run:
        command.append("--dry-run")
    if args.fallback_polling:
        command.append("--fallback-polling")
    print("\n启动 WebSocket 确认监听器。当前它主要作为旧消息确认模式的兜底入口。")
    return subprocess.call(command, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
