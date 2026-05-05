from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class FeishuCallbackPayloadError(RuntimeError):
    """飞书回调 payload 归一化异常。"""


@dataclass(slots=True)
class FeishuCallbackEnvelope:
    """飞书回调统一信封。

    HTTP 回调、飞书 SDK 长连接和 lark-cli 观察台输出的 JSON 包裹层并不完全
    一样。业务层只消费这个信封，避免在 M3/M4 handler 里散落协议兼容逻辑。
    """

    source: str
    event_type: str
    event_id: str
    action: str
    action_value: dict[str, Any]
    operator_open_id: str = ""
    chat_id: str = ""
    message_id: str = ""
    open_message_id: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)


def normalize_http_callback_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """归一化飞书 HTTP 回调 payload。

    HTTP 通道通常已经是项目现有 `FeishuEventHandler` 可处理的形态，这里只做
    最小校验和浅拷贝，保留 challenge、token 和 encrypt 字段给上层处理。
    """

    if not isinstance(payload, dict):
        raise FeishuCallbackPayloadError("HTTP 回调 payload 必须是 JSON object")
    return dict(payload)


def normalize_sdk_card_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """归一化 `lark_oapi` marshal 后的 card.action.trigger payload。

    飞书 SDK 不同版本可能把按钮 value 放在 `event.action.value`、
    `event.operator.value`、顶层 `action.value` 或顶层 `value`。这里宽松搜索，
    但最终统一成项目现有回调处理器可消费的 `event.action.value`。
    """

    if not isinstance(payload, dict):
        raise FeishuCallbackPayloadError("SDK 回调 payload 必须是 JSON object")

    normalized = dict(payload)
    event = normalized.get("event")
    if isinstance(event, dict):
        action = event.get("action")
        if isinstance(action, dict):
            value = parse_action_value(action.get("value"))
            if value:
                action["value"] = value
                event["action"] = action
                normalized["event"] = event
                return normalized
        operator = event.get("operator")
        if isinstance(operator, dict):
            value = parse_action_value(operator.get("value"))
            if value:
                event["action"] = {"value": value}
                normalized["event"] = event
                return normalized

    action = normalized.get("action")
    if isinstance(action, dict):
        value = parse_action_value(action.get("value"))
        if value:
            normalized.setdefault("event", {})
            if isinstance(normalized["event"], dict):
                normalized["event"]["action"] = {"value": value}
            return normalized

    value = parse_action_value(normalized.get("value"))
    if value:
        normalized.setdefault("event", {})
        if isinstance(normalized["event"], dict):
            normalized["event"]["action"] = {"value": value}
        return normalized

    found_value = find_first_action_value(normalized)
    if found_value:
        normalized.setdefault("event", {})
        if isinstance(normalized["event"], dict):
            normalized["event"]["action"] = {"value": found_value}
        return normalized
    return normalized


def build_callback_envelope(payload: dict[str, Any], source: str) -> FeishuCallbackEnvelope:
    """从统一 payload 中提取飞书回调信封。"""

    if source == "sdk_ws":
        normalized = normalize_sdk_card_action_payload(payload)
    else:
        normalized = normalize_http_callback_payload(payload)

    header = as_dict(normalized.get("header"))
    event = as_dict(normalized.get("event"))
    action = as_dict(event.get("action"))
    context = as_dict(event.get("context"))
    operator = as_dict(event.get("operator"))
    action_value = parse_action_value(action.get("value"))
    action_name = str(action_value.get("action") or action.get("name") or "").strip()

    return FeishuCallbackEnvelope(
        source=source,
        event_type=str(header.get("event_type") or normalized.get("type") or ""),
        event_id=str(header.get("event_id") or normalized.get("event_id") or event.get("event_id") or ""),
        action=action_name,
        action_value=action_value,
        operator_open_id=first_non_empty(
            operator.get("open_id"),
            deep_get(operator, "operator_id", "open_id"),
            deep_get(event, "operator_id", "open_id"),
        ),
        chat_id=first_non_empty(
            context.get("open_chat_id"),
            context.get("chat_id"),
            event.get("open_chat_id"),
            event.get("chat_id"),
        ),
        message_id=first_non_empty(
            context.get("message_id"),
            event.get("message_id"),
        ),
        open_message_id=first_non_empty(
            context.get("open_message_id"),
            event.get("open_message_id"),
        ),
        raw_payload=normalized,
    )


def callback_payload_from_sdk_object(lark: Any, data: Any) -> dict[str, Any]:
    """把飞书 SDK 回调对象转换为普通 dict。"""

    raw = lark.JSON.marshal(data)
    parsed = json.loads(raw or "{}")
    if not isinstance(parsed, dict):
        raise FeishuCallbackPayloadError("SDK 回调对象 marshal 后必须是 JSON object")
    return normalize_sdk_card_action_payload(parsed)


def parse_action_value(raw_value: Any) -> dict[str, Any]:
    """兼容 dict 和 JSON 字符串形式的 action.value。"""

    if isinstance(raw_value, dict):
        return dict(raw_value)
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise FeishuCallbackPayloadError("飞书卡片 action.value 不是合法 JSON") from error
        if isinstance(decoded, dict):
            return decoded
    return {}


def find_first_action_value(data: Any) -> dict[str, Any]:
    """递归查找第一个形如 action.value 的对象。"""

    if isinstance(data, dict):
        action = data.get("action")
        if isinstance(action, dict):
            value = parse_action_value(action.get("value"))
            if value:
                return value
        value = parse_action_value(data.get("value"))
        if value and ("action" in value or "item_id" in value):
            return value
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


def as_dict(value: Any) -> dict[str, Any]:
    """把可选字段安全转换为 dict。"""

    return value if isinstance(value, dict) else {}


def deep_get(data: dict[str, Any], *keys: str) -> Any:
    """读取嵌套字段，避免回调字段差异导致 KeyError。"""

    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current


def first_non_empty(*values: Any) -> str:
    """返回第一个非空字符串。"""

    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""

