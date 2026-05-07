from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.agent_loop import MeetFlowAgentLoop
from core.assistant_memory import AssistantSession, apply_user_reply_to_pending_action
from core.llm import LLMProvider, LLMResponse
from core.models import AgentMessage, AgentToolCall, Event, WorkflowContext
from core.policy import AgentPolicy
from core.storage import MeetFlowStorage
from core.tools import AgentTool, ToolRegistry


class CreateTaskThenAnswerProvider(LLMProvider):
    """首轮尝试创建任务，第二轮根据 policy 结果收束回答。"""

    def chat(self, messages: list[AgentMessage], tools=None, settings=None) -> LLMResponse:  # noqa: ANN001
        if any(message.role == "tool" for message in messages):
            return LLMResponse(content="需要用户补充字段。", finish_reason="stop", model="test")
        return LLMResponse(
            tool_calls=[
                AgentToolCall(
                    call_id="call_create_task",
                    tool_name="tasks_create_task",
                    arguments={
                        "summary": "整理会后材料",
                        "confidence": 0.9,
                        "idempotency_key": "task_demo_001",
                    },
                )
            ],
            finish_reason="tool_calls",
            model="test",
        )


class AssistantMemoryTest(unittest.TestCase):
    """验证多轮会话记忆和 pending action 恢复。"""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        settings = SimpleNamespace(
            db_path=str(root / "meetflow.sqlite"),
            project_memory_dir=str(root / "project_memory"),
            audit_log_path=str(root / "audit.jsonl"),
        )
        self.storage = MeetFlowStorage(settings)
        self.storage.initialize()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_agent_loop_saves_pending_action_when_policy_needs_confirmation(self) -> None:
        registry = ToolRegistry()
        registry.register(
            AgentTool(
                internal_name="tasks.create_task",
                description="创建飞书任务。",
                parameters={
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "confidence": {"type": "number"},
                        "idempotency_key": {"type": "string"},
                    },
                    "required": ["summary", "confidence", "idempotency_key"],
                },
                handler=lambda **_: {"unexpected": True},
                read_only=False,
                side_effect="create_task",
            )
        )
        loop = MeetFlowAgentLoop(
            llm_provider=CreateTaskThenAnswerProvider(),
            tool_registry=registry,
            policy=AgentPolicy(),
            storage=self.storage,
            max_iterations=2,
        )
        context = WorkflowContext(
            workflow_type="post_meeting_followup",
            trace_id="trace_memory_001",
            event=Event(
                event_id="evt_memory",
                event_type="minute.ready",
                event_time="1700000000",
                source="test",
                actor="ou_user",
                trace_id="trace_memory_001",
            ),
            raw_context={"assistant_session": {"session_id": "asst_memory_001"}},
        )

        result = loop.run(context=context, required_tools=["tasks.create_task"], allow_write=True)

        self.assertEqual(result.status, "success")
        pending = self.storage.find_latest_pending_action(session_id="asst_memory_001")
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.tool_name, "tasks.create_task")
        self.assertIn("human_confirmation", pending.missing_fields)
        tool_result = result.loop_state.tool_results[0] if result.loop_state else None
        self.assertIsNotNone(tool_result)
        assert tool_result is not None
        self.assertTrue(tool_result.data.get("pending_action_id"))

    def test_save_session_works_with_legacy_user_id_columns(self) -> None:
        self.tmpdir.cleanup()
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        db_path = root / "meetflow.sqlite"
        settings = SimpleNamespace(
            db_path=str(db_path),
            project_memory_dir=str(root / "project_memory"),
            audit_log_path=str(root / "audit.jsonl"),
        )
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE assistant_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    current_workflow TEXT NOT NULL,
                    current_meeting_id TEXT NOT NULL,
                    current_project_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

        storage = MeetFlowStorage(settings)
        storage.initialize()
        storage.save_assistant_session(
            AssistantSession(
                session_id="asst_legacy",
                actor="ou_legacy_user",
                source="live_test",
                workflow_type="pre_meeting_brief",
                memory={
                    "chat_id": "oc_legacy_chat",
                    "meeting_id": "evt_legacy",
                    "project_id": "meetflow",
                },
                last_trace_id="trace_legacy",
                created_at=1700000000,
                updated_at=1700000001,
            )
        )

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT user_id, chat_id, current_workflow, current_meeting_id,
                       current_project_id, actor, memory_json
                FROM assistant_sessions
                WHERE session_id = ?
                """,
                ("asst_legacy",),
            ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], "ou_legacy_user")
        self.assertEqual(row[1], "oc_legacy_chat")
        self.assertEqual(row[2], "pre_meeting_brief")
        self.assertEqual(row[3], "evt_legacy")
        self.assertEqual(row[4], "meetflow")
        self.assertEqual(row[5], "ou_legacy_user")
        self.assertIn("evt_legacy", row[6])

    def test_user_reply_patches_pending_action_fields(self) -> None:
        registry = ToolRegistry()
        # 通过上一条集成路径先落一个 pending，再模拟用户下一轮补字段。
        registry.register(
            AgentTool(
                internal_name="tasks.create_task",
                description="创建飞书任务。",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=lambda **_: {"unexpected": True},
                read_only=False,
                side_effect="create_task",
            )
        )
        loop = MeetFlowAgentLoop(
            llm_provider=CreateTaskThenAnswerProvider(),
            tool_registry=registry,
            policy=AgentPolicy(),
            storage=self.storage,
            max_iterations=2,
        )
        context = WorkflowContext(
            workflow_type="post_meeting_followup",
            trace_id="trace_memory_002",
            raw_context={"assistant_session": {"session_id": "asst_memory_002"}},
        )
        loop.run(context=context, required_tools=["tasks.create_task"], allow_write=True)
        pending = self.storage.find_latest_pending_action(session_id="asst_memory_002")
        self.assertIsNotNone(pending)
        assert pending is not None
        pending.missing_fields = ["assignee_ids", "due_timestamp_ms"]

        patched = apply_user_reply_to_pending_action(
            pending,
            "负责人是我，截止明天",
            actor_open_id="ou_current_user",
            now=1700000000,
        )

        self.assertEqual(patched.status, "ready_to_resume")
        self.assertEqual(patched.tool_arguments["assignee_ids"], ["ou_current_user"])
        self.assertTrue(str(patched.tool_arguments["due_timestamp_ms"]).isdigit())


if __name__ == "__main__":
    unittest.main()
