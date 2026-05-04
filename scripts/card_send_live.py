from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/card_send_live.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings


def parse_args() -> argparse.Namespace:
    """解析真实发卡统一入口参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "MeetFlow M3/M4 真实发卡统一入口。"
            "会调用现有真实联调脚本，显式带上 allow-write/send-card 安全开关。"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    m3 = subparsers.add_parser("m3", help="发送 M3 会前知识卡片。")
    m3.add_argument("--identity", default="user", choices=["tenant", "user"], help="读取日历/文档的飞书身份。")
    m3.add_argument("--calendar-id", default="primary", help="日历 ID，默认 primary。")
    m3.add_argument("--event-id", default="", help="指定日程 event_id。")
    m3.add_argument("--event-title", default="", help="按标题包含匹配日程。")
    m3.add_argument("--date", default="", help="按本地日期查询整天日程：today / tomorrow / YYYY-MM-DD。")
    m3.add_argument("--lookahead-hours", type=int, default=24, help="未指定 event 时向后查找多少小时。")
    m3.add_argument("--project-id", default="meetflow", help="项目 ID。")
    m3.add_argument("--doc", action="append", default=[], help="纳入索引的飞书文档 URL/token，可传多次。")
    m3.add_argument("--minute", action="append", default=[], help="纳入索引的飞书妙记 URL/token，可传多次。")
    m3.add_argument(
        "--llm-provider",
        default="scripted_debug",
        help="默认 scripted_debug，避免真实 LLM 接收飞书内容；确认风险后可传 deepseek 等 provider。",
    )
    m3.add_argument("--max-iterations", type=int, default=5, help="Agent Loop 最大轮数。")
    m3.add_argument("--idempotency-suffix", default="", help="重复真实发送同一会议时建议传唯一后缀。")
    m3.add_argument("--force-index", action="store_true", help="强制重建补充资源索引。")
    m3.add_argument("--write-report", action="store_true", help="写入 M3 运行报告。")
    m3.add_argument("--report-dir", default="storage/reports/m3", help="M3 报告目录。")
    m3.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，不真正发送。")

    m4 = subparsers.add_parser("m4", help="发送 M4 会后总结卡和待确认卡。")
    m4.add_argument("--minute", required=True, help="飞书妙记 URL 或 minute token。")
    m4.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取妙记的飞书身份。")
    m4.add_argument("--chat-id", default="", help="测试群 chat_id；不传则使用配置 default_chat_id。")
    m4.add_argument("--receive-id-type", default="chat_id", help="接收者 ID 类型，默认 chat_id。")
    m4.add_argument("--content-limit", type=int, default=300, help="报告中保留的妙记正文预览长度。")
    m4.add_argument("--report-dir", default="storage/reports/m4/button_flow", help="M4 报告目录。")
    m4.add_argument("--related-top-n", type=int, default=5, help="会后总结卡展示的相关背景资料数量。")
    m4.add_argument("--skip-related-knowledge", action="store_true", help="跳过 M3 RAG 背景资料召回。")
    m4.add_argument("--show-card-json", action="store_true", help="终端打印完整卡片 JSON。")
    m4.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，不真正发送。")

    callback = subparsers.add_parser("m4-callback", help="启动 M4 待确认按钮回调长连接。")
    callback.add_argument("--log-level", default="info", help="SDK 日志级别：debug/info/warn/error。")
    callback.add_argument("--dry-run", action="store_true", help="回调只打印，不真正创建任务。")
    callback.add_argument("--print-only", action="store_true", help="只打印将执行的命令，不启动长连接。")

    return parser.parse_args()


def main() -> int:
    """执行真实发卡统一入口。"""

    args = parse_args()
    settings = load_settings()
    if args.command == "m3":
        return run_m3(args)
    if args.command == "m4":
        return run_m4(args, settings)
    if args.command == "m4-callback":
        return run_m4_callback(args)
    raise SystemExit(f"未知子命令：{args.command}")


def run_m3(args: argparse.Namespace) -> int:
    """发送 M3 会前知识卡片。"""

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "pre_meeting_live_test.py"),
        "--identity",
        args.identity,
        "--calendar-id",
        args.calendar_id,
        "--lookahead-hours",
        str(args.lookahead_hours),
        "--project-id",
        args.project_id,
        "--llm-provider",
        args.llm_provider,
        "--max-iterations",
        str(args.max_iterations),
        "--allow-write",
        "--enable-idempotency",
    ]
    if args.event_id:
        command.extend(["--event-id", args.event_id])
    if args.event_title:
        command.extend(["--event-title", args.event_title])
    if args.date:
        command.extend(["--date", args.date])
    for doc in args.doc:
        command.extend(["--doc", doc])
    for minute in args.minute:
        command.extend(["--minute", minute])
    if args.idempotency_suffix:
        command.extend(["--idempotency-suffix", args.idempotency_suffix])
    if args.force_index:
        command.append("--force-index")
    if args.write_report:
        command.extend(["--write-report", "--report-dir", args.report_dir])
    return run_or_print(command, dry_run=args.dry_run)


def run_m4(args: argparse.Namespace, settings) -> int:  # noqa: ANN001 - settings 为项目配置对象
    """发送 M4 会后总结卡和待确认卡。"""

    chat_id = args.chat_id or settings.feishu.default_chat_id
    if not chat_id:
        raise SystemExit("缺少测试群 chat_id。请传 --chat-id，或在 config/settings.local.json 设置 feishu.default_chat_id。")

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "post_meeting_live_test.py"),
        "--minute",
        args.minute,
        "--identity",
        args.identity,
        "--allow-write",
        "--send-card",
        "--chat-id",
        chat_id,
        "--receive-id-type",
        args.receive_id_type,
        "--content-limit",
        str(args.content_limit),
        "--report-dir",
        args.report_dir,
        "--related-top-n",
        str(args.related_top_n),
    ]
    if args.skip_related_knowledge:
        command.append("--skip-related-knowledge")
    if args.show_card_json:
        command.append("--show-card-json")
    return run_or_print(command, dry_run=args.dry_run)


def run_m4_callback(args: argparse.Namespace) -> int:
    """启动 M4 按钮回调长连接。"""

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "post_meeting_button_flow_live_test.py"),
        "callback",
        "--log-level",
        args.log_level,
    ]
    if args.dry_run:
        command.append("--dry-run")
    return run_or_print(command, dry_run=args.print_only)


def run_or_print(command: list[str], *, dry_run: bool) -> int:
    """打印命令，并按需执行。"""

    print("将执行：")
    print(" ".join(command))
    if dry_run:
        return 0
    return subprocess.call(command, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
