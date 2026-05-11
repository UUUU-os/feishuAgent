from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from adapters.feishu_callback_payloads import (
    FeishuCallbackEnvelope,
    build_callback_envelope,
    normalize_http_callback_payload,
    normalize_sdk_card_action_payload,
)
from adapters.feishu_client import FeishuClient
from adapters.feishu_event_handler import FeishuEventHandler
from config.loader import Settings
from core.card_actions import CardActionRouter
from core.card_callback import handle_post_meeting_card_callback
from core.models import AgentInput
from core.observability import emit_structured_event, safe_error_message
from core.policy import AgentPolicy
from core.storage import MeetFlowStorage


POST_MEETING_ACTIONS = {
    "confirm_create_task",
    "reject_create_task",
    "edit_task_fields",
    "view_pending_tasks",
}

PRE_MEETING_ACTIONS = {
    "refresh_pre_meeting_brief",
    "create_task_draft",
    "send_summary_to_me",
}


@dataclass(slots=True)
class FeishuCallbackResponse:
    """统一回调响应。

    `body` 可直接返回给飞书；`agent_input` 用于 M3 刷新这类需要异步执行
    Agent 的动作，入口脚本负责决定是否执行以及是否开放写权限。
    """

    status: str
    body: dict[str, Any]
    agent_input: AgentInput | None = None
    envelope: FeishuCallbackEnvelope | None = None


class FeishuCallbackDispatcher:
    """统一处理飞书卡片与事件回调。

    HTTP 公网回调和官方 SDK 长连接都进入这个分发器。入口层只负责收包、
    验签或建连；M3/M4 业务判断集中在这里，避免两套接入方式行为漂移。
    """

    def __init__(
        self,
        settings: Settings,
        storage: MeetFlowStorage,
        feishu_client: FeishuClient,
        policy: AgentPolicy | None = None,
        card_action_router: CardActionRouter | None = None,
        event_handler: FeishuEventHandler | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.feishu_client = feishu_client
        self.policy = policy or AgentPolicy()
        self.card_action_router = card_action_router or CardActionRouter()
        self.event_handler = event_handler or FeishuEventHandler(
            verification_token=settings.feishu.event_verification_token,
            encrypt_key=settings.feishu.event_encrypt_key,
        )

    def dispatch_http_callback(self, payload: dict[str, Any]) -> FeishuCallbackResponse:
        """处理公网 HTTP 回调，包括 URL verification。"""

        normalized = normalize_http_callback_payload(payload)
        challenge_response = self.event_handler.handle_verification(normalized)
        if challenge_response is not None:
            return FeishuCallbackResponse(status="challenge", body=challenge_response)
        return self.dispatch_card_action(normalized, source="http")

    def dispatch_sdk_card_action(self, payload: dict[str, Any]) -> FeishuCallbackResponse:
        """处理飞书 SDK WebSocket 收到的卡片动作。"""

        normalized = normalize_sdk_card_action_payload(payload)
        return self.dispatch_card_action(normalized, source="sdk_ws")

    def dispatch_card_action(
        self,
        payload: dict[str, Any],
        source: str,
    ) -> FeishuCallbackResponse:
        """分发卡片动作到 M3 或 M4 业务处理器。"""

        try:
            envelope = build_callback_envelope(payload, source=source)
            emit_structured_event(
                "feishu_callback_received",
                trace_id=envelope.event_id or "-",
                source=source,
                feishu_event_type=envelope.event_type,
                action=envelope.action,
                chat_id=envelope.chat_id,
                message_id=envelope.message_id or envelope.open_message_id,
                status="parsed",
            )
            if self._is_post_meeting_action(envelope):
                return self._dispatch_post_meeting(payload=envelope.raw_payload, envelope=envelope)
            if self._is_pre_meeting_action(envelope):
                return self._dispatch_pre_meeting(payload=envelope.raw_payload, envelope=envelope)
            return FeishuCallbackResponse(
                status="ignored",
                body={"toast": {"type": "info", "content": f"暂不支持的卡片动作：{envelope.action or 'unknown'}"}},
                envelope=envelope,
            )
        except Exception as error:  # noqa: BLE001 - 回调入口必须稳定返回 toast。
            safe_message = safe_error_message(error)
            emit_structured_event(
                "feishu_callback_failed",
                trace_id="-",
                source=source,
                status="failed",
                error_type=error.__class__.__name__,
                error_message=safe_message,
            )
            return FeishuCallbackResponse(
                status="error",
                body={"toast": {"type": "error", "content": f"MeetFlow 回调处理失败：{safe_message}"}},
            )

    def _dispatch_post_meeting(
        self,
        payload: dict[str, Any],
        envelope: FeishuCallbackEnvelope,
    ) -> FeishuCallbackResponse:
        """处理 M4 待确认任务卡片动作。"""

        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=self.feishu_client,
            storage=self.storage,
            policy=self.policy,
        )
        return FeishuCallbackResponse(
            status=result.status,
            body=result.to_feishu_response(),
            envelope=envelope,
        )

    def _dispatch_pre_meeting(
        self,
        payload: dict[str, Any],
        envelope: FeishuCallbackEnvelope,
    ) -> FeishuCallbackResponse:
        """处理 M3 会前卡片动作。"""

        handler = self.event_handler if envelope.source == "http" else FeishuEventHandler()
        action_input = handler.parse_card_action(payload)
        result = self.card_action_router.route(action_input)
        return FeishuCallbackResponse(
            status=result.status,
            body=handler.build_callback_response(result),
            agent_input=result.agent_input,
            envelope=envelope,
        )

    @staticmethod
    def _is_post_meeting_action(envelope: FeishuCallbackEnvelope) -> bool:
        """判断是否属于 M4 待确认任务动作。"""

        value = envelope.action_value
        source_card = str(value.get("source_card") or value.get("card_type") or "")
        return (
            envelope.action in POST_MEETING_ACTIONS
            or "post_meeting" in source_card
            or bool(value.get("item_id") and envelope.action in POST_MEETING_ACTIONS)
        )

    @staticmethod
    def _is_pre_meeting_action(envelope: FeishuCallbackEnvelope) -> bool:
        """判断是否属于 M3 会前卡片动作。"""

        value = envelope.action_value
        workflow_type = str(value.get("workflow_type") or "")
        source_card = str(value.get("source_card") or value.get("card_type") or "")
        return (
            envelope.action in PRE_MEETING_ACTIONS
            or workflow_type == "pre_meeting_brief"
            or "pre_meeting" in source_card
        )
