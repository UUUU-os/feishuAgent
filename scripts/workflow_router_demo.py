from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/workflow_router_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import WorkflowRouter, build_agent_input


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="演示 T2.11 Workflow Router：把 AgentInput 路由为 AgentDecision。",
    )
    parser.add_argument(
        "--event-type",
        default="meeting.soon",
        help="事件类型，例如 meeting.soon / minute.ready / risk.scan.tick / message.command。",
    )
    parser.add_argument(
        "--trigger-type",
        default="manual",
        help="触发类型，例如 event / schedule / command / manual。",
    )
    parser.add_argument(
        "--workflow-type",
        default="",
        help="message.command 场景下可指定目标 workflow_type。",
    )
    parser.add_argument(
        "--event-id",
        default="",
        help="事件 ID，用于生成幂等键。",
    )
    parser.add_argument(
        "--meeting-id",
        default="",
        help="会议 ID，用于生成幂等键。",
    )
    parser.add_argument(
        "--minute-token",
        default="",
        help="妙记 token，用于生成幂等键。",
    )
    parser.add_argument(
        "--task-id",
        default="",
        help="任务 ID，用于生成幂等键。",
    )
    return parser.parse_args()


def main() -> int:
    """运行 Workflow Router demo。"""

    args = parse_args()
    payload = {
        "event_id": args.event_id,
        "meeting_id": args.meeting_id,
        "minute_token": args.minute_token,
        "task_id": args.task_id,
    }
    if args.workflow_type:
        payload["workflow_type"] = args.workflow_type

    # 清理空值，让 demo 输出更贴近真实事件 payload。
    payload = {key: value for key, value in payload.items() if value}

    agent_input = build_agent_input(
        event_type=args.event_type,
        trigger_type=args.trigger_type,
        payload=payload,
        source="workflow_router_demo",
    )
    decision = WorkflowRouter().route(agent_input)

    print("AgentInput:")
    print(json.dumps(agent_input.to_dict(), ensure_ascii=False, indent=2))
    print("\nAgentDecision:")
    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
