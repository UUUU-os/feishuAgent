from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/tool_registry_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuClient, create_feishu_tool_registry
from config import load_settings
from core import (
    AgentTool,
    AgentToolCall,
    ToolRegistry,
    configure_logging,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="演示 T2.10 Tool Registry：列出工具 schema 或执行本地 demo 工具。",
    )
    parser.add_argument(
        "--mode",
        choices=["list-feishu", "execute-demo"],
        default="list-feishu",
        help="list-feishu 只列出飞书工具 schema，不调用飞书 API；execute-demo 执行本地 echo 工具。",
    )
    parser.add_argument(
        "--tool",
        default="demo_echo",
        help="execute-demo 模式下要执行的工具名。",
    )
    parser.add_argument(
        "--message",
        default="Tool Registry 已经可以执行工具。",
        help="传给 demo_echo 工具的消息。",
    )
    return parser.parse_args()


def main() -> int:
    """运行 Tool Registry demo。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)

    if args.mode == "list-feishu":
        registry = create_feishu_tool_registry(
            client=FeishuClient(settings.feishu),
            default_chat_id=settings.feishu.default_chat_id,
        )
        print("已注册飞书工具：")
        for tool in registry.list_tools():
            print(f"- internal={tool.internal_name} llm={tool.llm_name} read_only={tool.read_only}")

        print("\n暴露给 LLM 的 tool definitions：")
        print(json.dumps([definition.to_dict() for definition in registry.get_definitions()], ensure_ascii=False, indent=2))
        return 0

    registry = _build_demo_registry()
    result = registry.execute(
        AgentToolCall(
            call_id="demo_call_001",
            tool_name=args.tool,
            arguments={"message": args.message},
        )
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _build_demo_registry() -> ToolRegistry:
    """构造一个不依赖外部 API 的本地 demo registry。"""

    registry = ToolRegistry()
    registry.register(
        AgentTool(
            internal_name="demo.echo",
            llm_name="demo_echo",
            description="回显传入的 message，用于验证 Tool Registry 执行链路。",
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "要回显的文本。"},
                },
                "required": ["message"],
            },
            handler=_demo_echo,
            read_only=True,
        )
    )
    return registry


def _demo_echo(message: str, **_: Any) -> dict[str, Any]:
    """本地 echo 工具，不产生任何副作用。"""

    return {
        "message": message,
        "length": len(message),
    }


if __name__ == "__main__":
    raise SystemExit(main())
