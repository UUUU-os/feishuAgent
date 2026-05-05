from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/feishu_event_sdk_server.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters.feishu_callback_payloads import callback_payload_from_sdk_object
from adapters.feishu_client import FeishuClient
from config import load_settings
from core.agent import create_meetflow_agent
from core.feishu_callback_dispatcher import FeishuCallbackDispatcher
from core.jobs import JobQueue, enqueue_agent_input_job
from core.logging import configure_logging, get_logger
from core.llm import DryRunLLMProvider
from core.observability import configure_structured_events, safe_error_message
from core.policy import AgentPolicy
from core.storage import MeetFlowStorage


def parse_args() -> argparse.Namespace:
    """解析飞书 SDK 长连接参数。"""

    parser = argparse.ArgumentParser(
        description="MeetFlow 飞书官方 SDK WebSocket 回调服务，统一承接 M3/M4 卡片动作。"
    )
    parser.add_argument("--log-level", default="", help="SDK 日志级别：debug/info/warn/error；不传使用配置。")
    parser.add_argument("--dry-run", action="store_true", help="只打印卡片回调并返回 toast，不执行业务写入。")
    parser.add_argument("--execute-agent", action="store_true", help="M3 刷新等动作生成 AgentInput 后异步执行 Agent。")
    parser.add_argument("--enqueue-agent", action="store_true", help="M3 刷新等动作生成 AgentInput 后写入 workflow_jobs，由 worker 执行。")
    parser.add_argument("--allow-write", action="store_true", help="允许后台 Agent 执行写工具。")
    parser.add_argument("--job-queue", default="workflow", help="AgentInput 入队队列名，默认 workflow。")
    parser.add_argument("--job-priority", type=int, default=100, help="入队优先级，数值越小越先执行。")
    parser.add_argument("--job-max-attempts", type=int, default=0, help="入队最大尝试次数；不传使用配置 jobs.max_attempts。")
    parser.add_argument(
        "--agent-provider",
        choices=["configured", "dry-run"],
        default="dry-run",
        help="后台 Agent 使用的模型 provider；默认 dry-run 方便联调。",
    )
    return parser.parse_args()


def main() -> int:
    """启动飞书 SDK WebSocket 长连接。"""

    args = parse_args()
    try:
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger,
            P2CardActionTriggerResponse,
        )
    except ImportError:
        print("缺少飞书 Python SDK：lark-oapi")
        print("请先运行：python3 scripts/setup_lark_oapi_venv.py")
        return 2

    settings = load_settings()
    configure_logging(settings.logging)
    configure_structured_events(settings.observability)
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(settings.feishu)
    dispatcher = FeishuCallbackDispatcher(
        settings=settings,
        storage=storage,
        feishu_client=client,
        policy=AgentPolicy(),
    )
    job_queue = JobQueue(settings.storage) if args.enqueue_agent else None
    logger = get_logger("meetflow.feishu_event_sdk_server")

    if not settings.feishu.app_id or not settings.feishu.app_secret:
        raise SystemExit("缺少 feishu.app_id 或 feishu.app_secret，无法启动飞书 SDK 长连接。")

    def do_card_action_trigger(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        """处理 card.action.trigger，并复用统一 dispatcher。"""

        payload = callback_payload_from_sdk_object(lark, data)
        logger.info("收到 SDK card.action.trigger keys=%s dry_run=%s", sorted(payload.keys()), args.dry_run)
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return P2CardActionTriggerResponse(
                {"toast": {"type": "info", "content": "MeetFlow dry-run：已收到按钮回调。"}}
            )
        result = dispatcher.dispatch_sdk_card_action(payload)
        if args.enqueue_agent and result.agent_input is not None and job_queue is not None:
            job = enqueue_agent_input_job(
                job_queue,
                agent_input=result.agent_input,
                queue_name=args.job_queue,
                allow_write=args.allow_write,
                agent_provider=args.agent_provider,
                priority=args.job_priority,
                max_attempts=args.job_max_attempts or settings.jobs.max_attempts,
            )
            logger.info("SDK 回调已入队后台 Agent job_id=%s event_type=%s", job.job_id, result.agent_input.event_type)
        elif args.execute_agent and result.agent_input is not None:
            thread = threading.Thread(
                target=run_agent_in_background,
                args=(result.agent_input, args.allow_write, args.agent_provider),
                daemon=True,
            )
            thread.start()
        return P2CardActionTriggerResponse(result.body)

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(do_card_action_trigger)
        .build()
    )

    kwargs: dict[str, Any] = {"event_handler": event_handler}
    log_level = resolve_lark_log_level(lark, args.log_level or getattr(settings.feishu, "event_sdk_log_level", ""))
    if log_level is not None:
        kwargs["log_level"] = log_level
    ws_client = lark.ws.Client(settings.feishu.app_id, settings.feishu.app_secret, **kwargs)
    print("MeetFlow 飞书 SDK 长连接回调服务已启动，等待 card.action.trigger。")
    print("请确保飞书开放平台 > 事件与回调 > 回调配置 已选择“使用长连接接收回调”。")
    ws_client.start()
    return 0


def run_agent_in_background(agent_input: Any, allow_write: bool, agent_provider: str) -> None:
    """异步执行 Agent，避免阻塞飞书 SDK 回调响应。"""

    logger = get_logger("meetflow.feishu_event_sdk_server")
    try:
        settings = load_settings()
        llm_provider = DryRunLLMProvider() if agent_provider == "dry-run" else None
        agent = create_meetflow_agent(settings, llm_provider=llm_provider)
        agent.run(agent_input, allow_write=allow_write)
    except Exception as error:  # noqa: BLE001 - 后台任务失败需要落日志而不是吞掉。
        logger.exception("SDK 回调触发的后台 Agent 执行失败：%s", safe_error_message(error))


def resolve_lark_log_level(lark: Any, value: str) -> Any:
    """把命令行日志级别转换为 SDK 常量。"""

    normalized = value.strip().lower()
    if not normalized:
        return None
    log_level_enum = getattr(lark, "LogLevel", None)
    if log_level_enum is None:
        return None
    member_name_mapping = {
        "debug": "DEBUG",
        "info": "INFO",
        "warn": "WARNING",
        "warning": "WARNING",
        "error": "ERROR",
        "critical": "CRITICAL",
    }
    member_name = member_name_mapping.get(normalized)
    if not member_name:
        return None
    return getattr(log_level_enum, member_name, None)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nMeetFlow 飞书 SDK 长连接回调服务已停止。")
        raise SystemExit(130)
