from __future__ import annotations

import sys
from pathlib import Path

# 允许直接使用 `python3 scripts/logging_demo.py` 启动脚本。
# 这里主动把项目根目录加入 sys.path，避免出现找不到 config/core 模块的问题。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import WorkflowRunRecorder, configure_logging, get_logger


def main() -> None:
    """演示日志与审计底座的最小使用方式。"""

    settings = load_settings()
    configure_logging(settings.logging)

    logger = get_logger("meetflow.demo")
    recorder = WorkflowRunRecorder(
        workflow_name="demo_workflow",
        storage=settings.storage,
        logger_name="meetflow.demo.workflow",
    )

    try:
        trace_id = recorder.start(trigger="manual", scene="local_demo")
        logger.info("演示工作流开始执行，当前 trace_id=%s", trace_id)

        # 这里用一条普通日志模拟工具调用或业务处理过程。
        logger.info("正在执行模拟步骤：读取配置与记录审计日志")

        recorder.success(status="ok", records_written=2)
    except Exception as error:  # pragma: no cover - 这里只作为演示兜底
        recorder.failure(error, trigger="manual", scene="local_demo")
        raise


if __name__ == "__main__":
    # 保证脚本被直接执行时会进入演示主流程。
    main()
