from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# 允许直接通过 `python3 scripts/agent_models_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import (
    AgentDecision,
    AgentInput,
    AgentLoopState,
    AgentMessage,
    AgentRunResult,
    AgentToolCall,
    AgentToolResult,
    Event,
    Resource,
    WorkflowContext,
)


def main() -> int:
    """演示 T2.8 新增 Agent Runtime 数据模型如何串起来。"""

    now = int(time.time())

    # 1. AgentInput 是所有触发源进入 Agent 的统一入口。
    agent_input = AgentInput(
        trigger_type="event",
        event_type="meeting.soon",
        actor="ou_demo_user",
        source="calendar",
        event_id="evt_demo_meeting_soon",
        trace_id="trace_demo_agent",
        created_at=now,
        payload={
            "calendar_id": "primary",
            "event_id": "calendar_event_demo",
            "summary": "项目周会",
        },
    )

    # 2. AgentDecision 表示路由器做出的业务场景选择。
    decision = AgentDecision(
        workflow_type="pre_meeting_brief",
        confidence=0.95,
        reason="会议即将开始，需要生成会前背景卡片。",
        required_tools=["calendar.list_events", "docs.fetch_resource", "im.send_card"],
        idempotency_key="meeting:calendar_event_demo:pre_meeting_brief",
    )

    # 3. WorkflowContext 把原始事件转换成工作流能直接消费的上下文。
    event = Event(
        event_id=agent_input.event_id,
        event_type=agent_input.event_type,
        event_time=str(now),
        source=agent_input.source,
        actor=agent_input.actor,
        payload=agent_input.payload,
        trace_id=agent_input.trace_id,
    )
    resource = Resource(
        resource_id="doc_demo",
        resource_type="feishu_document",
        title="项目背景文档",
        content="这里是项目背景摘要。",
        source_url="https://example.feishu.cn/docx/demo",
        updated_at=str(now),
    )
    context = WorkflowContext(
        workflow_type=decision.workflow_type,
        trace_id=agent_input.trace_id,
        event=event,
        meeting_id="calendar_event_demo",
        calendar_event_id="calendar_event_demo",
        project_id="meetflow",
        related_resources=[resource],
        memory_snapshot={"last_decision": "上周决定优先完成飞书集成。"},
    )

    # 4. AgentLoopState 记录 LLM 多轮工具调用过程，后续 T2.13 会真正驱动它运行。
    tool_call = AgentToolCall(
        call_id="call_001",
        tool_name="docs.fetch_resource",
        arguments={"document_id": "doc_demo"},
    )
    loop_state = AgentLoopState(
        loop_id="loop_demo_001",
        trace_id=agent_input.trace_id,
        workflow_type=decision.workflow_type,
        max_iterations=4,
    )
    loop_state.append_message(
        AgentMessage(
            role="system",
            content="你是 MeetFlow，会基于证据生成会前背景卡。",
        )
    )
    loop_state.append_message(
        AgentMessage(
            role="assistant",
            content="我需要读取项目背景文档。",
            tool_calls=[tool_call],
        )
    )
    loop_state.pending_tool_calls.append(tool_call)
    loop_state.append_tool_result(
        AgentToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.tool_name,
            status="success",
            content="已读取项目背景文档，发现本周重点是完成 Agent Runtime。",
            data={"resource": resource.to_dict()},
            started_at=now,
            finished_at=now,
        )
    )
    loop_state.status = "finished"
    loop_state.stop_reason = "final_answer"

    # 5. AgentRunResult 是一次 Agent 运行的最终结果，可转换为现有 WorkflowResult 落盘。
    run_result = AgentRunResult(
        trace_id=agent_input.trace_id,
        workflow_type=decision.workflow_type,
        status="success",
        summary="会前背景卡片已生成。",
        final_answer="本次会议建议重点同步 Agent Runtime 的实现边界。",
        produced_resources=[resource],
        side_effects=[{"type": "dry_run", "target": "im.send_card"}],
        next_actions=["进入 T2.9，封装 LLMProvider。"],
        loop_state=loop_state,
        created_at=now,
        payload={
            "agent_input": agent_input.to_dict(),
            "decision": decision.to_dict(),
            "context": context.to_dict(),
        },
    )

    print(json.dumps(run_result.to_dict(), ensure_ascii=False, indent=2))
    print("\n转换为 WorkflowResult 后的结构：")
    print(json.dumps(run_result.to_workflow_result().to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
