from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# 允许直接通过 `python3 scripts/pre_meeting_trigger_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import (
    AgentPolicy,
    GenerationSettings,
    MeetFlowAgentLoop,
    MeetFlowStorage,
    WorkflowContextBuilder,
    WorkflowRouter,
    build_pre_meeting_trigger_plan,
    configure_logging,
    select_due_pre_meeting_events,
)
from core.agent import MeetFlowAgent
from scripts.agent_demo import ScriptedDebugProvider, build_local_registry


def main() -> int:
    """模拟 T3.8 会前定时触发，并验证幂等去重。"""

    settings = load_settings()
    configure_logging(settings.logging)
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    now = int(time.time())
    sample_events = [
        {
            "event_id": f"event_pre_meeting_trigger_demo_{now}",
            "summary": "MeetFlow M3 会前卡片评审",
            "start_time": str(now + settings.scheduler.pre_meeting_minutes_before * 60),
            "end_time": str(now + settings.scheduler.pre_meeting_minutes_before * 60 + 3600),
            "participants": [{"display_name": "产品负责人"}, {"display_name": "研发负责人"}],
            "attachments": [{"title": "MeetFlow M3 任务文档", "url": "https://example.feishu.cn/docx/m3"}],
        }
    ]
    due_events = select_due_pre_meeting_events(
        sample_events,
        now_ts=now,
        minutes_before=settings.scheduler.pre_meeting_minutes_before,
    )
    plan = build_pre_meeting_trigger_plan(due_events[0], project_id="meetflow")
    agent = build_local_pre_meeting_agent(storage)
    generation = GenerationSettings(model="scripted-debug", temperature=0.0, max_tokens=1000)

    first_result = agent.run(
        agent_input=plan.agent_input,
        workflow_goal="模拟会前定时触发，生成会前背景卡草案。",
        generation_settings=generation,
        allow_write=False,
    )
    second_result = agent.run(
        agent_input=plan.agent_input,
        workflow_goal="重复模拟同一会议会前触发，应该被幂等拦截。",
        generation_settings=generation,
        allow_write=False,
    )
    print(
        json.dumps(
            {
                "due_count": len(due_events),
                "trigger_plan": plan.to_dict(),
                "first_status": first_result.status,
                "second_status": second_result.status,
                "second_summary": second_result.summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if first_result.status in {"success", "max_iterations"} and second_result.status == "skipped" else 1


def build_local_pre_meeting_agent(storage: MeetFlowStorage) -> MeetFlowAgent:
    """构造不会访问真实飞书的会前 Agent，用于 scheduler 演练。"""

    policy = AgentPolicy()
    return MeetFlowAgent(
        router=WorkflowRouter(),
        context_builder=WorkflowContextBuilder(storage=storage, default_project_id="meetflow"),
        loop=MeetFlowAgentLoop(
            llm_provider=ScriptedDebugProvider(),
            tool_registry=build_local_registry(),
            policy=policy,
            storage=storage,
            max_iterations=3,
        ),
        storage=storage,
        policy=policy,
        enable_idempotency=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
