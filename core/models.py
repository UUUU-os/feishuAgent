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
