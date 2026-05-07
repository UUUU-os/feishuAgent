from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# 允许直接通过 Python 3.10+ 启动脚本，推荐使用主 meetflow 环境创建隔离 venv。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENV = PROJECT_ROOT / ".venv-lark-oapi"
MIN_PYTHON = (3, 10)


def parse_args() -> argparse.Namespace:
    """解析飞书 SDK 隔离环境安装参数。"""

    parser = argparse.ArgumentParser(description="为飞书卡片回调长连接创建独立 lark-oapi 虚拟环境。")
    parser.add_argument("--venv", default=str(DEFAULT_VENV), help="虚拟环境目录。")
    parser.add_argument("--version", default="1.4.0", help="lark-oapi 版本。")
    parser.add_argument("--recreate", action="store_true", help="删除并重建虚拟环境，用于修复 Python 版本不一致。")
    return parser.parse_args()


def main() -> int:
    """创建 venv 并安装 lark-oapi，避免污染主 Python 环境的 protobuf。"""

    args = parse_args()
    if sys.version_info < MIN_PYTHON:
        print("当前 Python 版本过低，无法运行 MeetFlow SDK 回调服务。")
        print(f"当前版本：{sys.version.split()[0]}，最低要求：{MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
        print("请使用主 meetflow 环境重建，例如：")
        print("/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py --recreate")
        return 2

    venv = Path(args.venv).resolve()
    python_bin = venv / "bin" / "python"
    if args.recreate and venv.exists():
        if not can_recreate_venv(venv):
            print(f"拒绝删除看起来不像虚拟环境的目录：{venv}")
            print("请确认 --venv 参数，或手动处理该目录后再重试。")
            return 2
        shutil.rmtree(venv)
    elif python_bin.exists() and not venv_python_is_compatible(python_bin):
        print("现有 lark-oapi 虚拟环境 Python 版本过低，容易和 MeetFlow 主环境冲突。")
        print("请用主 meetflow 环境加 --recreate 重建：")
        print("/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py --recreate")
        return 2

    if not python_bin.exists():
        code = run([sys.executable, "-m", "venv", str(venv)])
        if code != 0:
            return code
    if not venv_python_is_compatible(python_bin):
        print("创建出的 lark-oapi 虚拟环境 Python 版本过低，请检查创建命令。")
        return 2

    code = run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip"])
    if code != 0:
        return code
    code = run([str(python_bin), "-m", "pip", "install", f"lark-oapi=={args.version}"])
    if code != 0:
        return code
    print("")
    print("独立环境已准备好。启动 MeetFlow 统一飞书 SDK 长连接：")
    print(f"{python_bin} scripts/feishu_event_sdk_server.py --dry-run --log-level debug")
    return 0


def venv_python_is_compatible(python_bin: Path) -> bool:
    """确认 SDK 隔离环境和 MeetFlow 代码的 Python 语法能力一致。"""

    code = (
        "import sys; "
        f"raise SystemExit(0 if sys.version_info >= {MIN_PYTHON!r} else 1)"
    )
    return subprocess.call([str(python_bin), "-c", code], cwd=PROJECT_ROOT) == 0


def can_recreate_venv(venv: Path) -> bool:
    """限制 --recreate 的删除范围，避免误删非虚拟环境目录。"""

    default_venv = DEFAULT_VENV.resolve()
    return venv == default_venv or (venv / "pyvenv.cfg").exists()


def run(command: list[str]) -> int:
    """执行安装命令。"""

    print(f"$ {' '.join(command)}")
    return subprocess.call(command, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
