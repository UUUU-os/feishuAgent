from __future__ import annotations

import json
import time
from typing import Any

from core.card_actions import CardActionInput, CardActionResult, build_card_action_input
from core.logging import generate_trace_id
from core.observability import emit_structured_event, safe_error_message


class FeishuEventHandlerError(RuntimeError):
    """飞书事件回调处理异常。"""


class FeishuEventHandler:
    """飞书事件回调协议适配器。

    这个类只处理飞书回调协议细节：challenge、token 校验、payload 字段兼容
    和 toast 响应构造。业务动作路由交给 `CardActionRouter`。
    """

    def __init__(self, verification_token: str = "", encrypt_key: str = "") -> None:
        self.verification_token = _normalize_optional_secret(verification_token)
        self.encrypt_key = _normalize_optional_secret(encrypt_key)

    def handle_verification(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """处理飞书 URL verification challenge。"""

        if payload.get("type") == "url_verification" or payload.get("challenge"):
            self._validate_token(payload)
            return {"challenge": str(payload.get("challenge", "") or "")}
        return None

    def parse_card_action(self, payload: dict[str, Any]) -> CardActionInput:
        """从 `card.action.trigger` payload 中解析内部动作输入。"""

        if payload.get("encrypt"):
            raise FeishuEventHandlerError("当前 MVP 尚未实现飞书加密回调解密，请先关闭加密或补充 encrypt_key 解密逻辑。")

        self._validate_token(payload)
        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        if not event:
            raise FeishuEventHandlerError("飞书回调缺少 event 字段")

        event_type = str(header.get("event_type") or payload.get("type") or "")
        if event_type and event_type not in {"card.action.trigger", "card.action_trigger"}:
            raise FeishuEventHandlerError(f"暂不支持的飞书事件类型：{event_type}")

        action_obj = _as_dict(event.get("action"))
        value = _parse_action_value(action_obj.get("value"))
        action_name = str(value.get("action") or action_obj.get("name") or "").strip()
        if not action_name:
            raise FeishuEventHandlerError("飞书卡片动作缺少 action.value.action")

        operator = _as_dict(event.get("operator"))
        context = _as_dict(event.get("context"))
        event_id = str(header.get("event_id") or payload.get("event_id") or event.get("event_id") or "")
        trace_id = str(value.get("trace_id") or event_id or generate_trace_id())
        operator_open_id = _first_non_empty(
            operator.get("open_id"),
            _deep_get(operator, "operator_id", "open_id"),
            _deep_get(event, "operator_id", "open_id"),
        )
        chat_id = _first_non_empty(
            context.get("open_chat_id"),
            context.get("chat_id"),
            event.get("open_chat_id"),
            event.get("chat_id"),
        )
        open_message_id = _first_non_empty(
            context.get("open_message_id"),
            context.get("message_id"),
            event.get("open_message_id"),
            event.get("message_id"),
        )

        action_input = build_card_action_input(
            action=action_name,
            trace_id=trace_id,
            event_id=event_id,
            operator_open_id=operator_open_id,
            chat_id=chat_id,
            open_message_id=open_message_id,
            workflow_type=str(value.get("workflow_type") or ""),
            meeting_id=str(value.get("meeting_id") or ""),
            calendar_event_id=str(value.get("calendar_event_id") or ""),
            source_card=str(value.get("source_card") or ""),
            idempotency_key=str(value.get("idempotency_key") or ""),
            value=value,
            raw_event=event,
            created_at=int(time.time()),
        )
        emit_structured_event(
            "card_action_received",
            trace_id=action_input.trace_id,
            event_id=action_input.event_id,
            action=action_input.action,
            workflow_type=action_input.workflow_type,
            operator_open_id=action_input.operator_open_id,
            chat_id=action_input.chat_id,
            open_message_id=action_input.open_message_id,
            idempotency_key=action_input.idempotency_key,
            status="parsed",
        )
        return action_input

    def build_callback_response(self, result: CardActionResult) -> dict[str, Any]:
        """把内部处理结果转换为飞书卡片回调响应。"""

        if result.response_payload:
            return dict(result.response_payload)
        toast_type = "error" if result.status in {"failed", "blocked"} else "info"
        return {
            "toast": {
                "type": toast_type,
                "content": result.message,
            }
        }

    def handle(self, payload: dict[str, Any], router: Any | None = None) -> dict[str, Any]:
        """处理飞书回调 payload。

        如果传入 router，则会完成解析和路由；否则只处理 challenge，非
        challenge payload 返回空响应，方便 HTTP 层自行组织流程。
        """

        challenge_response = self.handle_verification(payload)
        if challenge_response is not None:
            return challenge_response
        if router is None:
            return {}
        try:
            action_input = self.parse_card_action(payload)
            result = router.route(action_input)
            return self.build_callback_response(result)
        except Exception as error:  # noqa: BLE001 - 回调层要返回可读 toast。
            safe_message = safe_error_message(error)
            return {
                "toast": {
                    "type": "error",
                    "content": f"卡片动作处理失败：{safe_message}",
                }
            }

    def _validate_token(self, payload: dict[str, Any]) -> None:
        """校验飞书 verification token，错误信息不暴露真实 token。"""

        if not self.verification_token:
            return
        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        actual_token = str(payload.get("token") or header.get("token") or "")
        if actual_token != self.verification_token:
            raise FeishuEventHandlerError("飞书回调 verification token 不匹配")


def _parse_action_value(raw_value: Any) -> dict[str, Any]:
    """兼容 dict 和 JSON 字符串形式的 action.value。"""

    if isinstance(raw_value, dict):
        return dict(raw_value)
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise FeishuEventHandlerError("飞书卡片 action.value 不是合法 JSON") from error
        if isinstance(decoded, dict):
            return decoded
    return {}


def _as_dict(value: Any) -> dict[str, Any]:
    """把可选字段安全转换为 dict。"""

    return value if isinstance(value, dict) else {}


def _deep_get(data: dict[str, Any], *keys: str) -> Any:
    """读取嵌套字段，避免回调字段差异导致 KeyError。"""

    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current


def _first_non_empty(*values: Any) -> str:
    """返回第一个非空字符串。"""

    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_optional_secret(value: str) -> str:
    """把示例占位符当作未配置，避免本地 demo 被模板值误拦截。"""

    text = str(value or "").strip()
    if not text or text.startswith("replace-with"):
        return ""
    return text
