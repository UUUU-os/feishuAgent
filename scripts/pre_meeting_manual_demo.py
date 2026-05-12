from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/pre_meeting_manual_demo.py` 启动脚本。
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
    build_manual_pre_meeting_input,
    configure_logging,
)
from core.agent import MeetFlowAgent
from scripts.agent_demo import ScriptedDebugProvider, build_local_registry


def parse_args() -> argparse.Namespace:
    """解析手动兜底入口参数。"""

    parser = argparse.ArgumentParser(description="T3.9 手动生成会前卡片兜底入口。")
    parser.add_argument("--command", default="生成 MeetFlow 今日会前卡片", help="用户命令文本。")
    parser.add_argument("--project-id", default="meetflow", help="项目 ID。")
    parser.add_argument("--meeting-title", default="", help="可选会议标题。")
    return parser.parse_args()


def main() -> int:
    """执行手动会前卡片兜底流程。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    agent_input = build_manual_pre_meeting_input(
        command_text=args.command,
        project_id=args.project_id,
        meeting_title=args.meeting_title,
    )
    agent = build_local_agent(storage)
    result = agent.run(
        agent_input=agent_input,
        workflow_goal=args.command,
        generation_settings=GenerationSettings(model="scripted-debug", temperature=0.0, max_tokens=1000),
        allow_write=False,
    )
    print(
        json.dumps(
            {
                "agent_input": agent_input.to_dict(),
                "status": result.status,
                "workflow_type": result.workflow_type,
                "summary": result.summary,
                "final_answer": result.final_answer,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.status in {"success", "max_iterations", "skipped"} else 1


def build_local_agent(storage: MeetFlowStorage) -> MeetFlowAgent:
    """构造本地手动兜底 Agent。"""

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
        enable_idempotency=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
