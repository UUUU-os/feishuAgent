from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/sync_lark_cli_config.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings


def parse_args() -> argparse.Namespace:
    """解析 lark-cli 配置同步参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "把 lark-cli 的长连接应用配置同步为 MeetFlow 当前 feishu.app_id。"
            "用于确保 API 订阅事件和 WebSocket 接收事件使用同一个飞书应用。"
        )
    )
    parser.add_argument("--lark-cli-bin", default="", help="lark-cli 可执行文件路径；不传则使用 PATH。")
    parser.add_argument("--yes", action="store_true", help="确认写入本机 lark-cli 配置。未传时只打印将要做什么。")
    return parser.parse_args()


def main() -> int:
    """执行 lark-cli 配置同步。"""

    args = parse_args()
    settings = load_settings()
    app_id = settings.feishu.app_id
    app_secret = settings.feishu.app_secret
    if not app_id or not app_secret:
        raise SystemExit("缺少 config/settings.local.json 中的 feishu.app_id 或 feishu.app_secret。")
    executable = resolve_lark_cli_bin(args.lark_cli_bin)
    current_app_id = read_current_lark_cli_app_id(executable)
    print(f"当前 lark-cli app_id: {current_app_id or '(未配置/无法解析)'}")
    print(f"目标 MeetFlow app_id: {app_id}")
    if current_app_id == app_id:
        print("lark-cli 已经使用 MeetFlow 当前应用，无需同步。")
        return 0
    if not args.yes:
        print("")
        print("未写入配置。确认要同步时运行：")
        print("python3 scripts/sync_lark_cli_config.py --yes")
        return 2

    command = [
        executable,
        "config",
        "init",
        "--app-id",
        app_id,
        "--app-secret-stdin",
        "--brand",
        settings.feishu.brand or "feishu",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        input=app_secret + "\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    output = (completed.stdout or "").replace(app_secret, "****")
    if output.strip():
        print(output)
    if completed.returncode != 0:
        raise SystemExit(f"lark-cli 配置同步失败 returncode={completed.returncode}")

    synced_app_id = read_current_lark_cli_app_id(executable)
    if synced_app_id != app_id:
        raise SystemExit(f"同步后 app_id 仍不一致：current={synced_app_id} target={app_id}")
    print(f"同步完成：lark-cli app_id={synced_app_id}")
    return 0


def resolve_lark_cli_bin(preferred: str) -> str:
    """解析 lark-cli 可执行文件路径。"""

    if preferred:
        path = Path(preferred).expanduser()
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).absolute()
        return str(path)
    return shutil.which("lark-cli") or "lark-cli"


def read_current_lark_cli_app_id(executable: str) -> str:
    """读取当前 lark-cli 配置中的 appId。"""

    completed = subprocess.run(
        [executable, "config", "show"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=15,
        check=False,
    )
    output = completed.stdout or ""
    try:
        start = output.index("{")
        data, _ = json.JSONDecoder().raw_decode(output[start:])
        return str(data.get("appId") or "").strip() if isinstance(data, dict) else ""
    except (ValueError, json.JSONDecodeError):
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
