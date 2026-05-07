from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/tasks_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuAuthError, FeishuClient
from config import load_settings
from core import ActionItem, configure_logging, get_logger


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="真实调用飞书 Python 客户端，测试任务读取与 ActionItem 转换能力。",
    )
    parser.add_argument(
        "--identity",
        default="",
        choices=["tenant", "user"],
        help="请求所使用的飞书身份；不传时默认读取 feishu.default_identity。任务读取必须使用 user。",
    )
    parser.add_argument(
        "--completed",
        choices=["true", "false", "all"],
        default="false",
        help="任务完成状态过滤：false=未完成，true=已完成，all=不过滤。",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="每页任务数量，范围 1-100，默认 50。",
    )
    parser.add_argument(
        "--page-limit",
        type=int,
        default=20,
        help="最多读取多少页，默认 20。",
    )
    parser.add_argument(
        "--page-token",
        default="",
        help="可选：从指定分页 token 开始读取。",
    )
    parser.add_argument(
        "--user-id-type",
        default="open_id",
        choices=["open_id", "user_id", "union_id"],
        help="返回用户 ID 的类型，默认 open_id。",
    )
    parser.add_argument(
        "--query",
        default="",
        help="可选：按任务标题做本地包含过滤。",
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="是否打印每条任务的原始飞书 JSON。",
    )
    return parser.parse_args()


def _parse_completed(value: str) -> bool | None:
    """把命令行字符串转换为飞书接口需要的 completed 过滤值。"""

    if value == "all":
        return None
    return value == "true"


def _filter_tasks(tasks: list[ActionItem], query: str) -> list[ActionItem]:
    """按标题做简单本地过滤，方便快速定位任务。"""

    keyword = query.strip().lower()
    if not keyword:
        return tasks
    return [task for task in tasks if keyword in task.title.lower()]


def _print_task(task: ActionItem, show_raw: bool) -> None:
    """按易读方式打印单条任务。"""

    print("=" * 80)
    print(f"任务 ID: {task.item_id}")
    print(f"标题: {task.title}")
    print(f"负责人: {task.owner or '未返回负责人'}")
    print(f"截止时间(ms): {task.due_date or '未设置'}")
    print(f"状态: {task.status}")
    print(f"链接: {task.extra.get('url', '')}")
    print(f"创建时间(ms): {task.extra.get('created_at', '')}")
    print(f"更新时间(ms): {task.extra.get('updated_at', '')}")
    if task.extra.get("description"):
        print(f"描述: {task.extra.get('description')}")

    if show_raw:
        print("原始 JSON:")
        print(json.dumps(task.extra.get("raw_payload", {}), ensure_ascii=False, indent=2))


def main() -> int:
    """真实测试飞书任务列表接口。"""

    args = _parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.tasks.live_test")
    # 如果命令行没有显式指定身份，就回退到配置中的默认身份。
    identity = args.identity or settings.feishu.default_identity

    logger.info(
        "准备真实调用飞书任务接口 identity=%s completed=%s page_size=%s page_limit=%s",
        identity,
        args.completed,
        args.page_size,
        args.page_limit,
    )

    client = FeishuClient(settings.feishu)
    try:
        tasks = client.list_my_tasks(
            completed=_parse_completed(args.completed),
            page_size=args.page_size,
            page_limit=args.page_limit,
            page_token=args.page_token,
            user_id_type=args.user_id_type,
            identity=identity,
        )
    except FeishuAuthError as error:
        logger.error("飞书鉴权失败：%s", error)
        print(
            "\n鉴权失败。请先检查以下配置是否正确：\n"
            "1. config/settings.local.json 中的 feishu.app_id / feishu.app_secret\n"
            "2. 任务读取必须使用 user 身份，请先执行 python3 scripts/oauth_device_login.py 完成扫码登录\n"
            "3. 确认应用已开通 task:task:read，并重新授权\n"
        )
        return 2
    except FeishuAPIError as error:
        logger.error("飞书任务接口调用失败：%s", error)
        print(f"\n接口调用失败：{error}\n")
        return 3
    except Exception as error:  # pragma: no cover - 这里作为真实联调脚本兜底
        logger.exception("未知异常")
        print(f"\n发生未知异常：{error}\n")
        return 4

    filtered_tasks = _filter_tasks(tasks, args.query)
    print(
        f"\n任务读取成功，共返回 {len(tasks)} 条；"
        f"本地过滤后 {len(filtered_tasks)} 条。completed={args.completed}\n"
    )
    if not filtered_tasks:
        print("没有匹配的任务。你可以尝试：")
        print("1. 使用 --completed all 查看全部任务")
        print("2. 去掉 --query 或换一个关键词")
        print("3. 确认飞书任务里确实有分配给你的任务")
        return 0

    for task in filtered_tasks:
        _print_task(task, show_raw=args.show_raw)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
