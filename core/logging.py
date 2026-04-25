from __future__ import annotations

import contextvars
import logging
import sys
import uuid
from typing import Any

from config import LoggingSettings


# 使用 ContextVar 保存当前执行链路的 trace_id。
# 这样即使后续有多个工作流并行运行，每条链路也能带上自己的追踪编号。
TRACE_ID_CONTEXT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "meetflow_trace_id",
    default="-",
)


class TraceIdFilter(logging.Filter):
    """为每条日志记录注入 trace_id。

    这样日志 formatter 中就可以直接使用 %(trace_id)s，
    而不需要在每次 logger.info(...) 时手工传入。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # 如果业务代码没有显式传 trace_id，就自动从上下文里取。
        record.trace_id = getattr(record, "trace_id", get_trace_id())
        return True


def generate_trace_id() -> str:
    """生成新的 trace_id，用于标记一次完整工作流执行。"""

    return uuid.uuid4().hex[:12]


def bind_trace_id(trace_id: str | None = None) -> str:
    """将 trace_id 绑定到当前上下文。

    如果调用方没有传入 trace_id，就自动生成一个新的。
    返回值永远是当前最终生效的 trace_id，便于上层继续传递。
    """

    final_trace_id = trace_id or generate_trace_id()
    TRACE_ID_CONTEXT.set(final_trace_id)
    return final_trace_id


def get_trace_id() -> str:
    """获取当前上下文中的 trace_id。"""

    return TRACE_ID_CONTEXT.get()


def reset_trace_id() -> None:
    """将 trace_id 重置为默认值。

    这个函数常用于工作流结束后清理上下文，避免后续日志串号。
    """

    TRACE_ID_CONTEXT.set("-")


def configure_logging(settings: LoggingSettings) -> None:
    """初始化全局日志配置。

    当前实现以控制台输出为主，并统一注入 trace_id。
    后续如果需要文件日志或远程日志采集，也可以在这里继续扩展。
    """

    root_logger = logging.getLogger()
    log_level = getattr(logging, settings.level.upper(), logging.INFO)

    # 为避免重复初始化导致日志重复打印，这里先清空已有 handler。
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(log_level)
    stream_handler.addFilter(TraceIdFilter())

    if settings.json_format:
        # 当前先提供简化版 JSON 字符串格式，便于后续接日志平台。
        formatter = logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","trace_id":"%(trace_id)s","logger":"%(name)s","message":"%(message)s"}'
        )
    else:
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [trace_id=%(trace_id)s] [%(name)s] %(message)s"
        )

    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。"""

    return logging.getLogger(name)


def log_workflow_event(
    logger: logging.Logger,
    workflow_name: str,
    stage: str,
    **extra: Any,
) -> None:
    """统一记录工作流关键节点日志。

    stage 推荐使用：
    - started
    - finished
    - failed
    - retrying
    - skipped
    """

    extra_parts = [f"{key}={value}" for key, value in extra.items()]
    extra_text = f" | {' '.join(extra_parts)}" if extra_parts else ""
    logger.info("workflow=%s stage=%s%s", workflow_name, stage, extra_text)
