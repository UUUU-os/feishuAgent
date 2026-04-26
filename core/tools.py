from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, is_dataclass
from typing import Any

from core.llm import TOOL_NAME_PATTERN, ToolDefinition
from core.logging import get_logger, get_trace_id
from core.models import AgentToolCall, AgentToolResult, BaseModel


class ToolRegistryError(RuntimeError):
    """工具注册与执行阶段的通用错误。"""


class ToolNotFoundError(ToolRegistryError):
    """当 LLM 请求了未注册工具时抛出。"""


class ToolParameterError(ToolRegistryError):
    """工具参数不合法时抛出。"""


ToolHandler = Callable[..., Any]


@dataclass(slots=True)
class AgentTool:
    """Agent 可调用工具定义。

    `internal_name` 是系统内部稳定名称，例如 `calendar.list_events`。
    `llm_name` 是暴露给模型的函数名，例如 `calendar_list_events`。
    二者分开后，既能保留业务可读的命名层级，又能兼容 DeepSeek 等模型的函数名限制。
    """

    internal_name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    llm_name: str = ""
    read_only: bool = True
    side_effect: str = "none"
    timeout_seconds: int = 60
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 如果调用方没有显式提供 LLM 名称，就从内部名称自动转换。
        if not self.llm_name:
            self.llm_name = make_llm_tool_name(self.internal_name)
        validate_llm_tool_name(self.llm_name)

    def to_definition(self) -> ToolDefinition:
        """转换成 LLMProvider 可直接使用的工具定义。"""

        return ToolDefinition(
            name=self.llm_name,
            description=self.description,
            parameters=self.parameters,
        )

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        """根据 JSON Schema 的 required 字段做最小参数校验。

        完整 JSON Schema 校验后续可以引入专门库；当前先做首版最关键的必填字段校验，
        避免 LLM 漏传核心参数时直接进入飞书 API。
        """

        if not isinstance(arguments, dict):
            raise ToolParameterError(f"工具 {self.internal_name} 参数必须是对象")

        required_fields = self.parameters.get("required", [])
        if not isinstance(required_fields, list):
            return

        missing_fields = [
            field_name
            for field_name in required_fields
            if field_name not in arguments or arguments.get(field_name) is None or arguments.get(field_name) == ""
        ]
        if missing_fields:
            raise ToolParameterError(
                f"工具 {self.internal_name} 缺少必填参数：{', '.join(str(item) for item in missing_fields)}"
            )

    def execute(self, arguments: dict[str, Any]) -> Any:
        """执行工具处理函数。"""

        self.validate_arguments(arguments)
        return self.handler(**arguments)


class ToolRegistry:
    """Agent 工具注册器。

    负责三件事：
    - 注册系统工具
    - 向 LLM 暴露工具 schema
    - 根据 LLM 返回的 `AgentToolCall` 执行真实工具
    """

    def __init__(self) -> None:
        self.logger = get_logger("meetflow.tool_registry")
        self._tools_by_internal_name: dict[str, AgentTool] = {}
        self._tools_by_llm_name: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        """注册一个工具。"""

        if tool.internal_name in self._tools_by_internal_name:
            raise ToolRegistryError(f"工具内部名称重复：{tool.internal_name}")
        if tool.llm_name in self._tools_by_llm_name:
            raise ToolRegistryError(f"工具 LLM 名称重复：{tool.llm_name}")

        self._tools_by_internal_name[tool.internal_name] = tool
        self._tools_by_llm_name[tool.llm_name] = tool

    def get(self, name: str) -> AgentTool:
        """按内部名称或 LLM 名称读取工具。"""

        tool = self._tools_by_internal_name.get(name) or self._tools_by_llm_name.get(name)
        if tool is None:
            raise ToolNotFoundError(f"未注册工具：{name}")
        return tool

    def list_tools(self) -> list[AgentTool]:
        """返回当前所有工具。"""

        return list(self._tools_by_internal_name.values())

    def get_definitions(self, names: list[str] | None = None) -> list[ToolDefinition]:
        """返回可交给 LLM 的工具定义列表。

        `names` 可以传内部名称或 LLM 名称；不传则返回全部工具。
        """

        tools = [self.get(name) for name in names] if names else self.list_tools()
        return [tool.to_definition() for tool in tools]

    def execute(self, tool_call: AgentToolCall) -> AgentToolResult:
        """执行 LLM 返回的一次工具调用，并统一包装结果。"""

        started_at = int(time.time())
        trace_id = get_trace_id()

        try:
            tool = self.get(tool_call.tool_name)
            self.logger.info(
                "开始执行 Agent 工具 trace_id=%s tool=%s llm_name=%s call_id=%s",
                trace_id,
                tool.internal_name,
                tool.llm_name,
                tool_call.call_id,
            )
            raw_result = tool.execute(tool_call.arguments)
            data = serialize_tool_result(raw_result)
            return AgentToolResult(
                call_id=tool_call.call_id,
                tool_name=tool.internal_name,
                status="success",
                content=build_tool_result_content(tool.internal_name, data),
                data=data,
                started_at=started_at,
                finished_at=int(time.time()),
            )
        except Exception as error:  # noqa: BLE001 - 工具层需要把所有异常统一包装给 Agent Loop。
            tool_name = tool_call.tool_name
            self.logger.warning(
                "Agent 工具执行失败 trace_id=%s tool=%s call_id=%s error=%s",
                trace_id,
                tool_name,
                tool_call.call_id,
                error,
            )
            return AgentToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_name,
                status="error",
                content=f"工具 {tool_name} 执行失败：{error}",
                error_message=str(error),
                started_at=started_at,
                finished_at=int(time.time()),
            )


def make_llm_tool_name(internal_name: str) -> str:
    """把内部工具名转换成 LLM 兼容工具名。"""

    llm_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", internal_name).strip("_")
    if not llm_name:
        raise ToolRegistryError(f"无法从内部工具名生成 LLM 工具名：{internal_name}")
    return llm_name


def validate_llm_tool_name(tool_name: str) -> None:
    """校验 LLM 工具名是否兼容 OpenAI-compatible / DeepSeek。"""

    if TOOL_NAME_PATTERN.match(tool_name):
        return
    raise ToolRegistryError(
        f"LLM 工具名不合法：{tool_name}。只能包含字母、数字、下划线和连字符。"
    )


def serialize_tool_result(value: Any) -> dict[str, Any]:
    """将工具返回值转换成可 JSON 序列化的字典。"""

    if isinstance(value, BaseModel):
        return value.to_dict()
    if isinstance(value, list):
        return {"items": [serialize_tool_item(item) for item in value], "count": len(value)}
    if isinstance(value, dict):
        return {str(key): serialize_tool_item(item) for key, item in value.items()}
    return {"value": serialize_tool_item(value)}


def serialize_tool_item(value: Any) -> Any:
    """递归序列化工具结果中的单个值。"""

    if isinstance(value, BaseModel):
        return value.to_dict()
    if is_dataclass(value):
        return {key: serialize_tool_item(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, list):
        return [serialize_tool_item(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize_tool_item(item) for key, item in value.items()}
    return value


def build_tool_result_content(tool_name: str, data: dict[str, Any]) -> str:
    """构造喂回 LLM 的工具结果内容。

    注意：这里不能只返回“共 N 条记录”。
    LLM 第二轮推理只能看到 tool message 的 content，
    如果不把结构化数据放进去，模型就无法总结会议标题、时间、参与人等细节。
    """

    detail_json = json.dumps(data, ensure_ascii=False, indent=2)
    if "count" in data:
        return (
            f"工具 {tool_name} 执行成功，返回 {data['count']} 条记录。\n"
            "结构化数据 JSON：\n"
            f"{detail_json}"
        )
    if "title" in data:
        return (
            f"工具 {tool_name} 执行成功，返回资源：{data['title']}。\n"
            "结构化数据 JSON：\n"
            f"{detail_json}"
        )
    return (
        f"工具 {tool_name} 执行成功。\n"
        "结构化数据 JSON：\n"
        f"{detail_json}"
    )
