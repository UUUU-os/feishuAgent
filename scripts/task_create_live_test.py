from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# 允许直接通过 `python3 scripts/task_create_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuAuthError, FeishuClient
from config import load_settings
from core import ActionItem, configure_logging, get_logger


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="真实调用飞书 Python 客户端，测试 ActionItem 创建飞书任务能力。",
    )
    parser.add_argument(
        "--summary",
        required=True,
        help="任务标题。",
    )
    parser.add_argument(
        "--description",
        default="",
        help="任务描述。",
    )
    parser.add_argument(
        "--assignee-open-id",
        action="append",
        default=[],
        help="负责人 open_id，可传多次；不传则创建无负责人任务。",
    )
    parser.add_argument(
        "--due",
        default="",
        help="截止时间，支持毫秒时间戳、YYYY-MM-DD、ISO 时间、+Nd 相对天数。",
    )
    parser.add_argument(
        "--due-all-day",
        action="store_true",
        help="是否按全天截止日期创建任务；YYYY-MM-DD 和 +Nd 默认也会作为全天任务。",
    )
    parser.add_argument(
        "--tasklist-guid",
        default="",
        help="可选：任务清单 GUID。",
    )
    parser.add_argument(
        "--idempotency-key",
        default="",
        help="幂等键；相同键可避免重复创建。",
    )
    parser.add_argument(
        "--identity",
        default="",
        choices=["tenant", "user"],
        help="请求所使用的飞书身份；不传时默认读取 feishu.default_identity。",
    )
    parser.add_argument(
        "--user-id-type",
        default="open_id",
        choices=["open_id", "user_id", "union_id"],
        help="成员 ID 类型，默认 open_id。",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="真正创建任务。不传时只打印将要发送的 payload。",
    )
    return parser.parse_args()


def _parse_due_to_ms(raw_due: str, timezone_name: str) -> tuple[str, bool]:
    """把命令行输入的截止时间转换成飞书需要的毫秒时间戳。"""

    due = raw_due.strip()
    if not due:
        return "", False
    if due.isdigit():
        return due, False

    timezone = ZoneInfo(timezone_name)
    if due.startswith("+") and due.endswith("d") and due[1:-1].isdigit():
        days = int(due[1:-1])
        target = datetime.now(timezone).replace(hour=0, minute=0, second=0, microsecond=0)
        target = target + timedelta(days=days)
        return str(int(target.timestamp() * 1000)), True

    if len(due) == 10:
        target = datetime.strptime(due, "%Y-%m-%d").replace(tzinfo=timezone)
        return str(int(target.timestamp() * 1000)), True

    try:
        target = datetime.fromisoformat(due)
    except ValueError as error:
        raise FeishuAPIError("无法解析 --due，请使用毫秒时间戳、YYYY-MM-DD、ISO 时间或 +Nd") from error

    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone)
    return str(int(target.timestamp() * 1000)), False


def _build_action_item(args: argparse.Namespace, due_timestamp_ms: str) -> ActionItem:
    """把命令行输入先转换成内部 ActionItem，模拟后续工作流产物。"""

    return ActionItem(
        item_id="",
        title=args.summary,
        owner=", ".join(args.assignee_open_id),
        due_date=due_timestamp_ms,
        status="todo",
        confidence=1.0,
        needs_confirm=False,
        extra={
            "description": args.description,
            "source": "scripts/task_create_live_test.py",
        },
    )


def _print_action_item(task: ActionItem) -> None:
    """按易读方式打印创建后的任务。"""

    print("\n任务创建成功，已转换为 ActionItem：")
    print("=" * 80)
    print(f"任务 ID: {task.item_id}")
    print(f"标题: {task.title}")
    print(f"负责人: {task.owner or '未返回负责人'}")
    print(f"截止时间(ms): {task.due_date or '未设置'}")
    print(f"状态: {task.status}")
    print(f"链接: {task.extra.get('url', '')}")
    print("\n完整 ActionItem JSON:")
    print(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))


def main() -> int:
    """真实测试飞书任务创建接口。"""

    args = _parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.task_create.live_test")
    # 如果命令行没有显式指定身份，就回退到配置中的默认身份。
    identity = args.identity or settings.feishu.default_identity

    client = FeishuClient(settings.feishu)
    try:
        due_timestamp_ms, due_all_day_from_parser = _parse_due_to_ms(
            raw_due=args.due,
            timezone_name=settings.app.timezone,
        )
        due_is_all_day = args.due_all_day or due_all_day_from_parser
        action_item = _build_action_item(args, due_timestamp_ms)
        payload = client.build_create_task_payload(
            summary=action_item.title,
            description=action_item.extra.get("description", ""),
            assignee_ids=args.assignee_open_id,
            due_timestamp_ms=action_item.due_date,
            due_is_all_day=due_is_all_day,
            tasklist_guid=args.tasklist_guid,
            idempotency_key=args.idempotency_key,
        )

        print("\n即将创建的飞书任务 payload：")
        print(
            json.dumps(
                {
                    "query": {
                        "user_id_type": args.user_id_type,
                    },
                    "body": payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        if not args.create:
            print("\n当前是 dry-run，没有真正创建任务。确认无误后加上 --create 才会创建。")
            return 0

        logger.info("准备真实创建飞书任务 summary=%s identity=%s", args.summary, identity)
        created_task = client.create_task_from_action_item(
            action_item=action_item,
            assignee_ids=args.assignee_open_id,
            due_is_all_day=due_is_all_day,
            tasklist_guid=args.tasklist_guid,
            idempotency_key=args.idempotency_key,
            user_id_type=args.user_id_type,
            identity=identity,
        )
    except FeishuAuthError as error:
        logger.error("飞书鉴权失败：%s", error)
        print(
            "\n鉴权失败。请先检查以下配置是否正确：\n"
            "1. config/settings.local.json 中的 feishu.app_id / feishu.app_secret\n"
            "2. 若使用 user 身份，请先执行 python3 scripts/oauth_device_login.py 完成扫码登录\n"
            "3. 确认应用已开通 task:task:write，并重新授权\n"
        )
        return 2
    except FeishuAPIError as error:
        logger.error("飞书任务创建接口调用失败：%s", error)
        print(f"\n接口调用失败：{error}\n")
        return 3
    except Exception as error:  # pragma: no cover - 这里作为真实联调脚本兜底
        logger.exception("未知异常")
        print(f"\n发生未知异常：{error}\n")
        return 4

    _print_action_item(created_task)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
