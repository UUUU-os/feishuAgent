from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/meetflow_cli.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.cli_facade import CLIResult, MeetFlowCLI, build_trace_id, result_to_json
from core.observability import safe_error_message


def build_parser() -> argparse.ArgumentParser:
    """构造 MeetFlow / OpenClaw 统一 CLI 参数。"""

    parser = argparse.ArgumentParser(
        description="MeetFlow OpenClaw/CLI 受控工作流入口，默认 dry-run，真实写入必须显式 --allow-write。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="检查配置、migration、报告目录和服务状态。")
    subparsers.add_parser("openclaw-tools", help="输出 OpenClaw 工具清单 JSON。")

    pre = subparsers.add_parser("pre-meeting", help="触发 M3 会前背景知识卡。")
    pre.add_argument("--date", default="today", help="today / tomorrow / YYYY-MM-DD。")
    pre.add_argument("--event-title", default="", help="会议标题关键词。")
    pre.add_argument("--event-id", default="", help="明确的飞书日程 event_id。")
    pre.add_argument("--provider", default="scripted_debug", help="LLM provider，例如 scripted_debug/settings/doubao/deepseek。")
    pre.add_argument("--project-id", default="meetflow", help="项目 ID。")
    pre.add_argument("--doc", action="append", default=[], help="纳入会前 RAG 的飞书文档，可传多次。")
    pre.add_argument("--minute", action="append", default=[], help="纳入会前 RAG 的飞书妙记，可传多次。")
    pre.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取日历/资料的飞书身份。")
    pre.add_argument("--calendar-id", default="primary", help="飞书日历 ID。")
    pre.add_argument("--max-iterations", type=int, default=5, help="Agent 最大迭代次数。")
    pre.add_argument("--force-index", action="store_true", help="强制重建补充资料索引。")
    pre.add_argument("--write-report", action="store_true", help="写入 M3 报告。")
    pre.add_argument("--allow-write", action="store_true", help="允许真实发送飞书卡片。")
    pre.add_argument("--dry-run", action="store_true", help="显式 dry-run；默认已经是 dry-run。")
    pre.add_argument("--idempotency-suffix", default="", help="真实发卡幂等后缀。")
    pre.add_argument("--timeout-seconds", type=int, default=120, help="下游脚本超时时间。")

    post = subparsers.add_parser("post-meeting", help="触发 M4 妙记复盘和会后总结卡。")
    add_post_meeting_args(post)

    tasks = subparsers.add_parser("task-cards", help="根据妙记生成 D4 任务卡视角摘要。")
    add_post_meeting_args(tasks)

    risk = subparsers.add_parser("risk-scan", help="触发 M5 风险巡检。")
    risk.add_argument("--backend", default="local", choices=["local", "feishu"], help="任务来源。")
    risk.add_argument("--mode", default="direct", choices=["direct", "enqueue"], help="直接执行或只入队。")
    risk.add_argument("--chat-id", default="", help="测试群 chat_id。")
    risk.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取任务身份。")
    risk.add_argument("--send-identity", default="tenant", choices=["user", "tenant"], help="发送群卡身份。")
    risk.add_argument("--completed", default="false", choices=["true", "false", "all"], help="任务完成状态过滤。")
    risk.add_argument("--page-size", type=int, default=50, help="飞书任务分页大小。")
    risk.add_argument("--page-limit", type=int, default=20, help="飞书任务最多读取页数。")
    risk.add_argument("--stale-update-days", type=int, default=0, help="长期未更新阈值。")
    risk.add_argument("--due-soon-hours", type=int, default=0, help="即将截止阈值。")
    risk.add_argument("--max-reminders", type=int, default=0, help="每日最大提醒数。")
    risk.add_argument("--show-card", action="store_true", help="输出风险卡 JSON。")
    risk.add_argument("--allow-write", action="store_true", help="允许真实发送风险卡。")
    risk.add_argument("--dry-run", action="store_true", help="显式 dry-run；默认已经是 dry-run。")
    risk.add_argument("--timeout-seconds", type=int, default=180, help="下游脚本超时时间。")

    eval_parser = subparsers.add_parser("eval", help="运行 Agent 轨迹评测。")
    eval_parser.add_argument("--suite", default="agent_trajectory", help="评测套件。")
    eval_parser.add_argument("--case-id", default="", help="只运行指定 case。")
    eval_parser.add_argument("--provider", default="scripted_debug", help="记录本次 provider。")
    eval_parser.add_argument("--fail-under", type=float, default=0.95, help="最低通过分数。")
    eval_parser.add_argument("--write-report", action="store_true", help="写入评测报告。")

    replay = subparsers.add_parser("demo-replay", help="运行离线 E2E 回放。")
    replay.add_argument("--case", default="", help="只运行指定 E2E case。")
    replay.add_argument("--all", action="store_true", help="运行全部 case。")
    replay.add_argument("--fail-under", type=float, default=1.0, help="最低通过分数。")
    replay.add_argument("--write-report", action="store_true", help="写入回放报告。")
    replay.add_argument("--timeout-seconds", type=int, default=180, help="下游脚本超时时间。")

    service = subparsers.add_parser("service", help="管理白名单长期服务。")
    service_subparsers = service.add_subparsers(dest="service_action", required=True)
    service_subparsers.add_parser("list", help="列出服务状态。")
    service_start = service_subparsers.add_parser("start", help="启动白名单服务。")
    service_start.add_argument("name", help="服务名，例如 worker/sdk_callback/m4_callback。")
    service_start.add_argument("--profile", default="default", help="服务 profile。")
    service_stop = service_subparsers.add_parser("stop", help="停止服务。")
    service_stop.add_argument("name", help="服务名。")
    service_logs = service_subparsers.add_parser("logs", help="查看服务日志。")
    service_logs.add_argument("name", help="服务名。")
    service_logs.add_argument("--tail", type=int, default=200, help="尾部行数。")

    live = subparsers.add_parser("live", help="封装真实飞书联调常用长进程和发卡命令。")
    live_subparsers = live.add_subparsers(dest="live_command", required=True)

    sdk = live_subparsers.add_parser("sdk-callback", help="前台启动 SDK 回调服务，只选它或 M4 回调之一。")
    sdk.add_argument("--agent-provider", default="dry-run", help="回调触发 Agent 时使用的 provider。")
    sdk.add_argument("--job-queue", default="workflow", help="入队队列名。")
    sdk.add_argument("--log-level", default="debug", help="SDK 日志级别。")

    worker = live_subparsers.add_parser("worker", help="前台启动 MeetFlow worker。")
    worker.add_argument("--queues", default="workflow,risk_scan,rag_refresh", help="worker 消费队列。")
    worker.add_argument("--poll-seconds", type=int, default=2, help="轮询间隔。")

    d3_card = live_subparsers.add_parser("d3-card", help="重新发送 D3 会后总结卡。")
    d3_card.add_argument("--minute", required=True, help="飞书妙记链接或 token。")
    d3_card.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取妙记身份。")
    d3_card.add_argument("--chat-id", default="", help="测试群 chat_id；不传则使用配置默认群。")
    d3_card.add_argument("--receive-id-type", default="chat_id", help="接收者 ID 类型。")
    d3_card.add_argument("--report-dir", default="storage/reports/m4/d3", help="D3 报告目录。")
    d3_card.add_argument("--show-card-json", action="store_true", help="打印完整卡片 JSON。")
    d3_card.add_argument("--dry-run", action="store_true", help="只打印下游命令，不发送。")

    watch = live_subparsers.add_parser("watch-callbacks", help="观察卡片回调和 workflow event 日志。")
    watch.add_argument("--lines", type=int, default=0, help="tail 初始行数，默认 0。")

    return parser


def add_post_meeting_args(parser: argparse.ArgumentParser) -> None:
    """给 M4/D4 子命令添加共享参数。"""

    parser.add_argument("--minute", required=True, help="飞书妙记链接或 token。")
    parser.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取妙记身份。")
    parser.add_argument("--chat-id", default="", help="测试群 chat_id。")
    parser.add_argument("--content-limit", type=int, default=300, help="报告正文预览长度。")
    parser.add_argument("--related-top-n", type=int, default=5, help="召回相关背景资料数量。")
    parser.add_argument("--skip-related-knowledge", action="store_true", help="跳过相关知识召回。")
    parser.add_argument("--show-card-json", action="store_true", help="输出卡片 JSON。")
    parser.add_argument("--allow-write", action="store_true", help="允许真实发送飞书卡片。")
    parser.add_argument("--dry-run", action="store_true", help="显式 dry-run；默认已经是 dry-run。")
    parser.add_argument("--timeout-seconds", type=int, default=180, help="下游脚本超时时间。")


def run_from_args(args: argparse.Namespace, cli: MeetFlowCLI) -> CLIResult:
    """根据 argparse 结果分发到 CLI facade。"""

    if args.command == "health":
        return cli.health()
    if args.command == "openclaw-tools":
        return cli.openclaw_tools()
    if args.command == "pre-meeting":
        return cli.pre_meeting(
            date=args.date,
            event_title=args.event_title,
            event_id=args.event_id,
            provider=args.provider,
            project_id=args.project_id,
            doc=args.doc,
            minute=args.minute,
            identity=args.identity,
            calendar_id=args.calendar_id,
            max_iterations=args.max_iterations,
            force_index=args.force_index,
            write_report=args.write_report,
            allow_write=args.allow_write,
            idempotency_suffix=args.idempotency_suffix,
            timeout_seconds=args.timeout_seconds,
        )
    if args.command == "post-meeting":
        return cli.post_meeting(**post_kwargs(args))
    if args.command == "task-cards":
        return cli.task_cards(**post_kwargs(args))
    if args.command == "risk-scan":
        return cli.risk_scan(
            backend=args.backend,
            mode=args.mode,
            chat_id=args.chat_id,
            identity=args.identity,
            send_identity=args.send_identity,
            completed=args.completed,
            page_size=args.page_size,
            page_limit=args.page_limit,
            stale_update_days=args.stale_update_days,
            due_soon_hours=args.due_soon_hours,
            max_reminders=args.max_reminders,
            show_card=args.show_card,
            allow_write=args.allow_write,
            timeout_seconds=args.timeout_seconds,
        )
    if args.command == "eval":
        return cli.eval(
            suite=args.suite,
            case_id=args.case_id,
            provider=args.provider,
            fail_under=args.fail_under,
            write_report=args.write_report,
        )
    if args.command == "demo-replay":
        return cli.demo_replay(
            case_id=args.case,
            run_all=args.all,
            fail_under=args.fail_under,
            write_report=args.write_report,
            timeout_seconds=args.timeout_seconds,
        )
    if args.command == "service":
        return cli.service(
            args.service_action,
            name=getattr(args, "name", ""),
            profile=getattr(args, "profile", "default"),
            tail=getattr(args, "tail", 200),
        )
    raise ValueError(f"未知命令：{args.command}")


def build_live_command(args: argparse.Namespace) -> list[str]:
    """构造 D3 真实联调白名单命令。

    这个 live 命令组专门服务“多终端真实飞书联调”，因此允许前台长进程
    运行，但仍然只拼固定脚本和固定参数，不接收任意 shell。
    """

    if args.live_command == "sdk-callback":
        return [
            str(PROJECT_ROOT / ".venv-lark-oapi" / "bin" / "python"),
            str(PROJECT_ROOT / "scripts" / "feishu_event_sdk_server.py"),
            "--enqueue-agent",
            "--agent-provider",
            args.agent_provider,
            "--job-queue",
            args.job_queue,
            "--log-level",
            args.log_level,
        ]
    if args.live_command == "worker":
        return [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "meetflow_worker.py"),
            "--queues",
            args.queues,
            "--poll-seconds",
            str(args.poll_seconds),
        ]
    if args.live_command == "d3-card":
        command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "card_send_live.py"),
            "m4",
            "--minute",
            args.minute,
            "--identity",
            args.identity,
            "--report-dir",
            args.report_dir,
        ]
        if args.chat_id:
            command.extend(["--chat-id", args.chat_id, "--receive-id-type", args.receive_id_type])
        if args.show_card_json:
            command.append("--show-card-json")
        if args.dry_run:
            command.append("--dry-run")
        return command
    if args.live_command == "watch-callbacks":
        return [
            "tail",
            "-n",
            str(args.lines),
            "-f",
            str(PROJECT_ROOT / "storage" / "card_callbacks.jsonl"),
            str(PROJECT_ROOT / "storage" / "workflow_events.jsonl"),
        ]
    raise ValueError(f"未知 live 命令：{args.live_command}")


def run_live_from_args(args: argparse.Namespace) -> int:
    """执行 D3 真实联调前台命令。"""

    command = build_live_command(args)
    print("将执行：")
    print(" ".join(command))
    return subprocess.call(command, cwd=PROJECT_ROOT)


def post_kwargs(args: argparse.Namespace) -> dict[str, object]:
    """提取 M4/D4 共享参数。"""

    return {
        "minute": args.minute,
        "identity": args.identity,
        "chat_id": args.chat_id,
        "content_limit": args.content_limit,
        "related_top_n": args.related_top_n,
        "skip_related_knowledge": args.skip_related_knowledge,
        "show_card_json": args.show_card_json,
        "allow_write": args.allow_write,
        "timeout_seconds": args.timeout_seconds,
    }


def main() -> int:
    """脚本入口。"""

    parser = build_parser()
    args = parser.parse_args()
    if args.command == "live":
        return run_live_from_args(args)
    try:
        result = run_from_args(args, MeetFlowCLI())
    except Exception as error:  # noqa: BLE001 - CLI 需要输出稳定 JSON 错误。
        result = CLIResult(
            status="failed",
            workflow_type=str(getattr(args, "command", "unknown")),
            trace_id=build_trace_id("error"),
            error=safe_error_message(error),
            safety_summary={
                "policy_checked": False,
                "write_blocked_or_confirmed": True,
                "idempotency_key_present": False,
                "secret_redacted": True,
                "raw_shell_disabled": True,
                "whitelist_entrypoint": True,
            },
        )
    print(result_to_json(result))
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
