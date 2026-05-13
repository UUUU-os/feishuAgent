from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/deepseek_llm_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLMSettings, load_settings
from core import (
    AgentMessage,
    GenerationSettings,
    LLMAPIError,
    LLMConfigError,
    ToolDefinition,
    configure_logging,
    create_llm_provider,
    get_logger,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "真实调用当前项目 settings.local.json 中配置的 LLM。"
            "脚本名保留 deepseek 仅为历史兼容。"
        ),
    )
    parser.add_argument(
        "--api-base",
        default="",
        help="临时覆盖 settings.local.json 中的 llm.api_base；默认使用本地配置。",
    )
    parser.add_argument(
        "--model",
        default="",
        help="临时覆盖 settings.local.json 中的 llm.model；默认使用本地配置。",
    )
    parser.add_argument(
        "--prompt",
        default="请用一句话说明你已经成功接入 MeetFlow 的 LLMProvider。",
        help="用户输入。",
    )
    parser.add_argument(
        "--system",
        default="你是 MeetFlow 的模型连通性测试助手，请简洁回答。",
        help="系统提示词。",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="临时覆盖 settings.local.json 中的 llm.temperature。",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="临时覆盖 settings.local.json 中的 llm.max_tokens。",
    )
    parser.add_argument(
        "--mode",
        choices=["text", "tool"],
        default="text",
        help="text 测试普通回复；tool 测试模型是否返回 tool_calls。",
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="打印模型原始响应，便于排查兼容性问题。",
    )
    return parser.parse_args()


def _build_provider_settings(args: argparse.Namespace, fallback: LLMSettings) -> LLMSettings:
    """基于 settings.local.json 构造临时 LLMSettings，不修改本地配置文件。"""

    settings = LLMSettings(
        provider=fallback.provider,
        model=fallback.model,
        api_base=fallback.api_base,
        api_key=fallback.api_key,
        temperature=fallback.temperature,
        max_tokens=fallback.max_tokens,
        reasoning_effort="",
    )
    if args.model:
        settings.model = args.model
    if args.api_base:
        settings.api_base = args.api_base
    if args.temperature is not None:
        settings.temperature = args.temperature
    if args.max_tokens is not None:
        settings.max_tokens = args.max_tokens
    return settings


def _build_tools(mode: str) -> list[ToolDefinition] | None:
    """构造测试用工具定义。

    注意这里不会真正执行工具，只用于确认模型是否能返回 tool_calls。
    真正执行工具会在后续 T2.10 Tool Registry 中实现。
    """

    if mode != "tool":
        return None

    return [
        ToolDefinition(
            name="calendar_list_events",
            description="查询指定时间范围内的飞书日历事件。",
            parameters={
                "type": "object",
                "properties": {
                    "calendar_id": {
                        "type": "string",
                        "description": "飞书日历 ID，主日历可使用 primary。",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "查询开始时间，Unix 秒级时间戳。",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "查询结束时间，Unix 秒级时间戳。",
                    },
                },
                "required": ["calendar_id", "start_time", "end_time"],
            },
        )
    ]


def main() -> int:
    """执行 settings.local.json 中真实模型的连通性测试。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.llm.live_test")

    provider_settings = _build_provider_settings(args, settings.llm)
    provider = create_llm_provider(provider_settings)
    messages = [
        AgentMessage(role="system", content=args.system),
        AgentMessage(role="user", content=args.prompt),
    ]

    logger.info(
        "准备真实调用 settings.local LLM provider=%s model=%s api_base=%s mode=%s",
        provider_settings.provider,
        provider_settings.model,
        provider_settings.api_base,
        args.mode,
    )

    try:
        response = provider.chat(
            messages=messages,
            tools=_build_tools(args.mode),
            settings=GenerationSettings(
                model=provider_settings.model,
                temperature=provider_settings.temperature,
                max_tokens=provider_settings.max_tokens,
                timeout_seconds=60,
            ),
        )
    except (LLMConfigError, LLMAPIError) as error:
        logger.error("settings.local LLM 调用失败：%s", error)
        print(f"\nsettings.local LLM 调用失败：{error}")
        return 1

    print("\nsettings.local LLM 调用成功。")
    print(f"provider: {provider_settings.provider}")
    print(f"model: {response.model or provider_settings.model}")
    print(f"finish_reason: {response.finish_reason}")

    if response.content:
        print("\n模型回复：")
        print(response.content)

    if response.tool_calls:
        print("\n模型请求调用工具：")
        for tool_call in response.tool_calls:
            print(json.dumps(tool_call.to_dict(), ensure_ascii=False, indent=2))

    if response.usage:
        print("\nusage:")
        print(json.dumps(response.usage, ensure_ascii=False, indent=2))

    if args.show_raw:
        print("\n原始响应：")
        print(json.dumps(response.raw_payload, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
