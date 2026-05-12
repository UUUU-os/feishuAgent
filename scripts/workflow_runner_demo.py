from __future__ import annotations

import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/workflow_runner_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLMSettings, load_settings
from core import (
    AgentPolicy,
    GenerationSettings,
    KnowledgeIndexStore,
    MeetFlowAgentLoop,
    MeetFlowStorage,
    Resource,
    WorkflowContextBuilder,
    WorkflowRouter,
    build_agent_input,
    configure_logging,
)
from core.agent import MeetFlowAgent
from scripts.agent_demo import ScriptedDebugProvider, build_local_registry
from scripts.meetflow_agent_live_test import build_workflow_goal


def main() -> int:
    """验证确定性工作流骨架已经接入 Agent 主入口。"""

    settings = load_settings()
    configure_logging(settings.logging)

    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    seed_knowledge_index(settings)
    policy = AgentPolicy()
    registry = build_local_registry()
    agent = MeetFlowAgent(
        router=WorkflowRouter(),
        context_builder=WorkflowContextBuilder(storage=storage, default_project_id="meetflow"),
        loop=MeetFlowAgentLoop(
            llm_provider=ScriptedDebugProvider(),
            tool_registry=registry,
            policy=policy,
            storage=storage,
            max_iterations=3,
        ),
        storage=storage,
        policy=policy,
        enable_idempotency=False,
    )

    payload = {
        "workflow_type": "pre_meeting_brief",
        "required_tools": ["knowledge.search", "knowledge.fetch_chunk", "calendar.list_events", "tasks.list_my_tasks"],
        "calendar_id": "primary",
        "start_time": "1767024000",
        "end_time": "1767110400",
        "project_id": "meetflow",
        "meeting_id": "meeting_workflow_runner_demo",
        "summary": "MeetFlow M3 会前知识卡片方案讨论",
        "participants": [
            {"display_name": "产品负责人"},
            {"display_name": "研发负责人"},
        ],
        "attachments": [
            {"title": "MeetFlow 架构设计文档", "url": "https://example.feishu.cn/docx/demo"},
        ],
    }
    agent_input = build_agent_input(
        event_type="meeting.soon",
        payload=payload,
        source="workflow_runner_demo",
    )
    llm_settings = LLMSettings(
        provider="scripted-debug",
        model="scripted-debug",
        api_base="",
        api_key="",
        temperature=0.0,
        max_tokens=1000,
        reasoning_effort="",
    )
    result = agent.run(
        agent_input=agent_input,
        workflow_goal=build_workflow_goal(
            prompt="请生成会前背景知识卡片草案，并说明是否需要补充证据。",
            payload=payload,
        ),
        generation_settings=GenerationSettings(
            model=llm_settings.model,
            temperature=llm_settings.temperature,
            max_tokens=llm_settings.max_tokens,
            reasoning_effort=llm_settings.reasoning_effort,
        ),
        allow_write=False,
    )

    summary = summarize_result(result.to_dict())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.status in {"success", "max_iterations"} else 1


def seed_knowledge_index(settings: object) -> None:
    """为工作流 demo 准备一小组本地知识 chunk。"""

    store = KnowledgeIndexStore(settings.storage, embedding_settings=settings.embedding)
    store.initialize()
    store.index_resource(
        Resource(
            resource_id="workflow_demo_m3_rag",
            resource_type="doc",
            title="MeetFlow M3 会前知识卡片方案",
            content=(
                "# 上次结论\n"
                "M3 会前卡片需要优先使用轻量 RAG 检索知识 chunk，并保留来源链接。\n\n"
                "# 当前问题\n"
                "需要确认 knowledge.search 返回的 evidence pack 是否足够支撑摘要。\n\n"
                "# 风险\n"
                "如果只依赖日程附件，可能漏掉近期更新的妙记和任务。"
            ),
            source_url="https://example.feishu.cn/docx/workflow_demo_m3_rag",
            updated_at="2026-04-28",
            source_meta={"block_id": "block_workflow_demo_m3"},
        ),
        force=True,
    )


def summarize_result(result: dict[str, object]) -> dict[str, object]:
    """只打印验证骨架所需的关键信息。"""

    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    workflow_runner = payload.get("workflow_runner") if isinstance(payload.get("workflow_runner"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    raw_context = context.get("raw_context") if isinstance(context.get("raw_context"), dict) else {}
    pre_meeting_brief = raw_context.get("pre_meeting_brief") if isinstance(raw_context.get("pre_meeting_brief"), dict) else {}
    loop_state = result.get("loop_state") if isinstance(result.get("loop_state"), dict) else {}
    return {
        "status": result.get("status"),
        "workflow_type": result.get("workflow_type"),
        "final_answer": result.get("final_answer"),
        "workflow_runner": workflow_runner,
        "pre_meeting_stage_plan": raw_context.get("pre_meeting_stage_plan"),
        "retrieval_query_draft": raw_context.get("retrieval_query_draft"),
        "retrieval_result": raw_context.get("retrieval_result"),
        "meeting_brief_draft": pre_meeting_brief.get("meeting_brief"),
        "pre_meeting_card_payload": pre_meeting_brief.get("card_payload"),
        "tool_results": loop_state.get("tool_results", []),
    }


if __name__ == "__main__":
    raise SystemExit(main())
