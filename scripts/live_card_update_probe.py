from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuClient
from cards.post_meeting import build_pending_action_item_button_card
from config import load_settings
from scripts.meetflow_agent_live_test import save_token_bundle


def parse_args() -> argparse.Namespace:
    """解析真实卡片更新探针参数。"""

    parser = argparse.ArgumentParser(description="发送一张真实飞书待确认卡，并立即更新为结果态。")
    parser.add_argument("--chat-id", default="", help="测试群 chat_id；默认使用配置中的 default_chat_id。")
    parser.add_argument("--title", default="Codex 按钮消失真实验证", help="测试卡片标题。")
    parser.add_argument("--owner", default="李健文", help="测试负责人。")
    parser.add_argument("--due-date", default="2026-05-03", help="测试截止时间。")
    return parser.parse_args()


def main() -> int:
    """执行真实发卡 + 更新验证。"""

    args = parse_args()
    settings = load_settings()
    client = FeishuClient(settings.feishu, user_token_callback=lambda bundle: save_token_bundle(settings, bundle))
    chat_id = args.chat_id or settings.feishu.default_chat_id
    if not chat_id:
        raise SystemExit("缺少 chat_id。请传入 --chat-id，或在 settings.local.json 中设置 default_chat_id。")

    item = SimpleNamespace(
        item_id="action_live_patch_probe",
        title=args.title,
        owner=args.owner,
        due_date=args.due_date,
        priority="medium",
        confidence=0.93,
        evidence_refs=[],
        extra={"confirm_reason": "用于验证 update_multi + card update"},
    )
    artifacts = SimpleNamespace(meeting_summary=SimpleNamespace(topic="Codex 实时验证"))
    review_card = build_pending_action_item_button_card(artifacts, item, mode="review")
    resolved_card = build_pending_action_item_button_card(
        artifacts,
        item,
        mode="resolved",
        status_message="Codex 已通过真实 API 将这张卡更新为结果态。",
        status_kind="success",
    )

    sent = client.send_card_message(
        receive_id=chat_id,
        card=review_card,
        receive_id_type="chat_id",
        idempotency_key="codex-live-patch-probe-1",
        identity="tenant",
    )
    message_id = str(sent.get("message_id") or "")
    print(f"sent_message_id={message_id}")

    updated = client.update_card_message(
        message_id=message_id,
        card=resolved_card,
        identity="tenant",
    )
    print(f"update_result_keys={sorted(updated.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
