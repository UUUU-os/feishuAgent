from __future__ import annotations

import sys
import time
from pathlib import Path

# 允许直接从 scripts 目录运行演示脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import configure_logging, get_logger
from core.models import ActionItem, Event, MeetingSummary, RiskAlert, WorkflowResult
from core.storage import MeetFlowStorage


def main() -> None:
    """演示本地存储和公共数据模型的最小使用方式。"""

    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.storage.demo")

    storage = MeetFlowStorage(settings.storage)
    storage.initialize()

    # 先构造几条公共模型，模拟后续业务工作流的输入输出对象。
    demo_event = Event(
        event_id="evt_demo_001",
        event_type="message.command",
        event_time="2026-04-25T17:30:00+08:00",
        source="cli",
        actor="developer",
        payload={"command": "run storage demo"},
    )
    demo_action_item = ActionItem(
        item_id="item_demo_001",
        title="完成 MeetFlow 存储层原型",
        owner="lear-ubuntu-22",
        due_date="2026-04-26",
        priority="high",
        status="todo",
        confidence=0.95,
    )
    demo_summary = MeetingSummary(
        meeting_id="meeting_demo_001",
        project_id="meetflow",
        topic="存储层设计讨论",
        decisions=["采用 SQLite + JSON/JSONL 的混合存储方案"],
        action_items=[demo_action_item],
    )
    demo_risk = RiskAlert(
        risk_id="risk_demo_001",
        task_id="task_demo_001",
        risk_type="stale_update",
        severity="medium",
        reason="任务超过 3 天未更新",
        owner="lear-ubuntu-22",
        due_date="2026-04-28",
        suggestion="请补充当前进展或阻塞原因",
    )

    # 保存项目记忆，模拟长期知识沉淀。
    memory_path = storage.save_project_memory(
        "meetflow",
        {
            "project_name": "MeetFlow",
            "latest_event": demo_event.to_dict(),
            "latest_summary": demo_summary.to_dict(),
            "latest_risk": demo_risk.to_dict(),
        },
    )

    # 保存工作流结果，模拟一次完整流程的落盘。
    workflow_result = WorkflowResult(
        trace_id="trace_storage_demo_001",
        workflow_name="storage_demo",
        status="success",
        summary="演示本地存储已成功写入",
        payload={
            "event": demo_event.to_dict(),
            "meeting_summary": demo_summary.to_dict(),
            "risk_alert": demo_risk.to_dict(),
        },
        created_at=int(time.time()),
    )
    storage.save_workflow_result(workflow_result)

    # 保存幂等键和任务映射，模拟未来业务流程的去重与同步能力。
    storage.record_idempotency_key(
        idempotency_key="meeting_demo_001:storage_demo",
        workflow_name="storage_demo",
        trace_id=workflow_result.trace_id,
    )
    storage.save_task_mapping(
        item_id=demo_action_item.item_id,
        task_id="task_demo_001",
        owner=demo_action_item.owner,
        due_date=demo_action_item.due_date,
        status=demo_action_item.status,
    )
    storage.append_action_item_snapshot(demo_action_item.to_dict())

    # 读取刚刚保存的数据，确认整个存储链路是闭环的。
    stored_result = storage.get_workflow_result(workflow_result.trace_id)
    stored_mapping = storage.get_task_mapping(demo_action_item.item_id)
    stored_memory = storage.load_project_memory("meetflow")
    is_processed = storage.is_idempotency_key_processed("meeting_demo_001:storage_demo")

    logger.info("项目记忆写入位置=%s", memory_path)
    logger.info("工作流结果读取成功=%s", stored_result is not None)
    logger.info("任务映射读取成功=%s", stored_mapping is not None)
    logger.info("项目记忆读取成功=%s", stored_memory is not None)
    logger.info("幂等键已记录=%s", is_processed)


if __name__ == "__main__":
    main()
