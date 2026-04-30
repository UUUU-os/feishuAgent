from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# 允许直接通过 `python3 scripts/meetflow_agent_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLMSettings, load_settings
from core import (
    AgentMessage,
    AgentToolCall,
    GenerationSettings,
    LLMConfigError,
    LLMProvider,
    LLMResponse,
    build_agent_input,
    configure_logging,
    create_llm_provider,
)
from core.agent import create_meetflow_agent


LOCAL_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.local.json"


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="真实测试 MeetFlowAgent：LLM Agent Loop + 飞书工具 + 本地存储。",
    )
    parser.add_argument(
        "--event-type",
        default="message.command",
        help="触发事件类型。推荐先用 message.command 做人工测试。",
    )
    parser.add_argument(
        "--workflow-type",
        default="manual_qa",
        help="message.command 下的目标工作流，可选 manual_qa / pre_meeting_brief / risk_scan 等。",
    )
    parser.add_argument(
        "--prompt",
        default="请调用日历工具查询我今天的会议安排，并用简洁中文总结。",
        help="本次 Agent 的工作目标，会进入 LLM 上下文。",
    )
    parser.add_argument(
        "--tool",
        action="append",
        default=[],
        help="本次显式开放的工具，可传多次。默认只开放 calendar.list_events。",
    )
    parser.add_argument("--calendar-id", default="primary", help="日历 ID，主日历可传 primary。")
    parser.add_argument("--start-time", default="", help="Unix 秒级开始时间；不传则取今天 00:00。")
    parser.add_argument("--end-time", default="", help="Unix 秒级结束时间；不传则取明天 00:00。")
    parser.add_argument("--project-id", default="meetflow", help="项目 ID，用于读取项目记忆。")
    parser.add_argument("--minute-token", default="", help="妙记 token，用于测试会后场景。")
    parser.add_argument("--document", default="", help="文档 URL 或 token，用于测试文档读取。")
    parser.add_argument("--task-id", default="", help="任务 ID，用于测试风险巡检上下文。")
    parser.add_argument(
        "--llm-provider",
        default="scripted_calendar",
        help="LLM 配置来源。scripted_calendar 会直接驱动日历工具；deepseek 使用真实模型。",
    )
    parser.add_argument("--model", default="", help="临时覆盖模型名。")
    parser.add_argument("--api-base", default="", help="临时覆盖 OpenAI-compatible API base。")
    parser.add_argument(
        "--api-key-env",
        default="",
        help="从指定环境变量读取 API Key，例如 DEEPSEEK_API_KEY。",
    )
    parser.add_argument("--temperature", type=float, default=None, help="临时覆盖采样温度。")
    parser.add_argument("--max-tokens", type=int, default=None, help="临时覆盖最大输出 token 数。")
    parser.add_argument("--max-iterations", type=int, default=4, help="Agent Loop 最大轮数。")
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help="允许 LLM 调用写工具，例如发消息、建任务。默认不开放写工具。",
    )
    parser.add_argument(
        "--enable-idempotency",
        action="store_true",
        help="启用幂等键去重。真实事件订阅建议开启，本地反复测试时可不传。",
    )
    parser.add_argument(
        "--show-full",
        action="store_true",
        help="打印完整 AgentRunResult。默认只打印摘要、工具结果和最终回答。",
    )
    return parser.parse_args()


def main() -> int:
    """运行真实 Agent 测试。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)

    try:
        llm_settings = build_llm_settings(args, settings.llm)
        provider = build_llm_provider(args, llm_settings)
    except LLMConfigError as error:
        print(f"\nLLM 配置错误：{error}")
        print("建议：先用 --llm-provider scripted_calendar 验证飞书链路；真实模型请设置 DEEPSEEK_API_KEY。")
        return 2
    agent = create_meetflow_agent(
        settings=settings,
        llm_provider=provider,
        enable_idempotency=args.enable_idempotency,
        user_token_callback=lambda bundle: save_token_bundle(settings, bundle),
    )
    agent.loop.max_iterations = args.max_iterations

    payload = build_payload(args, settings.app.timezone)
    agent_input = build_agent_input(
        event_type=args.event_type,
        payload=payload,
        source="meetflow_agent_live_test",
    )
    result = agent.run(
        agent_input=agent_input,
        workflow_goal=build_workflow_goal(args.prompt, payload),
        generation_settings=GenerationSettings(
            model=llm_settings.model,
            temperature=llm_settings.temperature,
            max_tokens=llm_settings.max_tokens,
            reasoning_effort=llm_settings.reasoning_effort,
            timeout_seconds=90,
        ),
        allow_write=args.allow_write,
    )

    print_result(result.to_dict(), show_full=args.show_full)
    return 0 if result.status in {"success", "max_iterations"} else 1


def build_payload(args: argparse.Namespace, timezone: str) -> dict[str, object]:
    """构造 AgentInput.payload。"""

    start_time, end_time = resolve_time_window(args, timezone)
    required_tools = enrich_required_tools(args.tool or ["calendar.list_events"])

    payload: dict[str, object] = {
        "workflow_type": args.workflow_type,
        "required_tools": required_tools,
        "calendar_id": args.calendar_id,
        "start_time": start_time,
        "end_time": end_time,
        "project_id": args.project_id,
        "idempotency_key": f"{args.workflow_type}:{args.calendar_id}:{start_time}:{end_time}",
    }
    if args.minute_token:
        payload["minute_token"] = args.minute_token
        payload["minute"] = args.minute_token
    if args.document:
        payload["document"] = args.document
    if args.task_id:
        payload["task_id"] = args.task_id
    return payload


def enrich_required_tools(required_tools: list[str]) -> list[str]:
    """根据业务工具自动补充必要的辅助工具。

    例如用户说“负责人为我”时，创建任务前需要先把“我”解析成 open_id。
    因此只要开放 `tasks.create_task`，就自动补充通讯录只读工具。
    """

    final_tools = list(required_tools)
    if "tasks.create_task" in final_tools:
        # 先放当前用户工具，便于“负责人为我”的场景优先成功。
        for helper_tool in reversed(("contact.get_current_user", "contact.search_user")):
            if helper_tool not in final_tools:
                final_tools.insert(0, helper_tool)
    return final_tools


def resolve_time_window(args: argparse.Namespace, timezone: str) -> tuple[str, str]:
    """解析查询时间窗口，默认取本地今天。"""

    if args.start_time and args.end_time:
        return args.start_time, args.end_time

    tz = ZoneInfo(timezone or "Asia/Shanghai")
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    return str(int(today.timestamp())), str(int(tomorrow.timestamp()))


def build_workflow_goal(prompt: str, payload: dict[str, object]) -> str:
    """把用户目标和关键工具参数合成更明确的 Agent 目标。"""

    return (
        f"{prompt}\n\n"
        "人员解析规则：\n"
        "- 如果负责人是“我/本人/自己”，必须先调用 contact_get_current_user 获取当前用户 open_id，再把 open_id 放入 assignee_ids。\n"
        "- 如果负责人是具体姓名，必须先调用 contact_search_user 搜索用户，选择最匹配候选人的 open_id，再把 open_id 放入 assignee_ids。\n"
        "- 不要把自然语言姓名直接填入 assignee_ids。\n\n"
        "如果需要查询日历，请优先调用 calendar_list_events，参数如下：\n"
        f"- calendar_id: {payload.get('calendar_id', 'primary')}\n"
        f"- start_time: {payload.get('start_time', '')}\n"
        f"- end_time: {payload.get('end_time', '')}\n"
        "除非用户明确要求发送消息或创建任务，否则不要调用写工具。"
    )


def build_llm_settings(args: argparse.Namespace, fallback: LLMSettings) -> LLMSettings:
    """读取本次测试使用的 LLM 配置。"""

    provider_name = args.llm_provider.strip()
    if provider_name == "scripted_calendar":
        return LLMSettings(
            provider="scripted-calendar",
            model="scripted-calendar",
            api_base="",
            api_key="",
            temperature=0.0,
            max_tokens=1000,
            reasoning_effort="",
        )

    if provider_name in {"settings", "default"}:
        return override_llm_settings(args, fallback)

    provider_config = load_provider_config(provider_name)
    api_key_env = args.api_key_env or str(provider_config.get("api_key_env", ""))
    api_key = os.getenv(api_key_env, "") if api_key_env else ""
    api_key = api_key or str(provider_config.get("api_key", ""))

    settings = LLMSettings(
        provider=str(provider_config.get("provider", "openai-compatible")),
        model=str(provider_config.get("model", "")),
        api_base=str(provider_config.get("api_base", "")),
        api_key=api_key,
        temperature=float(provider_config.get("temperature", 0.2) or 0.2),
        max_tokens=int(provider_config.get("max_tokens", 4000) or 4000),
        reasoning_effort=str(provider_config.get("reasoning_effort", "") or ""),
    )
    return override_llm_settings(args, settings)


def build_llm_provider(args: argparse.Namespace, settings: LLMSettings) -> LLMProvider:
    """创建本次测试使用的 LLM Provider。"""

    if args.llm_provider.strip() == "scripted_calendar":
        start_time, end_time = resolve_time_window(args, "Asia/Shanghai")
        return ScriptedCalendarProvider(
            calendar_id=args.calendar_id,
            start_time=start_time,
            end_time=end_time,
        )
    return create_llm_provider(settings)


class ScriptedCalendarProvider(LLMProvider):
    """用于真实飞书 API 冒烟测试的脚本化 Provider。

    它不是大模型，只负责稳定地产生一次 `calendar_list_events` 工具调用。
    价值是快速验证：
    - MeetFlowAgent 主入口是否串通
    - ToolRegistry 是否能执行飞书工具
    - FeishuClient 是否真的能读取日历
    """

    def __init__(self, calendar_id: str, start_time: str, end_time: str) -> None:
        self.calendar_id = calendar_id
        self.start_time = start_time
        self.end_time = end_time

    def chat(
        self,
        messages: list[AgentMessage],
        tools: list[object] | None = None,
        settings: GenerationSettings | None = None,
    ) -> LLMResponse:
        """模拟一轮工具调用，然后根据工具结果给出最终回复。"""

        for message in reversed(messages):
            if message.role == "tool":
                return LLMResponse(
                    content=f"scripted_calendar 最终回复：{message.content}",
                    finish_reason="stop",
                    model="scripted-calendar",
                )

        return LLMResponse(
            content="",
            finish_reason="tool_calls",
            model="scripted-calendar",
            tool_calls=[
                AgentToolCall(
                    call_id=f"scripted_calendar_{int(time.time())}",
                    tool_name="calendar_list_events",
                    arguments={
                        "calendar_id": self.calendar_id,
                        "start_time": self.start_time,
                        "end_time": self.end_time,
                        "identity": "user",
                    },
                    raw_payload={"provider": "scripted-calendar"},
                )
            ],
        )


def load_provider_config(provider_name: str) -> dict[str, object]:
    """从 llm_providers.local.json / example.json 读取指定厂商配置。"""

    local_path = PROJECT_ROOT / "config" / "llm_providers.local.json"
    example_path = PROJECT_ROOT / "config" / "llm_providers.example.json"
    config_path = local_path if local_path.exists() else example_path

    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    providers = data.get("providers", {})
    if not isinstance(providers, dict) or provider_name not in providers:
        raise LLMConfigError(f"找不到 LLM provider 配置：{provider_name}")

    provider_config = providers[provider_name]
    if not isinstance(provider_config, dict):
        raise LLMConfigError(f"LLM provider 配置格式错误：{provider_name}")
    return provider_config


def override_llm_settings(args: argparse.Namespace, settings: LLMSettings) -> LLMSettings:
    """用命令行参数临时覆盖 LLM 配置。"""

    if args.model:
        settings.model = args.model
    if args.api_base:
        settings.api_base = args.api_base
    if args.api_key_env:
        settings.api_key = os.getenv(args.api_key_env, settings.api_key)
    if args.temperature is not None:
        settings.temperature = args.temperature
    if args.max_tokens is not None:
        settings.max_tokens = args.max_tokens
    return settings


def print_result(result: dict[str, object], show_full: bool) -> None:
    """打印 Agent 测试结果。"""

    if show_full:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("\nMeetFlowAgent 执行完成")
    print(f"trace_id: {result.get('trace_id')}")
    print(f"workflow_type: {result.get('workflow_type')}")
    print(f"status: {result.get('status')}")
    print("\n最终回答：")
    print(result.get("final_answer") or result.get("summary") or "")

    loop_state = result.get("loop_state")
    if not isinstance(loop_state, dict):
        return

    tool_results = loop_state.get("tool_results") or []
    if not tool_results:
        print("\n本次没有工具调用。")
        return

    print("\n工具调用结果：")
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        print(f"- {item.get('tool_name')} status={item.get('status')} content={item.get('content')}")


def save_token_bundle(settings: object, bundle: object) -> None:
    """把自动刷新的用户 token 回写到本地配置。

    飞书 refresh_token 是一次性的；如果刷新后不保存新 refresh_token，
    下一次真实 API 调用就会拿旧 token 报 20064。
    """

    current = load_local_config()
    patch = {
        "feishu": {
            "redirect_uri": settings.feishu.redirect_uri,
            "user_oauth_scope": bundle.scope or settings.feishu.user_oauth_scope,
            "user_access_token": bundle.access_token,
            "user_access_token_expires_at": bundle.access_token_expires_at,
            "user_refresh_token": bundle.refresh_token,
            "user_refresh_token_expires_at": bundle.refresh_token_expires_at,
        }
    }
    merged = deep_merge(current, patch)
    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_CONFIG_PATH.open("w", encoding="utf-8") as file:
        json.dump(merged, file, ensure_ascii=False, indent=2)


def load_local_config() -> dict[str, object]:
    """读取 settings.local.json；不存在则返回空字典。"""

    if not LOCAL_CONFIG_PATH.exists():
        return {}
    with LOCAL_CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, dict) else {}


def deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    """递归合并配置字典。"""

    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


if __name__ == "__main__":
    raise SystemExit(main())
