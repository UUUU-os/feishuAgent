from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from config import LLMSettings
from core.logging import get_logger
from core.models import AgentMessage, AgentToolCall, BaseModel


TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class LLMConfigError(RuntimeError):
    """模型配置错误。

    例如缺少 `api_key`、`api_base`，或者 provider 类型暂不支持。
    """


class LLMAPIError(RuntimeError):
    """模型接口调用失败。

    这里统一包装 HTTP 错误、网络错误和响应解析错误，
    让上层 Agent Loop 可以用同一种异常处理模型调用失败。
    """


@dataclass(slots=True)
class GenerationSettings(BaseModel):
    """单次模型生成参数。

    默认值来自 `config/settings.*.json`，调用时也可以临时覆盖。
    """

    model: str
    temperature: float = 0.2
    max_tokens: int = 4000
    reasoning_effort: str = ""
    timeout_seconds: int = 60


@dataclass(slots=True)
class ToolDefinition(BaseModel):
    """提供给 LLM 的工具定义。

    当前按照 OpenAI-compatible tool calling 格式组织，
    后续 Tool Registry 可以直接生成这个结构。
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_openai_tool(self) -> dict[str, Any]:
        """转换为 OpenAI-compatible 的工具 schema。"""

        self.validate_name()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }

    def validate_name(self) -> None:
        """校验工具名是否符合 OpenAI-compatible / DeepSeek 的函数命名规则。"""

        if TOOL_NAME_PATTERN.match(self.name):
            return
        raise LLMConfigError(
            "LLM 工具名不合法："
            f"{self.name}。工具名只能包含字母、数字、下划线和连字符，"
            "例如 calendar_list_events，不能使用 calendar.list_events。"
        )


@dataclass(slots=True)
class LLMResponse(BaseModel):
    """模型响应的内部统一结构。

    Agent Loop 只关心：
    - 模型最终回复内容
    - 模型是否要求调用工具
    - 本次停止原因
    - 原始响应，方便排查兼容性问题
    """

    content: str = ""
    tool_calls: list[AgentToolCall] = field(default_factory=list)
    finish_reason: str = ""
    model: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def should_execute_tools(self) -> bool:
        """判断 Agent Loop 是否需要进入工具执行阶段。"""

        return bool(self.tool_calls)


class LLMProvider:
    """LLM Provider 抽象基类。

    后续如果要支持其他厂商，只需要新增 provider 子类，
    不要让业务工作流直接写 HTTP 请求。
    """

    def chat(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition] | None = None,
        settings: GenerationSettings | None = None,
    ) -> LLMResponse:
        """执行一次模型对话。"""

        raise NotImplementedError


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI-compatible Chat Completions Provider。

    兼容形如 `/v1/chat/completions` 的接口，
    便于接入 OpenAI、兼容网关或本地大模型服务。
    """

    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings
        self.logger = get_logger("meetflow.llm")

    def chat(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition] | None = None,
        settings: GenerationSettings | None = None,
    ) -> LLMResponse:
        """调用模型，并把响应转换成内部统一结构。"""

        generation = settings or settings_from_config(self.settings)
        self._validate_config()

        payload: dict[str, Any] = {
            "model": generation.model,
            "messages": [_agent_message_to_openai(message) for message in messages],
            "temperature": generation.temperature,
            "max_tokens": generation.max_tokens,
        }

        # reasoning_effort 不是所有模型都支持，只有配置了才传入。
        if generation.reasoning_effort:
            payload["reasoning_effort"] = generation.reasoning_effort

        if tools:
            payload["tools"] = [tool.to_openai_tool() for tool in tools]
            payload["tool_choice"] = "auto"

        endpoint = _join_url(self.settings.api_base, "chat/completions")
        self.logger.info("准备调用 LLM provider=openai-compatible model=%s", generation.model)
        raw_payload = self._post_json(
            endpoint=endpoint,
            payload=payload,
            timeout_seconds=generation.timeout_seconds,
        )
        return _parse_openai_response(raw_payload)

    def _validate_config(self) -> None:
        """检查调用模型所需的基础配置。"""

        if not self.settings.api_base:
            raise LLMConfigError("LLM api_base 为空，请在配置或环境变量中设置 MEETFLOW_LLM_API_BASE")

        if not self.settings.api_key or self.settings.api_key == "replace-with-env-or-local-file":
            raise LLMConfigError("LLM api_key 未配置，请设置 MEETFLOW_LLM_API_KEY 或 settings.local.json")

    def _post_json(
        self,
        endpoint: str,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """发送 JSON POST 请求，并解析 JSON 响应。"""

        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise LLMAPIError(
                f"LLM HTTP 错误 status={error.code} endpoint={endpoint} body={error_body}"
            ) from error
        except urllib.error.URLError as error:
            raise LLMAPIError(f"LLM 网络错误 endpoint={endpoint} error={error}") from error

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:
            raise LLMAPIError(f"LLM 响应不是合法 JSON endpoint={endpoint} body={body[:500]}") from error

        if not isinstance(parsed, dict):
            raise LLMAPIError(f"LLM 响应类型异常 endpoint={endpoint} type={type(parsed).__name__}")

        return parsed


class DryRunLLMProvider(LLMProvider):
    """本地 dry-run Provider。

    这个 provider 不访问网络，主要用于：
    - 没有 API Key 时验证 Agent 数据流
    - 本地演示 tool calling 解析
    - 后续写单元测试
    """

    def __init__(self, model: str = "dry-run-model") -> None:
        self.model = model

    def chat(
        self,
        messages: list[AgentMessage],
        tools: list[ToolDefinition] | None = None,
        settings: GenerationSettings | None = None,
    ) -> LLMResponse:
        """返回一个可预测的本地响应。"""

        last_tool_message = _find_last_message_content(messages, role="tool")
        if last_tool_message:
            return LLMResponse(
                content=f"dry-run 最终回复：我已经读取工具结果：{last_tool_message}",
                finish_reason="stop",
                model=self.model,
                raw_payload={"provider": "dry-run", "mode": "final_after_tool"},
            )

        if tools:
            tool = tools[0]
            return LLMResponse(
                content="",
                finish_reason="tool_calls",
                model=self.model,
                tool_calls=[
                    AgentToolCall(
                        call_id=f"dry_run_call_{int(time.time())}",
                        tool_name=tool.name,
                        arguments={},
                        raw_payload={"provider": "dry-run"},
                    )
                ],
                raw_payload={"provider": "dry-run", "mode": "tool_call"},
            )

        last_user_message = _find_last_message_content(messages, role="user")
        return LLMResponse(
            content=f"dry-run 回复：已收到输入：{last_user_message}",
            finish_reason="stop",
            model=self.model,
            raw_payload={"provider": "dry-run", "mode": "text"},
        )


def create_llm_provider(settings: LLMSettings) -> LLMProvider:
    """根据配置创建 LLM Provider。"""

    provider = settings.provider.strip().lower()
    if provider in {"openai-compatible", "openai_compatible", "openai"}:
        return OpenAICompatibleProvider(settings)
    if provider in {"dry-run", "dry_run", "mock"}:
        return DryRunLLMProvider(model=settings.model or "dry-run-model")
    raise LLMConfigError(f"暂不支持的 LLM provider: {settings.provider}")


def settings_from_config(settings: LLMSettings) -> GenerationSettings:
    """从配置对象转换出单次生成参数。"""

    return GenerationSettings(
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        reasoning_effort=settings.reasoning_effort,
    )


def _agent_message_to_openai(message: AgentMessage) -> dict[str, Any]:
    """把内部 AgentMessage 转换成 OpenAI-compatible 消息。"""

    data: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }
    if message.name:
        data["name"] = message.name
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        data["tool_calls"] = [_agent_tool_call_to_openai(tool_call) for tool_call in message.tool_calls]
    return data


def _agent_tool_call_to_openai(tool_call: AgentToolCall) -> dict[str, Any]:
    """把内部工具调用转换成 OpenAI-compatible 工具调用。"""

    return {
        "id": tool_call.call_id,
        "type": "function",
        "function": {
            "name": tool_call.tool_name,
            "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
        },
    }


def _parse_openai_response(payload: dict[str, Any]) -> LLMResponse:
    """解析 OpenAI-compatible Chat Completions 响应。"""

    choices = payload.get("choices") or []
    if not choices:
        raise LLMAPIError(f"LLM 响应缺少 choices: {payload}")

    first_choice = choices[0]
    message = first_choice.get("message") or {}
    raw_tool_calls = message.get("tool_calls") or []

    return LLMResponse(
        content=message.get("content") or "",
        tool_calls=[_parse_openai_tool_call(item) for item in raw_tool_calls],
        finish_reason=first_choice.get("finish_reason") or "",
        model=payload.get("model") or "",
        raw_payload=payload,
        usage=payload.get("usage") or {},
    )


def _parse_openai_tool_call(item: dict[str, Any]) -> AgentToolCall:
    """解析单个 OpenAI-compatible tool call。"""

    function = item.get("function") or {}
    raw_arguments = function.get("arguments") or "{}"
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
    except (TypeError, ValueError):
        # 参数解析失败时不直接丢弃，保留原始值，后续 Tool Registry 可以给出更明确错误。
        arguments = {"_raw_arguments": raw_arguments}

    return AgentToolCall(
        call_id=item.get("id") or "",
        tool_name=function.get("name") or "",
        arguments=arguments,
        raw_payload=item,
    )


def _join_url(base_url: str, path: str) -> str:
    """拼接 API base 和相对路径，避免多斜杠或漏斜杠。"""

    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _find_last_message_content(messages: list[AgentMessage], role: str) -> str:
    """读取最后一条指定角色消息内容。"""

    for message in reversed(messages):
        if message.role == role:
            return message.content
    return ""
