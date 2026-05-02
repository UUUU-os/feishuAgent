from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/setup_lark_oapi_venv.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENV = PROJECT_ROOT / ".venv-lark-oapi"


def parse_args() -> argparse.Namespace:
    """解析飞书 SDK 隔离环境安装参数。"""

    parser = argparse.ArgumentParser(description="为飞书卡片回调长连接创建独立 lark-oapi 虚拟环境。")
    parser.add_argument("--venv", default=str(DEFAULT_VENV), help="虚拟环境目录。")
    parser.add_argument("--version", default="1.4.0", help="lark-oapi 版本。")
    return parser.parse_args()


def main() -> int:
    """创建 venv 并安装 lark-oapi，避免污染主 Python 环境的 protobuf。"""

    args = parse_args()
    venv = Path(args.venv).resolve()
    python_bin = venv / "bin" / "python"
    if not python_bin.exists():
        code = run([sys.executable, "-m", "venv", str(venv)])
        if code != 0:
            return code
    code = run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip"])
    if code != 0:
        return code
    code = run([str(python_bin), "-m", "pip", "install", f"lark-oapi=={args.version}"])
    if code != 0:
        return code
    print("")
    print("独立环境已准备好。启动卡片按钮长连接：")
    print(f"{python_bin} scripts/post_meeting_card_callback_ws.py --dry-run --log-level debug")
    return 0


def run(command: list[str]) -> int:
    """执行安装命令。"""

    print(f"$ {' '.join(command)}")
    return subprocess.call(command, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
