from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# 允许直接通过 `python3 scripts/calendar_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuAuthError, FeishuClient
from config import load_settings
from core import CalendarEvent, CalendarInfo, configure_logging, get_logger


def _to_unix_seconds(dt: datetime) -> str:
    """把带时区的 datetime 转成秒级时间戳字符串。"""

    return str(int(dt.timestamp()))


def _build_default_time_range(timezone_name: str) -> tuple[str, str]:
    """生成默认查询区间。

    默认查询“现在起未来 24 小时”的日历事件，方便快速验证接口是否跑通。
    """

    timezone = ZoneInfo(timezone_name)
    now = datetime.now(timezone)
    end = now + timedelta(days=1)
    return _to_unix_seconds(now), _to_unix_seconds(end)


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="真实调用飞书 Python 客户端，测试日历/会议读取能力是否可用。",
    )
    parser.add_argument(
        "--calendar-id",
        default="primary",
        help="要查询的日历 ID，默认使用 primary。",
    )
    parser.add_argument(
        "--start-time",
        default="",
        help="查询开始时间，秒级时间戳；不传则默认使用当前时间。",
    )
    parser.add_argument(
        "--end-time",
        default="",
        help="查询结束时间，秒级时间戳；不传则默认使用未来 24 小时。",
    )
    parser.add_argument(
        "--user-id-type",
        default="",
        help="可选：user_id 类型，如 user_id / union_id / open_id。",
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="是否额外打印原始事件 JSON。",
    )
    parser.add_argument(
        "--identity",
        default="",
        choices=["tenant", "user"],
        help="请求所使用的飞书身份；不传时默认读取 feishu.default_identity。",
    )
    parser.add_argument(
        "--debug-calendar",
        action="store_true",
        help="是否打印主日历列表和解析后的真实日历详情。",
    )
    return parser.parse_args()


def _print_event_summary(event: CalendarEvent, show_raw: bool) -> None:
    """把单条日历事件按易读方式打印出来。"""

    print("=" * 80)
    print(f"事件 ID: {event.event_id}")
    print(f"会议标题: {event.summary}")
    print(f"开始时间: {event.start_time}")
    print(f"结束时间: {event.end_time}")
    print(f"时区: {event.timezone}")
    print(f"组织者: {event.organizer_name} ({event.organizer_id})")
    print(f"状态: {event.status}")
    print(f"描述: {event.description}")
    print(f"跳转链接: {event.app_link}")
    print("参与人:")
    if not event.attendees:
        print("  - 无参与人信息")
    else:
        for attendee in event.attendees:
            print(
                "  - "
                f"name={attendee.display_name}, "
                f"type={attendee.attendee_type}, "
                f"rsvp={attendee.rsvp_status}, "
                f"optional={attendee.is_optional}, "
                f"organizer={attendee.is_organizer}"
            )

    if show_raw:
        print("原始 JSON:")
        print(json.dumps(event.raw_payload, ensure_ascii=False, indent=2))


def _print_calendar_info(title: str, calendar: CalendarInfo) -> None:
    """按易读方式打印日历基础信息。"""

    print("=" * 80)
    print(title)
    print(f"calendar_id: {calendar.calendar_id}")
    print(f"summary: {calendar.summary}")
    print(f"description: {calendar.description}")
    print(f"permissions: {calendar.permissions}")
    print(f"type: {calendar.calendar_type}")
    print(f"summary_alias: {calendar.summary_alias}")
    print(f"is_deleted: {calendar.is_deleted}")
    print(f"is_third_party: {calendar.is_third_party}")
    print(f"role: {calendar.role}")
    print(f"user_id: {calendar.user_id}")
    print("原始 JSON:")
    print(json.dumps(calendar.raw_payload, ensure_ascii=False, indent=2))


def main() -> int:
    """真实测试飞书日历接口。

    成功时返回 0，失败时返回非 0，方便你后续接入自动化脚本。
    """

    args = _parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.calendar.live_test")
    # 如果命令行没有显式指定身份，就回退到配置中的默认身份。
    identity = args.identity or settings.feishu.default_identity

    start_time, end_time = args.start_time, args.end_time
    if not start_time or not end_time:
        start_time, end_time = _build_default_time_range(settings.app.timezone)

    logger.info(
        "准备真实调用飞书日历接口 calendar_id=%s start_time=%s end_time=%s",
        args.calendar_id,
        start_time,
        end_time,
    )
    logger.info("当前使用的飞书身份=%s", identity)
    logger.info("当前使用的日历后端=http")
    client = FeishuClient(settings.feishu)

    try:
        if args.debug_calendar:
            primary_calendars = client.get_primary_calendars(identity=identity)
            resolved_calendar_id = client.resolve_calendar_id(args.calendar_id, identity=identity)
            resolved_calendar = client.get_calendar(resolved_calendar_id, identity=identity)
            print(f"\n主日历接口返回 {len(primary_calendars)} 条记录\n")
            for index, calendar in enumerate(primary_calendars, start=1):
                _print_calendar_info(f"主日历候选 #{index}", calendar)

            print()
            _print_calendar_info("当前用于事件查询的真实日历", resolved_calendar)

        events = client.list_calendar_event_instances(
            calendar_id=args.calendar_id,
            start_time=start_time,
            end_time=end_time,
            user_id_type=args.user_id_type or None,
            identity=identity,
        )
    except FeishuAuthError as error:
        logger.error("飞书鉴权失败：%s", error)
        print(
            "\n鉴权失败。请先检查以下配置是否正确：\n"
            "1. config/settings.local.json 中的 feishu.app_id / feishu.app_secret\n"
            "2. 若使用 tenant 身份，请检查环境变量 MEETFLOW_FEISHU_APP_ID / MEETFLOW_FEISHU_APP_SECRET\n"
            "3. 若使用 user 身份，请先执行 python3 scripts/oauth_device_login.py 完成扫码登录\n"
        )
        return 2
    except FeishuAPIError as error:
        logger.error("飞书接口调用失败：%s", error)
        print(f"\n接口调用失败：{error}\n")
        return 3
    except Exception as error:  # pragma: no cover - 这里作为真实联调脚本兜底
        logger.exception("未知异常")
        print(f"\n发生未知异常：{error}\n")
        return 4

    print(
        f"\n查询成功，共返回 {len(events)} 条事件。"
        f" calendar_id={args.calendar_id} start_time={start_time} end_time={end_time}\n"
    )

    if not events:
        print("当前时间窗口内没有查询到事件。你可以尝试：")
        print("1. 改大查询时间范围")
        print("2. 检查 calendar_id 是否正确")
        print("3. 先用 lark-cli calendar +agenda 看看该账号是否确实有日程")
        return 0

    for event in events:
        _print_event_summary(event, show_raw=args.show_raw)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
