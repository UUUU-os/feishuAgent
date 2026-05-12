from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class BaseModel:
    """所有公共数据模型的基础类。

    统一提供 `to_dict()`，方便后续：
    - 写入 SQLite / JSON / JSONL
    - 输出给日志与审计系统
    - 作为接口层和工作流层之间的中间对象
    """

    def to_dict(self) -> dict[str, Any]:
        """将 dataclass 模型递归转换为普通字典。"""

        return asdict(self)


@dataclass(slots=True)
class Event(BaseModel):
    """统一事件模型。

    用于描述系统收到的外部触发，如：
    - 会议即将开始
    - 妙记生成完成
    - 任务状态更新
    - 手动命令触发
    """

    event_id: str
    event_type: str
    event_time: str
    source: str
    actor: str
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str = "-"


@dataclass(slots=True)
class Resource(BaseModel):
    """统一资源模型。

    用于抽象飞书里的文档、妙记、任务、消息等对象，
    让召回、摘要、抽取逻辑都基于同一种数据结构处理。
    """

    resource_id: str
    resource_type: str
    title: str
    content: str
    source_url: str
    source_meta: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class EvidenceRef(BaseModel):
    """证据引用模型。

    每条结论或行动项都应该尽量带上证据引用，
    便于后续溯源和人工校验。
    """

    source_type: str
    source_id: str
    source_url: str
    snippet: str
    updated_at: str = ""


@dataclass(slots=True)
class CalendarAttendee(BaseModel):
    """日历参与人模型。

    当前优先保留会前场景最有价值的字段：
    - 显示名称
    - 参与人类型
    - RSVP 状态
    - 是否组织者
    """

    attendee_id: str = ""
    display_name: str = ""
    attendee_type: str = ""
    rsvp_status: str = ""
    is_optional: bool = False
    is_organizer: bool = False


@dataclass(slots=True)
class CalendarEvent(BaseModel):
    """统一的日历事件模型。

    这个模型主要服务于会前场景，统一承接：
    - 会议标题
    - 开始时间 / 结束时间
    - 会议描述
    - 参与人
    - 跳转链接
    """

    event_id: str
    summary: str
    description: str = ""
    start_time: str = ""
    end_time: str = ""
    timezone: str = ""
    organizer_name: str = ""
    organizer_id: str = ""
    status: str = ""
    app_link: str = ""
    attendees: list[CalendarAttendee] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CalendarInfo(BaseModel):
    """日历基础信息模型。

    用于承接“获取主日历”等接口的返回结果，
    方便后续解析出真实可用的 `calendar_id`。
    """

    calendar_id: str
    summary: str
    description: str = ""
    permissions: str = ""
    color: int = -1
    calendar_type: str = ""
    summary_alias: str = ""
    is_deleted: bool = False
    is_third_party: bool = False
    role: str = ""
    user_id: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActionItem(BaseModel):
    """会后抽取出的行动项模型。"""

    item_id: str
    title: str
    owner: str = ""
    due_date: str = ""
    priority: str = "medium"
    status: str = "todo"
    confidence: float = 0.0
    needs_confirm: bool = False
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MeetingSummary(BaseModel):
    """会议结构化总结模型。"""

    meeting_id: str
    project_id: str
    topic: str
    decisions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class RiskAlert(BaseModel):
    """风险提醒模型。"""

    risk_id: str
    task_id: str
    risk_type: str
    severity: str
    reason: str
    owner: str = ""
    due_date: str = ""
    suggestion: str = ""


@dataclass(slots=True)
class WorkflowResult(BaseModel):
    """工作流执行结果模型。

    这个模型用于把工作流最终产物统一保存到本地存储中，
    便于后续查历史、做评估和构建演示数据。
    """

    trace_id: str
    workflow_name: str
    status: str
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0


@dataclass(slots=True)
class AgentInput(BaseModel):
    """Agent 统一输入模型。

    这个模型承接所有触发来源：
    - 飞书事件回调
    - 定时任务
    - 本地命令行调试
    后续 `MeetFlowAgent` 只需要处理这一种输入结构，不需要关心原始触发器来自哪里。
    """

    trigger_type: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    actor: str = ""
    source: str = "manual"
    event_id: str = ""
    trace_id: str = "-"
    created_at: int = 0


@dataclass(slots=True)
class AgentDecision(BaseModel):
    """Agent 路由决策模型。

    `WorkflowRouter` 会根据 `AgentInput` 输出这个模型，
    告诉后续运行时：
    - 要跑哪个业务工作流
    - 为什么做这个决策
    - 本次允许 LLM 使用哪些工具
    - 如何做幂等去重
    """

    workflow_type: str
    confidence: float
    reason: str
    required_tools: list[str] = field(default_factory=list)
    idempotency_key: str = ""
    status: str = "ready"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowContext(BaseModel):
    """工作流上下文模型。

    它把飞书原始 payload 转换成业务可理解的上下文，
    避免 M3-M5 每个工作流都重复解析会议、妙记、任务和项目记忆。
    """

    workflow_type: str
    trace_id: str
    event: Event | None = None
    meeting_id: str = ""
    calendar_event_id: str = ""
    minute_token: str = ""
    task_id: str = ""
    project_id: str = ""
    participants: list[dict[str, Any]] = field(default_factory=list)
    related_resources: list[Resource] = field(default_factory=list)
    memory_snapshot: dict[str, Any] = field(default_factory=dict)
    raw_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentToolCall(BaseModel):
    """LLM 请求调用工具时的内部统一模型。

    不同模型服务返回的 tool call 字段可能不完全一致，
    后续 `LLMProvider` 会统一转换成这个结构，再交给 `ToolRegistry` 执行。
    """

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentToolResult(BaseModel):
    """工具执行结果模型。

    这个模型会作为 tool 消息喂回 LLM，
    所以需要同时保留：
    - 给模型看的简短内容
    - 给系统审计和回放用的结构化数据
    - 错误信息和证据引用
    """

    call_id: str
    tool_name: str
    status: str
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    started_at: int = 0
    finished_at: int = 0

    def is_success(self) -> bool:
        """判断工具是否执行成功，方便 Agent Loop 做分支处理。"""

        return self.status == "success"


@dataclass(slots=True)
class AgentMessage(BaseModel):
    """Agent Loop 中的一条消息。

    角色通常是：
    - system：系统提示词
    - user：触发事件或人工命令
    - assistant：LLM 的回复或工具调用请求
    - tool：工具执行结果
    """

    role: str
    content: str = ""
    name: str = ""
    tool_call_id: str = ""
    tool_calls: list[AgentToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentLoopState(BaseModel):
    """Agent Loop 运行状态模型。

    这个结构用于记录一次 LLM 多轮工具调用过程，
    后续可以落盘、审计、回放，也方便本地 demo 打印每一轮模型做了什么。
    """

    loop_id: str
    trace_id: str
    workflow_type: str
    iteration: int = 0
    max_iterations: int = 6
    status: str = "running"
    stop_reason: str = ""
    messages: list[AgentMessage] = field(default_factory=list)
    pending_tool_calls: list[AgentToolCall] = field(default_factory=list)
    tool_results: list[AgentToolResult] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def append_message(self, message: AgentMessage) -> None:
        """追加一条 loop 消息，避免调用方直接操作内部列表。"""

        self.messages.append(message)

    def append_tool_result(self, result: AgentToolResult) -> None:
        """追加工具执行结果，并自动生成对应的 tool 消息。"""

        self.tool_results.append(result)
        self.messages.append(
            AgentMessage(
                role="tool",
                content=result.content,
                tool_call_id=result.call_id,
                metadata={
                    "tool_name": result.tool_name,
                    "status": result.status,
                    "error_message": result.error_message,
                },
            )
        )


@dataclass(slots=True)
class AgentRunResult(BaseModel):
    """Agent 一次完整运行的结果模型。

    它比 `WorkflowResult` 更偏 Agent 运行时，
    会保存 LLM loop 状态、工具副作用、下一步建议等信息。
    真正落到存储层时，可以通过 `to_workflow_result()` 转换成现有工作流结果模型。
    """

    trace_id: str
    workflow_type: str
    status: str
    summary: str = ""
    final_answer: str = ""
    produced_resources: list[Resource] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    side_effects: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    loop_state: AgentLoopState | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0

    def to_workflow_result(self) -> WorkflowResult:
        """转换为现有 `WorkflowResult`，复用当前存储层。"""

        return WorkflowResult(
            trace_id=self.trace_id,
            workflow_name=self.workflow_type,
            status=self.status,
            summary=self.summary,
            payload={
                "final_answer": self.final_answer,
                "produced_resources": [item.to_dict() for item in self.produced_resources],
                "action_items": [item.to_dict() for item in self.action_items],
                "side_effects": self.side_effects,
                "next_actions": self.next_actions,
                "loop_state": self.loop_state.to_dict() if self.loop_state else None,
                "payload": self.payload,
            },
            created_at=self.created_at,
        )
