from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/llm_provider_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import (
    AgentMessage,
    GenerationSettings,
    ToolDefinition,
    configure_logging,
    create_llm_provider,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="演示 T2.9 LLMProvider：普通对话与 tool calling 协议解析。",
    )
    parser.add_argument(
        "--mode",
        choices=["text", "tool"],
        default="tool",
        help="text 表示普通回复，tool 表示让 provider 返回或解析工具调用。",
    )
    parser.add_argument(
        "--provider",
        choices=["dry-run", "configured"],
        default="dry-run",
        help="dry-run 不访问网络；configured 使用 settings 中配置的真实 LLM。",
    )
    parser.add_argument(
        "--prompt",
        default="请根据会议上下文判断下一步应该调用什么工具。",
        help="传给模型的用户输入。",
    )
    return parser.parse_args()


def main() -> int:
    """运行 LLMProvider demo。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)

    # dry-run 模式会临时覆盖 provider，方便没有 API Key 时也能验证协议。
    if args.provider == "dry-run":
        settings.llm.provider = "dry-run"
        settings.llm.model = "dry-run-model"

    provider = create_llm_provider(settings.llm)
    messages = [
        AgentMessage(
            role="system",
            content="你是 MeetFlow 的垂直会议 Agent，只能通过工具读取证据。",
        ),
        AgentMessage(role="user", content=args.prompt),
    ]

    tools: list[ToolDefinition] | None = None
    if args.mode == "tool":
        tools = [
            ToolDefinition(
                name="docs_fetch_resource",
                description="读取一篇飞书文档并返回 Resource。",
                parameters={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "飞书文档 token 或 document_id。",
                        }
                    },
                    "required": ["document_id"],
                },
            )
        ]

    response = provider.chat(
        messages=messages,
        tools=tools,
        settings=GenerationSettings(
            model=settings.llm.model,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            reasoning_effort=settings.llm.reasoning_effort,
            timeout_seconds=60,
        ),
    )

    print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))
    if response.should_execute_tools:
        print("\n模型请求调用工具，后续 T2.10 会由 Tool Registry 负责执行。")
    else:
        print("\n模型返回最终文本，后续 Agent Loop 可以直接进入结果封装。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
