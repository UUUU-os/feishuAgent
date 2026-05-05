from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/risk_scan_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuAuthError, FeishuClient
from cards import build_risk_scan_card
from config import load_settings
from core import (
    MeetFlowStorage,
    configure_logging,
    configure_structured_events,
    decide_risk_notification,
    get_logger,
    normalize_task_snapshots,
    scan_risks,
)
from core.jobs import JobQueue


def parse_args() -> argparse.Namespace:
    """解析 M5 风险巡检 demo 参数。"""

    parser = argparse.ArgumentParser(description="MeetFlow M5 风险巡检本地/飞书演示入口。")
    parser.add_argument("--backend", choices=["local", "feishu"], default="local", help="local 使用 mock；feishu 真实读取任务。")
    parser.add_argument("--show-card", action="store_true", help="打印风险卡片 JSON。")
    parser.add_argument("--allow-write", action="store_true", help="允许向飞书测试群发送风险卡片。")
    parser.add_argument("--chat-id", default="", help="风险卡片接收群，不传则使用配置 feishu.default_chat_id。")
    parser.add_argument("--identity", choices=["user", "tenant"], default="user", help="读取任务使用的飞书身份，任务接口通常用 user。")
    parser.add_argument("--send-identity", choices=["user", "tenant"], default="tenant", help="发送群消息使用的飞书身份，机器人通常用 tenant。")
    parser.add_argument("--completed", choices=["true", "false", "all"], default="false", help="任务完成状态过滤。")
    parser.add_argument("--page-size", type=int, default=50, help="飞书任务读取单页数量。")
    parser.add_argument("--page-limit", type=int, default=20, help="飞书任务最多读取页数。")
    parser.add_argument("--stale-update-days", type=int, default=0, help="覆盖配置中的长期未更新天数。")
    parser.add_argument("--due-soon-hours", type=int, default=0, help="覆盖配置中的即将截止小时数。")
    parser.add_argument("--max-reminders", type=int, default=0, help="覆盖配置中的每日最大提醒数量。")
    parser.add_argument("--enqueue", action="store_true", help="只写入 risk_scan.run 后台任务，由 meetflow_worker 执行。")
    parser.add_argument("--job-queue", default="risk_scan", help="入队队列名，默认 risk_scan。")
    parser.add_argument("--job-priority", type=int, default=100, help="入队优先级，数值越小越先执行。")
    return parser.parse_args()


def main() -> int:
    """执行一次风险巡检 demo。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    configure_structured_events(settings.observability)
    logger = get_logger("meetflow.risk_scan.demo")

    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    if args.enqueue:
        job = enqueue_risk_scan_job(args, settings)
        print("已写入风险巡检后台任务：")
        print(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))
        return 0
    now = int(time.time())
    stale_update_days = args.stale_update_days or settings.risk_rules.stale_update_days
    due_soon_hours = args.due_soon_hours or settings.risk_rules.due_soon_hours
    max_reminders = args.max_reminders or settings.risk_rules.max_reminders_per_day

    try:
        task_items = load_tasks(args, settings)
    except FeishuAuthError as error:
        logger.error("飞书鉴权失败：%s", error)
        print("\n鉴权失败：请先完成 user 身份 OAuth，并确认 task:task:read 权限已发布生效。\n")
        return 2
    except FeishuAPIError as error:
        logger.error("飞书任务或消息接口调用失败：%s", error)
        print(f"\n飞书接口调用失败：{error}\n")
        return 3

    snapshots = normalize_task_snapshots(task_items)
    scan_result = scan_risks(
        tasks=snapshots,
        now=now,
        stale_update_days=stale_update_days,
        due_soon_hours=due_soon_hours,
    )
    decision = decide_risk_notification(
        scan_result=scan_result,
        storage=storage,
        max_reminders_per_day=max_reminders,
        now=now,
    )
    card = build_risk_scan_card(decision=decision, scan_result=scan_result)

    print_scan_result(scan_result.to_dict(), decision.to_dict())
    if args.show_card:
        print("\n" + "=" * 80)
        print("RiskScanCard JSON")
        print("=" * 80)
        print(json.dumps(card, ensure_ascii=False, indent=2))

    if not args.allow_write:
        print("\n当前为 dry-run，没有发送飞书消息。需要真实发送时加 --allow-write。")
        return 0

    if args.backend != "feishu":
        print("\nlocal backend 不会发送真实飞书消息。请使用 --backend feishu --allow-write。")
        return 0

    if not decision.should_notify:
        print(f"\n无需发送风险提醒：{decision.reason}")
        return 0

    client = FeishuClient(settings.feishu)
    receive_id = args.chat_id or settings.feishu.default_chat_id
    if not receive_id:
        print("\n缺少 chat_id。请传 --chat-id 或配置 feishu.default_chat_id。")
        return 4

    response = client.send_card_message(
        receive_id=receive_id,
        card=card,
        receive_id_type="chat_id",
        idempotency_key=decision.idempotency_key,
        identity=args.send_identity,
    )
    record_notification_history(
        storage=storage,
        decision=decision.to_dict(),
        scan_result=scan_result.to_dict(),
        recipient=receive_id,
        now=now,
    )
    storage.record_idempotency_key(
        idempotency_key=decision.idempotency_key,
        workflow_name="risk_scan",
        trace_id=f"risk_scan_demo_{now}",
    )
    print("\n风险卡片发送成功：")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def load_tasks(args: argparse.Namespace, settings: Any) -> list[Any]:
    """根据 backend 读取任务列表。"""

    if args.backend == "local":
        return build_local_risk_demo_tasks()
    client = FeishuClient(settings.feishu)
    return client.list_my_tasks(
        completed=parse_completed(args.completed),
        page_size=args.page_size,
        page_limit=args.page_limit,
        identity=args.identity,
    )


def enqueue_risk_scan_job(args: argparse.Namespace, settings: Any) -> Any:
    """把风险巡检请求写入后台队列。

    入队只记录运行参数，不直接访问飞书任务，也不发送卡片；真实副作用由
    `scripts/meetflow_worker.py` 后续执行，仍会检查 `--allow-write`。
    """

    now = int(time.time())
    payload = {
        "backend": args.backend,
        "show_card": bool(args.show_card),
        "allow_write": bool(args.allow_write),
        "chat_id": args.chat_id or settings.feishu.default_chat_id,
        "identity": args.identity,
        "send_identity": args.send_identity,
        "completed": args.completed,
        "page_size": args.page_size,
        "page_limit": args.page_limit,
        "stale_update_days": args.stale_update_days,
        "due_soon_hours": args.due_soon_hours,
        "max_reminders": args.max_reminders,
    }
    queue = JobQueue(settings.storage)
    return queue.enqueue(
        queue_name=args.job_queue,
        job_type="risk_scan.run",
        payload=payload,
        idempotency_key=f"risk_scan:{args.backend}:{payload['chat_id']}:{now}",
        priority=args.job_priority,
        max_attempts=settings.jobs.max_attempts,
    )


def parse_completed(value: str) -> bool | None:
    """把命令行 completed 参数转换为飞书接口参数。"""

    if value == "all":
        return None
    return value == "true"


def build_local_risk_demo_tasks() -> list[dict[str, Any]]:
    """构造本地 M5 风险巡检样本任务。"""

    now = int(time.time())
    return [
        build_task(
            task_id="task_overdue_demo",
            title="完成客户方案评审",
            owner="张三",
            due_timestamp=now - 30 * 60 * 60,
            updated_at=now - 2 * 24 * 60 * 60,
        ),
        build_task(
            task_id="task_stale_demo",
            title="补齐上线风险清单",
            owner="李四",
            due_timestamp=now + 3 * 24 * 60 * 60,
            updated_at=now - 5 * 24 * 60 * 60,
        ),
        build_task(
            task_id="task_due_soon_demo",
            title="确认明日演示数据",
            owner="王五",
            due_timestamp=now + 6 * 60 * 60,
            updated_at=now - 2 * 60 * 60,
        ),
        build_task(
            task_id="task_missing_owner_demo",
            title="整理会议遗留问题",
            owner="",
            due_timestamp=now + 2 * 24 * 60 * 60,
            updated_at=now - 1 * 60 * 60,
        ),
        build_task(
            task_id="task_done_demo",
            title="已完成的历史任务",
            owner="赵六",
            due_timestamp=now - 2 * 24 * 60 * 60,
            updated_at=now - 1 * 24 * 60 * 60,
            status="completed",
            completed_at=now - 1 * 24 * 60 * 60,
        ),
    ]


def build_task(
    task_id: str,
    title: str,
    owner: str,
    due_timestamp: int,
    updated_at: int,
    status: str = "todo",
    completed_at: int = 0,
) -> dict[str, Any]:
    """构造本地任务字典，模拟 `tasks.list_my_tasks` 的序列化结果。"""

    return {
        "item_id": task_id,
        "title": title,
        "owner": owner,
        "due_date": str(due_timestamp),
        "status": status,
        "extra": {
            "task_id": task_id,
            "updated_at": str(updated_at),
            "completed_at": str(completed_at) if completed_at else "",
            "url": f"https://example.feishu.cn/task/{task_id}",
        },
    }


def print_scan_result(scan_result: dict[str, Any], decision: dict[str, Any]) -> None:
    """打印风险巡检结果摘要。"""

    print("\n" + "=" * 80)
    print("RiskScanResult")
    print("=" * 80)
    print(json.dumps(scan_result, ensure_ascii=False, indent=2))
    print("\n" + "=" * 80)
    print("RiskNotificationDecision")
    print("=" * 80)
    print(json.dumps(decision, ensure_ascii=False, indent=2))


def record_notification_history(
    storage: MeetFlowStorage,
    decision: dict[str, Any],
    scan_result: dict[str, Any],
    recipient: str,
    now: int,
) -> None:
    """真实发送成功后记录风险提醒历史，用于后续降噪。"""

    suppressed_until = now + 24 * 60 * 60
    for risk in decision.get("notify_risks", []):
        task = risk.get("task", {}) if isinstance(risk, dict) else {}
        storage.record_risk_notification(
            risk_key=str(risk.get("dedupe_key", "")),
            task_id=str(risk.get("task_id", "")),
            risk_type=str(risk.get("risk_type", "")),
            severity=str(risk.get("severity", "")),
            status="notified",
            trace_id=f"risk_scan_demo_{now}",
            recipient=recipient,
            summary=str(risk.get("reason", "")),
            payload={
                "title": task.get("title", ""),
                "scan_result_summary": scan_result.get("summary", ""),
            },
            notified_at=now,
            suppressed_until=suppressed_until,
        )


if __name__ == "__main__":
    raise SystemExit(main())
