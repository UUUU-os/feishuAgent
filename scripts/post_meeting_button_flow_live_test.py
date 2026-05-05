from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/post_meeting_button_flow_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings


DEFAULT_MINUTE_TOKEN = "obcn7xk3bg1olx8lb811fq4i"
DEFAULT_VENV_PYTHON = PROJECT_ROOT / ".venv-lark-oapi" / "bin" / "python"
SEND_REQUIRED_MODULES = ("chromadb", "sentence_transformers")
CALLBACK_REQUIRED_MODULES = ("lark_oapi",)


def parse_args() -> argparse.Namespace:
    """解析按钮回调真实环境测试脚本参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "M4 按钮式待确认任务真实环境测试入口。"
            "支持两种子命令：callback=启动 card.action.trigger 长连接回调；"
            "send=读取真实妙记并向测试群发送待确认按钮卡。"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    callback_parser = subparsers.add_parser(
        "callback",
        help="启动飞书 SDK 长连接卡片回调服务，承接确认创建 / 修改信息 / 拒绝创建按钮。",
    )
    callback_parser.add_argument(
        "--python-bin",
        default="",
        help="回调链路的 python；不传时自动寻找包含 lark_oapi 的解释器。",
    )
    callback_parser.add_argument("--log-level", default="info", help="SDK 日志级别：debug/info/warn/error。")
    callback_parser.add_argument("--dry-run", action="store_true", help="只打印按钮回调，不真正创建任务。")

    send_parser = subparsers.add_parser(
        "send",
        help="读取真实妙记并向测试群发送会后总结卡 + 待确认按钮卡。",
    )
    send_parser.add_argument("--minute", default=DEFAULT_MINUTE_TOKEN, help="飞书妙记 URL 或 minute token。")
    send_parser.add_argument("--python-bin", default="", help="发送链路的 python；不传时自动寻找包含 chromadb 和 sentence_transformers 的解释器。")
    send_parser.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取妙记的身份。")
    send_parser.add_argument("--chat-id", default="", help="测试群 chat_id；不传时使用 feishu.default_chat_id。")
    send_parser.add_argument("--content-limit", type=int, default=300, help="报告中保留的妙记正文预览长度。")
    send_parser.add_argument("--report-dir", default="storage/reports/m4/button_flow", help="Markdown 报告目录。")
    send_parser.add_argument("--read-only", action="store_true", help="只读验证，不发卡。")
    send_parser.add_argument("--show-card-json", action="store_true", help="打印完整 card JSON。")

    return parser.parse_args()


def main() -> int:
    """执行按钮回调真实环境测试子命令。"""

    args = parse_args()
    settings = load_settings()
    if args.command == "callback":
        return run_callback(args)
    if args.command == "send":
        return run_send(args, settings)
    raise SystemExit(f"未知子命令：{args.command}")


def run_callback(args: argparse.Namespace) -> int:
    """启动按钮回调长连接监听。"""

    python_bin = resolve_python_bin(
        preferred=args.python_bin,
        purpose="callback",
        required_modules=CALLBACK_REQUIRED_MODULES,
        preferred_candidates=[DEFAULT_VENV_PYTHON],
    )

    command = [
        str(python_bin),
        str(PROJECT_ROOT / "scripts" / "post_meeting_card_callback_ws.py"),
        "--log-level",
        args.log_level,
    ]
    if args.dry_run:
        command.append("--dry-run")

    print("启动 M4 按钮回调长连接：")
    print(" ".join(command))
    print("")
    print("保持这个终端运行。群里点击待确认卡片按钮后，这里会收到 card.action.trigger。")
    try:
        return subprocess.call(command, cwd=PROJECT_ROOT)
    except KeyboardInterrupt:
        print("\n按钮回调启动已中断。")
        return 130


def run_send(args: argparse.Namespace, settings) -> int:  # noqa: ANN001 - settings 为项目配置对象
    """发送真实待确认按钮卡。"""

    chat_id = args.chat_id or settings.feishu.default_chat_id
    if not chat_id and not args.read_only:
        raise SystemExit("缺少测试群 chat_id。请传入 --chat-id，或在 settings.local.json 设置 feishu.default_chat_id。")

    python_bin = resolve_python_bin(
        preferred=args.python_bin,
        purpose="send",
        required_modules=SEND_REQUIRED_MODULES,
    )

    command = [
        str(python_bin),
        str(PROJECT_ROOT / "scripts" / "post_meeting_live_test.py"),
        "--minute",
        args.minute,
        "--identity",
        args.identity,
        "--content-limit",
        str(args.content_limit),
        "--report-dir",
        args.report_dir,
    ]
    if args.read_only:
        command.append("--read-only")
    else:
        command.extend(["--allow-write", "--send-card"])
        if chat_id:
            command.extend(["--chat-id", chat_id])
    if args.show_card_json:
        command.append("--show-card-json")

    print("发送 M4 会后总结卡 + 待确认按钮卡：")
    print(" ".join(command))
    print("")
    if not args.read_only:
        print("发送成功后，测试群会收到待确认卡片；点击“确认创建 / 修改信息 / 拒绝创建”即可走真实按钮回调。")
    return subprocess.call(command, cwd=PROJECT_ROOT)


def resolve_python_bin(
    *,
    preferred: str,
    purpose: str,
    required_modules: tuple[str, ...],
    preferred_candidates: list[Path] | None = None,
) -> Path:
    """为 send/callback 自动选择具备所需依赖的解释器。

    真实联调阶段经常同时激活 Conda 和 venv；此时裸 `python3` 很容易指到错误
    环境。这里会优先校验用户显式传入的解释器，再按常见路径自动探测。
    """

    candidates: list[Path] = []
    if preferred_candidates:
        candidates.extend(preferred_candidates)
    if preferred:
        candidates.insert(0, normalize_python_path(preferred))
    candidates.extend(discover_python_candidates())

    checked: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_python_path(str(candidate))
        key = str(normalized)
        if key in seen or not normalized.exists():
            continue
        seen.add(key)
        ok, detail = probe_python_modules(normalized, required_modules)
        checked.append(f"{normalized} -> {detail}")
        if ok:
            return normalized
    raise SystemExit(
        f"找不到可用于 {purpose} 的 Python 解释器，需要模块：{', '.join(required_modules)}。\n"
        + "\n".join(checked[:12])
    )


def normalize_python_path(value: str) -> Path:
    """把命令行或自动发现的解释器路径规范化成绝对路径。"""

    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).absolute()


def discover_python_candidates() -> list[Path]:
    """收集本机常见 Python 路径候选。"""

    candidates: list[Path] = [
        DEFAULT_VENV_PYTHON,
        Path(sys.executable),
        Path(sys.executable).with_name("python3"),
        Path(sys.executable).with_name("python"),
    ]
    for env_name in ("CONDA_PREFIX", "VIRTUAL_ENV"):
        env_root = os.getenv(env_name, "").strip()
        if not env_root:
            continue
        candidates.append(Path(env_root) / "bin" / "python3")
        candidates.append(Path(env_root) / "bin" / "python")
    home = Path.home()
    conda_env_root = home / "miniconda3" / "envs"
    if conda_env_root.exists():
        for env_dir in sorted(conda_env_root.iterdir()):
            if not env_dir.is_dir():
                continue
            candidates.append(env_dir / "bin" / "python3")
            candidates.append(env_dir / "bin" / "python")
    candidates.extend([Path("/usr/bin/python3"), Path("/bin/python3")])
    return candidates


def probe_python_modules(python_bin: Path, modules: tuple[str, ...]) -> tuple[bool, str]:
    """检查解释器能否导入所需模块。"""

    script = (
        "import importlib.util, sys\n"
        f"modules = {modules!r}\n"
        "missing = [name for name in modules if importlib.util.find_spec(name) is None]\n"
        "if missing:\n"
        "    print('missing:' + ','.join(missing))\n"
        "    raise SystemExit(3)\n"
        "print('ok')\n"
    )
    try:
        completed = subprocess.run(
            [str(python_bin), "-c", script],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=12,
            check=False,
        )
    except Exception as error:
        return False, f"probe_failed:{type(error).__name__}:{error}"
    output = (completed.stdout or "").strip().replace("\n", " | ")
    if completed.returncode == 0:
        return True, output or "ok"
    return False, output or f"exit_code={completed.returncode}"


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nM4 按钮式测试入口已停止。")
        raise SystemExit(130)
