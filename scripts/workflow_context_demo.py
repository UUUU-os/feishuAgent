from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/workflow_context_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import MeetFlowStorage, WorkflowContextBuilder, WorkflowRouter, build_agent_input, configure_logging


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="演示 T2.12 Workflow Context Builder：构建统一 WorkflowContext。",
    )
    parser.add_argument(
        "--event-type",
        default="meeting.soon",
        help="事件类型，例如 meeting.soon / minute.ready / risk.scan.tick / message.command。",
    )
    parser.add_argument("--meeting-id", default="", help="会议 ID。")
    parser.add_argument("--calendar-event-id", default="", help="日历事件 ID。")
    parser.add_argument("--minute-token", default="", help="妙记 token。")
    parser.add_argument("--task-id", default="", help="任务 ID。")
    parser.add_argument("--project-id", default="meetflow", help="项目 ID。")
    parser.add_argument(
        "--with-memory",
        action="store_true",
        help="写入并读取一份 demo 项目记忆，验证 memory_snapshot。",
    )
    return parser.parse_args()


def main() -> int:
    """运行 Workflow Context demo。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)

    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    if args.with_memory:
        storage.save_project_memory(
            args.project_id,
            {
                "project_id": args.project_id,
                "summary": "这是 T2.12 demo 写入的项目记忆。",
                "last_focus": "构建 Agent Runtime 的上下文层。",
            },
        )

    payload = {
        "meeting_id": args.meeting_id,
        "calendar_event_id": args.calendar_event_id,
        "minute_token": args.minute_token,
        "task_id": args.task_id,
        "project_id": args.project_id,
        "participants": [
            {"name": "李健文", "open_id": "ou_demo_owner", "role": "owner"},
            {"name": "MeetFlow Bot", "role": "assistant"},
        ],
        "related_resources": [
            {
                "resource_id": "doc_demo",
                "resource_type": "feishu_document",
                "title": "项目背景文档",
                "content": "这里是已有 payload 中携带的资源摘要。",
                "source_url": "https://example.feishu.cn/docx/demo",
            }
        ],
    }
    payload = {key: value for key, value in payload.items() if not _is_empty_value(value)}

    agent_input = build_agent_input(event_type=args.event_type, payload=payload, source="workflow_context_demo")
    decision = WorkflowRouter().route(agent_input)
    context = WorkflowContextBuilder(storage=storage, default_project_id=args.project_id).build(
        agent_input=agent_input,
        decision=decision,
    )

    print("AgentDecision:")
    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    print("\nWorkflowContext:")
    print(json.dumps(context.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _is_empty_value(value: object) -> bool:
    """判断 demo payload 字段是否为空。"""

    return value is None or value == "" or value == []


if __name__ == "__main__":
    raise SystemExit(main())
