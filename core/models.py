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
