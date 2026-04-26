from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.models import AgentToolCall, BaseModel, WorkflowContext
from core.storage import MeetFlowStorage
from core.tools import AgentTool


class AgentPolicyError(RuntimeError):
    """Agent Policy 判断异常。"""


@dataclass(slots=True)
class PolicyDecision(BaseModel):
    """单次策略判断结果。

    `status` 约定：
    - allow：允许执行
    - blocked：直接阻止
    - needs_confirmation：需要人工确认后再执行
    """

    status: str
    reason: str
    tool_name: str = ""
    idempotency_key: str = ""
    patched_arguments: dict[str, Any] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_allowed(self) -> bool:
        """判断策略是否允许继续执行工具。"""

        return self.status == "allow"


@dataclass(slots=True)
class AgentPolicyConfig:
    """Agent 自动化边界配置。"""

    min_action_item_confidence: float = 0.75
    require_task_owner: bool = True
    require_task_due_date: bool = True
    require_idempotency_for_writes: bool = True
    reminder_dedupe_seconds: int = 24 * 60 * 60


@dataclass(slots=True)
class AgentPolicy:
    """MeetFlow Agent 自动化边界。

    这个类不负责“怎么调用工具”，只负责回答：
    - 这个工具调用是否允许自动执行
    - 如果不允许，是阻止还是进入人工确认
    - 是否需要补齐幂等键
    """

    config: AgentPolicyConfig = field(default_factory=AgentPolicyConfig)

    def authorize_tool_call(
        self,
        context: WorkflowContext,
        tool: AgentTool,
        tool_call: AgentToolCall,
        allow_write: bool = False,
        storage: MeetFlowStorage | None = None,
    ) -> PolicyDecision:
        """在工具真正执行前进行策略判断。"""

        if tool.read_only:
            return PolicyDecision(
                status="allow",
                reason="只读工具允许自动执行。",
                tool_name=tool.internal_name,
                patched_arguments=dict(tool_call.arguments),
            )

        if not allow_write:
            return PolicyDecision(
                status="blocked",
                reason="写工具未开启自动执行权限，请显式传入 allow_write。",
                tool_name=tool.internal_name,
                patched_arguments=dict(tool_call.arguments),
            )

        patched_arguments = dict(tool_call.arguments)
        idempotency_key = self._resolve_idempotency_key(
            context=context,
            tool=tool,
            arguments=patched_arguments,
        )
        if self.config.require_idempotency_for_writes and not idempotency_key:
            return PolicyDecision(
                status="needs_confirmation",
                reason="写操作缺少幂等键，不能自动执行。",
                tool_name=tool.internal_name,
                patched_arguments=patched_arguments,
                required_fields=["idempotency_key"],
            )

        if idempotency_key:
            patched_arguments.setdefault("idempotency_key", idempotency_key)
            if storage and self._is_duplicate_side_effect(storage, idempotency_key):
                return PolicyDecision(
                    status="blocked",
                    reason=f"同一写操作幂等键已处理，跳过重复执行：{idempotency_key}",
                    tool_name=tool.internal_name,
                    idempotency_key=idempotency_key,
                    patched_arguments=patched_arguments,
                )

        if tool.side_effect == "create_task":
            task_decision = self._authorize_create_task(
                tool=tool,
                arguments=patched_arguments,
                idempotency_key=idempotency_key,
            )
            if not task_decision.is_allowed():
                return task_decision

        if context.workflow_type == "risk_scan" and tool.side_effect == "send_message":
            reminder_decision = self._authorize_risk_reminder(
                tool=tool,
                arguments=patched_arguments,
                idempotency_key=idempotency_key,
            )
            if not reminder_decision.is_allowed():
                return reminder_decision

        return PolicyDecision(
            status="allow",
            reason="写工具通过 AgentPolicy 检查。",
            tool_name=tool.internal_name,
            idempotency_key=idempotency_key,
            patched_arguments=patched_arguments,
        )

    def _authorize_create_task(
        self,
        tool: AgentTool,
        arguments: dict[str, Any],
        idempotency_key: str,
    ) -> PolicyDecision:
        """检查任务创建是否满足自动化条件。"""

        missing_fields: list[str] = []
        confidence = float(arguments.get("confidence", 1.0) or 0.0)
        assignee_ids = arguments.get("assignee_ids") or []
        due_timestamp_ms = str(arguments.get("due_timestamp_ms", "") or "")

        if confidence < self.config.min_action_item_confidence:
            return PolicyDecision(
                status="needs_confirmation",
                reason=f"行动项置信度 {confidence:.2f} 低于阈值 {self.config.min_action_item_confidence:.2f}。",
                tool_name=tool.internal_name,
                idempotency_key=idempotency_key,
                patched_arguments=arguments,
                required_fields=["confidence"],
            )

        if self.config.require_task_owner and not assignee_ids:
            missing_fields.append("assignee_ids")
        if self.config.require_task_due_date and not due_timestamp_ms:
            missing_fields.append("due_timestamp_ms")

        if missing_fields:
            return PolicyDecision(
                status="needs_confirmation",
                reason="任务缺少负责人或截止时间，进入待确认。",
                tool_name=tool.internal_name,
                idempotency_key=idempotency_key,
                patched_arguments=arguments,
                required_fields=missing_fields,
            )

        return PolicyDecision(
            status="allow",
            reason="任务创建满足自动化条件。",
            tool_name=tool.internal_name,
            idempotency_key=idempotency_key,
            patched_arguments=arguments,
        )

    def _authorize_risk_reminder(
        self,
        tool: AgentTool,
        arguments: dict[str, Any],
        idempotency_key: str,
    ) -> PolicyDecision:
        """检查风险提醒是否具备降噪条件。"""

        if not idempotency_key:
            return PolicyDecision(
                status="needs_confirmation",
                reason="风险提醒缺少幂等键，无法做当天降噪。",
                tool_name=tool.internal_name,
                patched_arguments=arguments,
                required_fields=["idempotency_key"],
            )

        return PolicyDecision(
            status="allow",
            reason="风险提醒具备幂等键，可自动发送。",
            tool_name=tool.internal_name,
            idempotency_key=idempotency_key,
            patched_arguments=arguments,
        )

    def _resolve_idempotency_key(
        self,
        context: WorkflowContext,
        tool: AgentTool,
        arguments: dict[str, Any],
    ) -> str:
        """从工具参数或上下文中解析写操作幂等键。"""

        explicit_key = str(arguments.get("idempotency_key", "") or "").strip()
        if explicit_key:
            return explicit_key

        raw_decision = context.raw_context.get("decision", {})
        if isinstance(raw_decision, dict):
            base_key = str(raw_decision.get("idempotency_key", "") or "").strip()
            if base_key:
                day_bucket = time.strftime("%Y%m%d", time.localtime())
                return f"{base_key}:{tool.side_effect}:{day_bucket}"

        return ""

    def _is_duplicate_side_effect(self, storage: MeetFlowStorage, idempotency_key: str) -> bool:
        """检查写操作是否已处理过。"""

        return storage.is_idempotency_key_processed(idempotency_key)
