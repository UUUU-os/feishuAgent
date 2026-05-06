from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/meetflow_up.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings


DEFAULT_EVENT_TYPES = (
    "calendar.calendar.event.changed_v4,"
    "drive.file.edit_v1,"
    "drive.file.title_updated_v1,"
    "drive.file.bitable_record_changed_v1,"
    "drive.file.bitable_field_changed_v1"
)


def parse_args() -> argparse.Namespace:
    """解析 MeetFlow 一键启动参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "MeetFlow 一键运行入口：启动长连接事件、daemon、worker、M4 按钮回调，"
            "让 M3/M4/M5/RAG 在后台闭环运行。"
        )
    )
    parser.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取日历/文档/任务使用的身份。")
    parser.add_argument("--calendar-id", default="primary", help="日历 ID，默认 primary。")
    parser.add_argument("--chat-id", default="", help="测试群 chat_id；不传使用 feishu.default_chat_id。")
    parser.add_argument("--doc", action="append", default=[], help="启动前加入并订阅的飞书文档 URL，可重复传。")
    parser.add_argument("--event-types", default=DEFAULT_EVENT_TYPES, help="lark-cli 长连接监听事件类型。")
    parser.add_argument("--m3-minutes-before", type=int, default=30, help="会议开始前多少分钟触发 M3。")
    parser.add_argument("--m4-delay-minutes", type=int, default=5, help="日程结束后至少等待多少分钟再查妙记。")
    parser.add_argument("--lookahead-hours", type=int, default=24, help="向后扫描日程小时数。")
    parser.add_argument("--m4-lookback-hours", type=int, default=12, help="向前扫描已结束会议小时数。")
    parser.add_argument("--poll-seconds", type=int, default=60, help="daemon 兜底扫描间隔。")
    parser.add_argument("--worker-poll-seconds", type=float, default=2.0, help="worker 空闲轮询间隔。")
    parser.add_argument("--risk-scan-seconds", type=int, default=900, help="M5 风险巡检入队间隔，默认 15 分钟。")
    parser.add_argument("--force-subscribe", action="store_true", help="给 lark-cli event +subscribe 追加 --force。")
    parser.add_argument("--sync-lark-cli", action="store_true", help="启动前同步 lark-cli app_id/app_secret。")
    parser.add_argument("--allow-write", action="store_true", help="允许真实发 M3/M4/M5 卡片。比赛演示时应开启。")
    parser.add_argument("--dry-run", action="store_true", help="只预览 daemon 发现机会，不真实入队/发卡。")
    parser.add_argument("--no-callback", action="store_true", help="不启动 M4 卡片按钮回调。")
    parser.add_argument("--no-worker", action="store_true", help="不启动 worker，只启动事件/daemon。")
    parser.add_argument("--no-m3", action="store_true", help="关闭 M3 自动触发。")
    parser.add_argument("--no-m4", action="store_true", help="关闭 M4 自动触发。")
    parser.add_argument("--no-m5", action="store_true", help="关闭 M5 风险巡检定时入队。")
    parser.add_argument("--no-rag", action="store_true", help="关闭 RAG 文档事件刷新。")
    parser.add_argument("--lark-cli-bin", default="", help="lark-cli 可执行文件路径；不传使用 PATH。")
    parser.add_argument("--python-bin", default="", help="MeetFlow 主 Python；不传使用当前解释器。")
    return parser.parse_args()


def main() -> int:
    """启动并监督 MeetFlow 后台进程。"""

    args = parse_args()
    settings = load_settings()
    python_bin = args.python_bin or sys.executable
    chat_id = args.chat_id or settings.feishu.default_chat_id

    if args.allow_write and not chat_id:
        raise SystemExit("开启 --allow-write 时需要 --chat-id 或 config/settings.local.json 的 feishu.default_chat_id。")
    if args.sync_lark_cli:
        run_checked([python_bin, str(PROJECT_ROOT / "scripts" / "sync_lark_cli_config.py"), "--yes"])
    if args.doc and not args.no_rag:
        bootstrap_rag_docs(args=args, python_bin=python_bin)

    processes: list[ManagedProcess] = []
    risk_next_at = 0.0
    stopping = False

    def request_stop(signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True
        print(f"\n收到信号 {signum}，正在停止 MeetFlow 后台服务...")

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    print_banner(args=args, chat_id=chat_id)
    lark_process = start_lark_cli(args)
    processes.append(ManagedProcess(name="lark-event", process=lark_process))
    daemon_process = start_daemon(args=args, python_bin=python_bin, lark_process=lark_process, chat_id=chat_id)
    processes.append(ManagedProcess(name="meetflow-daemon", process=daemon_process))

    if not args.no_worker:
        processes.append(
            ManagedProcess(
                name="meetflow-worker",
                process=start_worker(args=args, python_bin=python_bin),
            )
        )
    if not args.no_callback:
        processes.append(
            ManagedProcess(
                name="m4-callback",
                process=start_callback(python_bin=python_bin),
            )
        )

    try:
        while not stopping:
            for managed in processes:
                returncode = managed.process.poll()
                if returncode is not None:
                    print(f"[meetflow-up] 进程退出 name={managed.name} returncode={returncode}")
                    stopping = True
                    break
            if not args.no_m5 and not args.dry_run and time.time() >= risk_next_at:
                enqueue_risk_scan(args=args, python_bin=python_bin, chat_id=chat_id)
                risk_next_at = time.time() + max(60, int(args.risk_scan_seconds or 900))
            time.sleep(1.0)
    finally:
        stop_processes(processes)
    return 0


def print_banner(*, args: argparse.Namespace, chat_id: str) -> None:
    """打印一键启动摘要，方便比赛演示前确认运行模式。"""

    print("\n=== MeetFlow 一键运行 ===")
    print(f"- M3: {'关闭' if args.no_m3 else '开启'}")
    print(f"- M4: {'关闭' if args.no_m4 else '开启'}")
    print(f"- M5: {'关闭' if args.no_m5 else '开启'}")
    print(f"- RAG: {'关闭' if args.no_rag else '开启'}")
    if args.doc and not args.no_rag:
        print(f"- 启动前索引/订阅文档: {len(args.doc)} 篇")
    print(f"- 写操作: {'真实执行' if args.allow_write else '只入队/预览，不真实发卡'}")
    print(f"- chat_id: {chat_id or '(未配置)'}")
    print("- 停止方式: Ctrl+C")
    print("")


def start_lark_cli(args: argparse.Namespace) -> subprocess.Popen[str]:
    """启动 lark-cli 长连接，输出 NDJSON 给 daemon。"""

    executable = args.lark_cli_bin or "lark-cli"
    command = [
        executable,
        "event",
        "+subscribe",
        "--event-types",
        args.event_types,
        "--compact",
        "--quiet",
        "--as",
        "bot",
    ]
    if args.force_subscribe:
        command.append("--force")
    print("[meetflow-up] 启动 lark-event:", " ".join(command))
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        bufsize=1,
    )


def start_daemon(
    *,
    args: argparse.Namespace,
    python_bin: str,
    lark_process: subprocess.Popen[str],
    chat_id: str,
) -> subprocess.Popen[str]:
    """启动 daemon，并把 lark-cli 事件流接入 stdin。"""

    command = [
        python_bin,
        str(PROJECT_ROOT / "scripts" / "meetflow_daemon.py"),
        "--event-stdin",
        "--enqueue",
        "--identity",
        args.identity,
        "--calendar-id",
        args.calendar_id,
        "--poll-seconds",
        str(args.poll_seconds),
        "--lookahead-hours",
        str(args.lookahead_hours),
        "--m3-minutes-before",
        str(args.m3_minutes_before),
        "--m4-lookback-hours",
        str(args.m4_lookback_hours),
        "--m4-delay-minutes",
        str(args.m4_delay_minutes),
    ]
    if chat_id:
        command.extend(["--chat-id", chat_id])
    if not args.no_m3:
        command.append("--enable-m3")
    if not args.no_m4:
        command.append("--enable-m4")
    if not args.no_rag:
        command.append("--enable-rag")
    if args.dry_run or not args.allow_write:
        command.append("--dry-run")
    print("[meetflow-up] 启动 daemon:", " ".join(command))
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdin=lark_process.stdout,
        text=True,
    )


def start_worker(*, args: argparse.Namespace, python_bin: str) -> subprocess.Popen[str]:
    """启动后台 worker，消费 M3/M4/M5/RAG 队列。"""

    command = [
        python_bin,
        str(PROJECT_ROOT / "scripts" / "meetflow_worker.py"),
        "--queues",
        "workflow,risk_scan,rag_refresh",
        "--poll-seconds",
        str(args.worker_poll_seconds),
    ]
    print("[meetflow-up] 启动 worker:", " ".join(command))
    return subprocess.Popen(command, cwd=PROJECT_ROOT, text=True)


def start_callback(*, python_bin: str) -> subprocess.Popen[str]:
    """启动 M4 卡片按钮回调长连接。"""

    command = [
        python_bin,
        str(PROJECT_ROOT / "scripts" / "card_send_live.py"),
        "m4-callback",
        "--log-level",
        "info",
    ]
    print("[meetflow-up] 启动 M4 回调:", " ".join(command))
    return subprocess.Popen(command, cwd=PROJECT_ROOT, text=True)


def enqueue_risk_scan(*, args: argparse.Namespace, python_bin: str, chat_id: str) -> None:
    """定期把 M5 风险巡检写入队列，由 worker 执行。"""

    command = [
        python_bin,
        str(PROJECT_ROOT / "scripts" / "risk_scan_demo.py"),
        "--backend",
        "feishu",
        "--identity",
        args.identity,
        "--send-identity",
        "tenant",
        "--show-card",
        "--enqueue",
    ]
    if chat_id:
        command.extend(["--chat-id", chat_id])
    if args.allow_write:
        command.append("--allow-write")
    print("[meetflow-up] 入队 M5 风险巡检:", " ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT, text=True, check=False)
    if completed.returncode != 0:
        print(f"[meetflow-up] M5 入队失败 returncode={completed.returncode}")


def bootstrap_rag_docs(*, args: argparse.Namespace, python_bin: str) -> None:
    """启动前把比赛演示文档加入 RAG，并调用云文档订阅接口。

    一键演示时，用户希望只启动一个入口后就去飞书里操作。因此这里复用
    `live_environment_watch.py --doc` 的真实文档索引和订阅能力，短时间运行后
    退出，再进入正式 daemon/worker 常驻流程。
    """

    command = [
        python_bin,
        str(PROJECT_ROOT / "scripts" / "live_environment_watch.py"),
        "--enable-rag",
        "--identity",
        args.identity,
        "--duration-seconds",
        "5",
        "--poll-seconds",
        "5",
        "--skip-calendar-subscribe",
    ]
    if args.force_subscribe:
        command.append("--force-subscribe")
    for doc in args.doc:
        command.extend(["--doc", doc])
    print("[meetflow-up] 启动前索引/订阅 RAG 文档:", " ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"启动前 RAG 文档索引/订阅失败 returncode={completed.returncode}")


def run_checked(command: list[str]) -> None:
    """运行启动前检查命令，失败时停止总启动。"""

    print("[meetflow-up] 运行检查:", " ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"启动前检查失败 returncode={completed.returncode}")


class ManagedProcess:
    """记录一个由总启动器管理的子进程。"""

    def __init__(self, name: str, process: subprocess.Popen[str]) -> None:
        self.name = name
        self.process = process


def stop_processes(processes: list[ManagedProcess]) -> None:
    """按启动反序停止所有子进程。"""

    for managed in reversed(processes):
        if managed.process.poll() is not None:
            continue
        print(f"[meetflow-up] 停止 {managed.name} pid={managed.process.pid}")
        managed.process.terminate()
    deadline = time.time() + 8
    for managed in reversed(processes):
        if managed.process.poll() is not None:
            continue
        timeout = max(0.1, deadline - time.time())
        try:
            managed.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"[meetflow-up] 强制结束 {managed.name} pid={managed.process.pid}")
            managed.process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
