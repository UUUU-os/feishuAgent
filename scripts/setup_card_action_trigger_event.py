from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/setup_card_action_trigger_event.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    """解析卡片按钮事件配置辅助参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "辅助配置/验证飞书卡片按钮事件 card.action.trigger。"
            "注意：事件类型本身需要在飞书开放平台后台添加，不能仅靠 OAuth 登录完成。"
        )
    )
    parser.add_argument("--config-init", action="store_true", help="启动 lark-cli config init --new，重新配置应用。")
    parser.add_argument("--subscribe", action="store_true", help="验证后直接启动 card.action.trigger 长连接监听。")
    parser.add_argument("--event-types", default="card.action.trigger", help="要验证/监听的事件类型。")
    return parser.parse_args()


def main() -> int:
    """执行配置辅助流程。"""

    args = parse_args()
    print("飞书卡片按钮事件配置辅助")
    print("")
    print("你需要先在飞书开放平台后台完成：")
    print("1. 事件订阅方式选择“长连接 / WebSocket”。")
    print("2. 添加事件类型：card.action.trigger。")
    print("3. 开启机器人/应用的消息卡片或交互卡片能力。")
    print("4. 发布应用配置到当前测试企业。")
    print("")

    if args.config_init:
        code = run(["lark-cli", "config", "init", "--new"])
        if code != 0:
            return code

    print("验证 lark-cli 是否接受该事件类型：")
    code = run(
        [
            "lark-cli",
            "event",
            "+subscribe",
            "--dry-run",
            "--event-types",
            args.event_types,
            "--compact",
            "--quiet",
            "--as",
            "bot",
        ]
    )
    if code != 0:
        return code

    if not args.subscribe:
        print("")
        print("本地验证通过。后台配置完成后，可运行：")
        print(f"lark-cli event +subscribe --event-types {args.event_types} --compact --quiet --as bot")
        print("")
        print("或运行按钮探针：")
        print("python3 scripts/post_meeting_card_button_ws_probe.py --listen-seconds 180")
        return 0

    print("")
    print("启动长连接监听。点击测试卡片按钮后，观察终端是否出现 card.action.trigger 事件。")
    return run(
        [
            "lark-cli",
            "event",
            "+subscribe",
            "--event-types",
            args.event_types,
            "--compact",
            "--quiet",
            "--as",
            "bot",
        ]
    )


def run(command: list[str]) -> int:
    """运行 lark-cli 命令，不打印任何密钥内容。"""

    print(f"$ {' '.join(command)}")
    return subprocess.call(command, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
