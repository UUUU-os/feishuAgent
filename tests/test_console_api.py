from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config import (
    AppSettings,
    EmbeddingSettings,
    FeishuSettings,
    JobSettings,
    KnowledgeSearchSettings,
    LLMSettings,
    LoggingSettings,
    ObservabilitySettings,
    RerankerSettings,
    RiskRuleSettings,
    SchedulerSettings,
    StorageSettings,
)
from config.loader import Settings
from core.console_api import (
    ConsoleAPIError,
    EvaluationRunRequest,
    M3SendCardRequest,
    M4ReadMinuteRequest,
    M4SendCardsRequest,
    M5RiskScanRequest,
    MeetFlowConsoleAPI,
    parse_m3_stdout,
)
from core.jobs import JobQueue
from core.migrations import MigrationRunner
from scripts.meetflow_console_server import string_list_payload


class ConsoleAPITest(unittest.TestCase):
    """验证 MeetFlow Console 后端 facade。"""

    def test_health_reports_migration_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            MigrationRunner(settings.storage.db_path).apply_pending()
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))

            health = api.get_health()

            self.assertTrue(health["storage"]["db_exists"])
            self.assertTrue(health["migration"]["ok"])

    def test_list_jobs_returns_recent_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            queue = JobQueue(settings.storage)
            queue.enqueue(
                queue_name="workflow",
                job_type="agent_input.run",
                payload={"event_type": "meeting.soon"},
                idempotency_key="console:test",
            )
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))

            result = api.list_jobs(limit=5)

            self.assertEqual(result["items"][0]["job_type"], "agent_input.run")
            self.assertEqual(result["items"][0]["status"], "pending")

    def test_run_agent_evaluation_writes_latest_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))

            result = api.run_agent_evaluation(EvaluationRunRequest(write_report=True))

            self.assertEqual(result["score"], 1.0)
            self.assertEqual(result["safety_score"], 1.0)
            self.assertTrue((Path(temp_dir) / "storage" / "reports" / "evaluation" / "agent_trajectory_latest.json").exists())

    def test_run_m3_send_card_dry_run_wraps_existing_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))
            completed = SimpleNamespace(
                returncode=0,
                stdout=(
                    'trace_id: trace_console\nstatus: success\n'
                    '"report_json": "/tmp/pre_meeting_live_trace_console.json"'
                ),
            )

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                result = api.run_m3_send_card(
                    M3SendCardRequest(
                        event_title="MeetFlow 测试会议",
                        allow_write=False,
                        idempotency_suffix="m3-console-test",
                    )
                )

            command = run_mock.call_args.args[0]
            self.assertIn("--dry-run", command)
            self.assertEqual(result["parsed"]["trace_id"], "trace_console")
            self.assertEqual(result["parsed"]["status"], "success")

    def test_run_m3_send_card_passes_d2_resources_and_settings_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))
            completed = SimpleNamespace(returncode=0, stdout="status: success")

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                api.run_m3_send_card(
                    M3SendCardRequest(
                        date="today",
                        event_title="MeetFlow 测试会议",
                        llm_provider="settings",
                        doc=["https://example.feishu.cn/docx/doc1"],
                        minute=["https://example.feishu.cn/minutes/minute1"],
                        max_iterations=7,
                        allow_write=False,
                    )
                )

            command = run_mock.call_args.args[0]
            self.assertIn("--doc", command)
            self.assertIn("https://example.feishu.cn/docx/doc1", command)
            self.assertIn("--minute", command)
            self.assertIn("https://example.feishu.cn/minutes/minute1", command)
            self.assertIn("--max-iterations", command)
            self.assertIn("7", command)
            self.assertIn("settings", command)

    def test_m3_frontend_doc_minute_payload_accepts_single_or_multiline_values(self) -> None:
        self.assertEqual(string_list_payload("https://a/docx/1"), ["https://a/docx/1"])
        self.assertEqual(string_list_payload("https://a/docx/1\nhttps://a/docx/2"), ["https://a/docx/1", "https://a/docx/2"])
        self.assertEqual(string_list_payload(["https://a/minutes/1", ""]), ["https://a/minutes/1"])

    def test_parse_m3_stdout_extracts_report_paths(self) -> None:
        parsed = parse_m3_stdout(
            """
            trace_id: abc123
            workflow_type: pre_meeting_brief
            status: success
            "report_markdown": "/tmp/report.md",
            "report_json": "/tmp/report.json"
            """
        )

        self.assertEqual(parsed["trace_id"], "abc123")
        self.assertEqual(parsed["workflow_type"], "pre_meeting_brief")
        self.assertEqual(parsed["report_json"], "/tmp/report.json")

    def test_run_m4_read_minute_uses_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))
            completed = SimpleNamespace(returncode=0, stdout='{"report_path": "/tmp/m4.md"}')

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                result = api.run_m4_read_minute(M4ReadMinuteRequest(minute="https://example.feishu.cn/minutes/abc"))

            command = run_mock.call_args.args[0]
            self.assertIn("--read-only", command)
            self.assertNotIn("--allow-write", command)
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["report_path"], "/tmp/m4.md")

    def test_run_m4_send_cards_without_allow_write_uses_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))
            completed = SimpleNamespace(returncode=0, stdout="将执行：")

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                result = api.run_m4_send_cards(M4SendCardsRequest(minute="minute_token", chat_id="oc_test"))

            command = run_mock.call_args.args[0]
            self.assertIn("--dry-run", command)
            self.assertIn("--chat-id", command)
            self.assertTrue(result["dry_run"])

    def test_run_m4_send_cards_with_allow_write_removes_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))
            completed = SimpleNamespace(returncode=0, stdout='{"write_results": {"skipped": false}}')

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                result = api.run_m4_send_cards(M4SendCardsRequest(minute="minute_token", allow_write=True))

            command = run_mock.call_args.args[0]
            self.assertNotIn("--dry-run", command)
            self.assertFalse(result["dry_run"])

    def test_run_m4_send_cards_rejects_embedded_null_byte(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))

            with self.assertRaisesRegex(ConsoleAPIError, "不可见控制字符"):
                api.run_m4_send_cards(M4SendCardsRequest(minute="https://example.feishu.cn/minutes/abc\x00", allow_write=True))

    def test_run_m5_risk_scan_enqueue_wraps_existing_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))
            completed = SimpleNamespace(returncode=0, stdout='{"job_id": "job_test"}')

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                result = api.run_m5_risk_scan(M5RiskScanRequest(backend="feishu", mode="enqueue"))

            command = run_mock.call_args.args[0]
            self.assertIn("--enqueue", command)
            self.assertIn("--backend", command)
            self.assertEqual(result["job"]["job_id"], "job_test")

    def test_runtime_table_queries_return_empty_when_db_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = make_settings(temp_dir)
            api = MeetFlowConsoleAPI(settings=settings, project_root=Path(temp_dir))

            self.assertEqual(api.list_review_sessions()["items"], [])
            self.assertEqual(api.list_task_mappings()["items"], [])
            self.assertEqual(api.list_risk_notifications()["items"], [])


def make_settings(temp_dir: str) -> Settings:
    """构造 Console API 测试配置。"""

    root = Path(temp_dir)
    return Settings(
        app=AppSettings(name="MeetFlow", env="test", debug=True, timezone="Asia/Shanghai"),
        feishu=FeishuSettings(
            app_id="",
            app_secret="",
            base_url="https://open.feishu.cn",
            request_timeout_seconds=5,
            max_retries=1,
            default_identity="user",
            redirect_uri="",
            user_oauth_scope="",
            user_access_token="",
            user_access_token_expires_at=0,
            user_refresh_token="",
            user_refresh_token_expires_at=0,
            bot_name="MeetFlow",
            default_chat_id="",
            event_verification_token="",
            event_encrypt_key="",
            event_server_host="127.0.0.1",
            event_server_port=8765,
            event_receive_mode="websocket",
            event_sdk_log_level="info",
            event_http_enabled=False,
            event_http_paths=[],
        ),
        llm=LLMSettings(
            provider="scripted_debug",
            model="debug",
            api_base="",
            api_key="",
            temperature=0.0,
            max_tokens=512,
            reasoning_effort="low",
        ),
        embedding=EmbeddingSettings(
            provider="local",
            model="debug",
            api_base="",
            api_key="",
            dimensions=8,
            timeout_seconds=5,
        ),
        reranker=RerankerSettings(enabled=False, provider="", model="", top_k=5, timeout_seconds=5),
        knowledge_search=KnowledgeSearchSettings(fusion_strategy="rrf", rrf_k=60),
        scheduler=SchedulerSettings(
            pre_meeting_minutes_before=30,
            risk_scan_cron="",
            minute_retry_interval_minutes=5,
            minute_retry_max_attempts=3,
        ),
        risk_rules=RiskRuleSettings(stale_update_days=3, due_soon_hours=24, max_reminders_per_day=1),
        logging=LoggingSettings(level="INFO", json_format=False),
        storage=StorageSettings(
            db_path=str(root / "storage" / "meetflow.sqlite"),
            project_memory_dir=str(root / "storage" / "projects"),
            audit_log_path=str(root / "storage" / "workflow_events.jsonl"),
        ),
        jobs=JobSettings(
            enabled=True,
            default_queue="workflow",
            worker_id="test-worker",
            lock_seconds=60,
            max_attempts=3,
            retry_base_seconds=10,
            retry_max_seconds=60,
            dead_letter_after_attempts=3,
        ),
        observability=ObservabilitySettings(
            structured_events_enabled=False,
            structured_event_path=str(root / "storage" / "workflow_events.jsonl"),
            record_sensitive_payload=False,
            max_event_chars=2000,
            max_field_chars=500,
            mask_ids=True,
            daily_rotate=False,
        ),
    )


if __name__ == "__main__":
    unittest.main()
