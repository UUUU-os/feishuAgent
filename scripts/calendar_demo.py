from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# 允许直接从 scripts 目录运行脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuClient
from config import load_settings
from core import CalendarEvent, configure_logging, get_logger


def build_lark_cli_calendar_command(calendar_id: str, start_time: str, end_time: str) -> list[str]:
    """构造 `lark-cli calendar events instance_view` 命令。

    后续如果需要把 CLI 作为调试辅助工具，这个函数可以直接复用。
    """

    params = {
        "calendar_id": calendar_id,
        "start_time": start_time,
        "end_time": end_time,
    }
    return [
        "lark-cli",
        "calendar",
        "events",
        "instance_view",
        "--params",
        json.dumps(params, ensure_ascii=False),
        "--format",
        "pretty",
        "--dry-run",
    ]


def build_demo_calendar_event(client: FeishuClient) -> CalendarEvent:
    """使用模拟数据演示日历事件标准化流程。

    这里不依赖真实飞书网络请求，便于你本地阅读代码和验证模型转换逻辑。
    """

    raw_item = {
        "event_id": "event_demo_001",
        "summary": "MeetFlow 项目周会",
        "description": "讨论会前卡片、会后任务抽取和风险提醒进展",
        "status": "confirmed",
        "app_link": "https://applink.feishu.cn/demo",
        "start_time": {
            "timestamp": "1777111200",
            "timezone": "Asia/Shanghai",
        },
        "end_time": {
            "timestamp": "1777114800",
            "timezone": "Asia/Shanghai",
        },
        "event_organizer": {
            "display_name": "产品经理A",
            "user_id": "ou_demo_owner",
        },
        "attendees": [
            {
                "attendee_id": "att_demo_001",
                "display_name": "产品经理A",
                "type": "user",
                "rsvp_status": "accept",
                "is_optional": False,
                "is_organizer": True,
            },
            {
                "attendee_id": "att_demo_002",
                "display_name": "研发负责人B",
                "type": "user",
                "rsvp_status": "accept",
                "is_optional": False,
                "is_organizer": False,
            },
        ],
    }
    return client.to_calendar_event(raw_item)


def main() -> None:
    """演示会议/日历读取能力的两条实现路径。

    1. Python 客户端：展示日历事件标准化后的结构
    2. lark-cli：展示真实 CLI 调试命令如何构造
    """

    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.calendar.demo")

    client = FeishuClient(settings.feishu)
    demo_event = build_demo_calendar_event(client)
    logger.info(
        "模拟事件标准化完成 summary=%s start_time=%s attendee_count=%s",
        demo_event.summary,
        demo_event.start_time,
        len(demo_event.attendees),
    )

    cli_command = build_lark_cli_calendar_command(
        calendar_id="primary",
        start_time="1777111200",
        end_time="1777197600",
    )
    logger.info("即将演示 lark-cli 调试命令：%s", " ".join(cli_command))

    # 使用 --dry-run 展示请求而不真正执行，便于安全调试和理解参数结构。
    result = subprocess.run(
        cli_command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout.strip():
        logger.info("lark-cli dry-run 输出：\n%s", result.stdout.strip())
    if result.stderr.strip():
        logger.warning("lark-cli dry-run 错误输出：\n%s", result.stderr.strip())


if __name__ == "__main__":
    main()
