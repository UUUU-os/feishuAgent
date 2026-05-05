from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/post_meeting_card_callback_ws.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuClient
from config import load_settings
from core import AgentPolicy, MeetFlowStorage, configure_logging, get_logger, handle_post_meeting_card_callback
from scripts.meetflow_agent_live_test import save_token_bundle


def parse_args() -> argparse.Namespace:
    """解析卡片回调长连接参数。"""

    parser = argparse.ArgumentParser(
        description="M4 卡片按钮长连接回调服务，使用飞书 Python SDK 接收 card.action.trigger。"
    )
    parser.add_argument("--log-level", default="", help="SDK 日志级别：debug/info/warn/error；不传使用 SDK 默认。")
    parser.add_argument("--dry-run", action="store_true", help="只打印卡片回调，不创建任务。")
    return parser.parse_args()


def main() -> int:
    """启动飞书 SDK WebSocket 长连接，承接卡片按钮回调。"""

    args = parse_args()
    try:
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger,
            P2CardActionTriggerResponse,
        )
    except ImportError:
        print("缺少飞书 Python SDK：lark-oapi")
        print("请先安装：python3 -m pip install 'lark-oapi==1.4.0'")
        return 2

    settings = load_settings()
    configure_logging(settings.logging)
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(settings.feishu, user_token_callback=lambda bundle: save_token_bundle(settings, bundle))
    policy = AgentPolicy()
    logger = get_logger("meetflow.post_meeting.card_callback_ws")

    if not settings.feishu.app_id or not settings.feishu.app_secret:
        raise SystemExit("缺少 feishu.app_id 或 feishu.app_secret，无法启动卡片回调长连接。")

    def do_card_action_trigger(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        """处理 card.action.trigger，并复用现有 M4 卡片回调核心逻辑。"""

        payload = callback_payload_to_dict(lark, data)
        logger.info("收到 card.action.trigger keys=%s dry_run=%s", sorted(payload.keys()), args.dry_run)
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return P2CardActionTriggerResponse(
                {"toast": {"type": "info", "content": "MeetFlow dry-run：已收到按钮回调。"}}
            )
        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=settings,
            client=client,
            storage=storage,
            policy=policy,
        )
        return P2CardActionTriggerResponse(result.to_feishu_response())

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(do_card_action_trigger)
        .build()
    )

    kwargs: dict[str, Any] = {"event_handler": event_handler}
    log_level = resolve_lark_log_level(lark, args.log_level)
    if log_level is not None:
        kwargs["log_level"] = log_level
    ws_client = lark.ws.Client(settings.feishu.app_id, settings.feishu.app_secret, **kwargs)
    print("M4 卡片按钮长连接回调服务已启动，等待 card.action.trigger。")
    print("请确保飞书开放平台 > 事件与回调 > 回调配置 已选择“使用长连接接收回调”。")
    ws_client.start()
    return 0


def callback_payload_to_dict(lark: Any, data: Any) -> dict[str, Any]:
    """把 SDK 回调对象转换成现有 `handle_post_meeting_card_callback` 可处理的 dict。"""

    raw = lark.JSON.marshal(data)
    parsed = json.loads(raw or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("card.action.trigger payload 必须是 JSON object")
    return normalize_card_action_payload(parsed)


def normalize_card_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """兼容 SDK 对卡片回调的包裹结构，确保 event.action.value 可被提取。"""

    event = payload.get("event")
    if isinstance(event, dict):
        action = event.get("action")
        if isinstance(action, dict) and isinstance(action.get("value"), dict):
            return payload
        operator = event.get("operator")
        if isinstance(operator, dict) and isinstance(operator.get("value"), dict):
            event["action"] = {"value": operator["value"]}
            return payload

    action = payload.get("action")
    if isinstance(action, dict) and isinstance(action.get("value"), dict):
        return {"event": {"action": action}}

    value = payload.get("value")
    if isinstance(value, dict):
        return {"event": {"action": {"value": value}}}

    # SDK 可能把 action/value 放在 data 或 schema 子对象里。这里宽松搜索一次，
    # 避免因为包裹结构差异导致按钮事件被误判为未识别。
    found_value = find_first_action_value(payload)
    if found_value:
        normalized = dict(payload)
        normalized.setdefault("event", {})
        if isinstance(normalized["event"], dict):
            normalized["event"]["action"] = {"value": found_value}
        return normalized
    return payload


def find_first_action_value(data: Any) -> dict[str, Any]:
    """递归查找第一个形如 action.value 的对象。"""

    if isinstance(data, dict):
        action = data.get("action")
        if isinstance(action, dict) and isinstance(action.get("value"), dict):
            return dict(action["value"])
        value = data.get("value")
        if isinstance(value, dict) and ("action" in value or "item_id" in value):
            return dict(value)
        for item in data.values():
            found = find_first_action_value(item)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = find_first_action_value(item)
            if found:
                return found
    return {}


def resolve_lark_log_level(lark: Any, value: str) -> Any:
    """把命令行日志级别转换为 SDK 常量。"""

    normalized = value.strip().lower()
    if not normalized:
        return None
    log_level_enum = getattr(lark, "LogLevel", None)
    if log_level_enum is None:
        return None

    # `lark-oapi==1.4.0` 使用 `WARNING`，而不是 `WARN`。这里按字符串查找，
    # 避免在构造映射表时提前访问不存在的枚举成员，导致 dry-run 启动前崩溃。
    member_name_mapping = {
        "debug": "DEBUG",
        "info": "INFO",
        "warn": "WARNING",
        "warning": "WARNING",
        "error": "ERROR",
        "critical": "CRITICAL",
    }
    member_name = member_name_mapping.get(normalized)
    if not member_name:
        return None
    return getattr(log_level_enum, member_name, None)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nM4 卡片按钮长连接回调服务已停止。")
        raise SystemExit(130)
