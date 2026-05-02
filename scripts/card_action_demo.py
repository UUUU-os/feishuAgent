from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/card_action_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters.feishu_event_handler import FeishuEventHandler
from config import load_settings
from core.card_actions import CardActionRouter
from core.logging import configure_logging
from core.observability import configure_structured_events


def build_demo_payload(action: str) -> dict[str, Any]:
    """构造本地模拟的飞书卡片按钮点击 payload。"""

    return {
        "schema": "2.0",
        "header": {
            "event_id": "evt_card_demo",
            "event_type": "card.action.trigger",
        },
        "event": {
            "operator": {"open_id": "ou_demo"},
            "context": {
                "open_chat_id": "oc_demo",
                "open_message_id": "om_demo",
            },
            "action": {
                "value": {
                    "action": action,
                    "workflow_type": "pre_meeting_brief",
                    "meeting_id": "meeting_demo",
                    "calendar_event_id": "event_demo",
                    "source_card": "pre_meeting_brief",
                    "idempotency_key": f"card:pre_meeting_brief:event_demo:{action}",
                }
            },
        },
    }


def main() -> int:
    """演示卡片点击 payload 解析和 CardActionRouter 路由结果。"""

    parser = argparse.ArgumentParser(description="本地模拟飞书卡片按钮点击。")
    parser.add_argument("--action", default="refresh_pre_meeting_brief", help="模拟按钮动作。")
    parser.add_argument("--show-payload", action="store_true", help="打印模拟飞书原始 payload。")
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.logging)
    configure_structured_events(settings.observability)

    payload = build_demo_payload(args.action)
    handler = FeishuEventHandler()
    router = CardActionRouter()
    action_input = handler.parse_card_action(payload)
    result = router.route(action_input)
    response = handler.build_callback_response(result)

    if args.show_payload:
        print("\n=== FeishuPayload ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\n=== CardActionInput ===")
    print(json.dumps(action_input.to_dict(), ensure_ascii=False, indent=2))
    print("\n=== CardActionResult ===")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if result.agent_input:
        print("\n=== AgentInput ===")
        print(json.dumps(result.agent_input.to_dict(), ensure_ascii=False, indent=2))
    print("\n=== CallbackResponse ===")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
