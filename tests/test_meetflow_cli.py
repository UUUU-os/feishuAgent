from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.cli_facade import MeetFlowCLI, result_to_json
from scripts.meetflow_cli import build_live_command, build_parser, run_from_args
from tests.test_console_api import make_settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MeetFlowCLITest(unittest.TestCase):
    """覆盖 D8 OpenClaw/CLI 受控入口。"""

    def test_pre_meeting_defaults_to_dry_run_and_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli = MeetFlowCLI(settings=make_settings(temp_dir), project_root=Path(temp_dir))
            completed = SimpleNamespace(
                returncode=0,
                stdout='trace_id: trace_cli\nstatus: success\n"report_json": "/tmp/m3.json"',
            )

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                result = cli.pre_meeting(date="today", event_title="MeetFlow 测试会议")

            command = run_mock.call_args.args[0]
            payload = json.loads(result_to_json(result))
            self.assertIn("--dry-run", command)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["workflow_type"], "pre_meeting_brief")
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["allow_write"])

    def test_pre_meeting_allow_write_generates_idempotency_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli = MeetFlowCLI(settings=make_settings(temp_dir), project_root=Path(temp_dir))
            completed = SimpleNamespace(returncode=0, stdout="status: success")

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                result = cli.pre_meeting(date="today", event_title="MeetFlow 测试会议", allow_write=True)

            command = run_mock.call_args.args[0]
            self.assertNotIn("--dry-run", command)
            self.assertIn("--idempotency-suffix", command)
            self.assertTrue(result.safety_summary["idempotency_key_present"])

    def test_task_cards_reuses_post_meeting_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli = MeetFlowCLI(settings=make_settings(temp_dir), project_root=Path(temp_dir))
            completed = SimpleNamespace(returncode=0, stdout='{"pending_action_items": [1, 2], "report_path": "/tmp/m4.md"}')

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                result = cli.task_cards(minute="minute_token")

            command = run_mock.call_args.args[0]
            self.assertIn("--dry-run", command)
            self.assertEqual(result.workflow_type, "task_cards")

    def test_openclaw_tools_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli = MeetFlowCLI(settings=make_settings(temp_dir), project_root=Path(temp_dir))

            result = cli.openclaw_tools()

            names = {item["name"] for item in result.data["tools"]}
            self.assertIn("meetflow_pre_meeting", names)
            self.assertIn("meetflow_risk_scan", names)

    def test_meetflow_bin_wrapper_exposes_cli_help(self) -> None:
        wrapper = PROJECT_ROOT / "bin" / "meetflow"

        completed = subprocess.run([str(wrapper), "--help"], capture_output=True, text=True, check=False)

        self.assertEqual(completed.returncode, 0)
        self.assertIn("workflow", completed.stdout)
        self.assertIn("openclaw", completed.stdout)

    def test_parser_does_not_accept_raw_command_argument(self) -> None:
        parser = build_parser()

        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["health", "--command", "rm -rf /"])

    def test_run_from_args_dispatches_health(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = build_parser()
            args = parser.parse_args(["health"])
            cli = MeetFlowCLI(settings=make_settings(temp_dir), project_root=Path(temp_dir))

            result = run_from_args(args, cli)

            self.assertEqual(result.workflow_type, "health")
            self.assertEqual(result.status, "success")

    def test_workflow_plus_health_dispatches_existing_health(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = build_parser()
            args = parser.parse_args(["workflow", "+health"])
            cli = MeetFlowCLI(settings=make_settings(temp_dir), project_root=Path(temp_dir))

            result = run_from_args(args, cli)

            self.assertEqual(result.workflow_type, "health")
            self.assertEqual(result.status, "success")

    def test_workflow_plus_pre_meeting_reuses_existing_facade(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = build_parser()
            args = parser.parse_args(
                ["workflow", "+pre-meeting", "--date", "today", "--event-title", "MeetFlow 测试会议"]
            )
            cli = MeetFlowCLI(settings=make_settings(temp_dir), project_root=Path(temp_dir))
            completed = SimpleNamespace(returncode=0, stdout="status: success")

            with patch("core.console_api.subprocess.run", return_value=completed) as run_mock:
                result = run_from_args(args, cli)

            command = run_mock.call_args.args[0]
            self.assertIn("--dry-run", command)
            self.assertEqual(result.workflow_type, "pre_meeting_brief")

    def test_openclaw_plus_tools_dispatches_tool_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = build_parser()
            args = parser.parse_args(["openclaw", "+tools"])
            cli = MeetFlowCLI(settings=make_settings(temp_dir), project_root=Path(temp_dir))

            result = run_from_args(args, cli)

            names = {item["name"] for item in result.data["tools"]}
            self.assertIn("meetflow_pre_meeting", names)
            self.assertEqual(result.workflow_type, "openclaw_tools")

    def test_service_plus_list_dispatches_existing_service_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = build_parser()
            args = parser.parse_args(["service", "+list"])
            cli = MeetFlowCLI(settings=make_settings(temp_dir), project_root=Path(temp_dir))

            result = run_from_args(args, cli)

            self.assertEqual(result.workflow_type, "service")
            self.assertEqual(result.data["action"], "list")

    def test_live_sdk_callback_wraps_fixed_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["live", "sdk-callback"])

        command = build_live_command(args)

        self.assertIn("feishu_event_sdk_server.py", " ".join(command))
        self.assertIn("--enqueue-agent", command)
        self.assertIn("dry-run", command)

    def test_live_plus_sdk_callback_wraps_same_fixed_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["live", "+sdk-callback"])

        command = build_live_command(args)

        self.assertIn("feishu_event_sdk_server.py", " ".join(command))
        self.assertIn("--enqueue-agent", command)
        self.assertIn("dry-run", command)

    def test_live_worker_wraps_fixed_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["live", "worker"])

        command = build_live_command(args)

        self.assertIn("meetflow_worker.py", " ".join(command))
        self.assertIn("workflow,risk_scan,rag_refresh", command)

    def test_live_d3_card_wraps_card_send_live_m4(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["live", "d3-card", "--minute", "minute_token", "--show-card-json"])

        command = build_live_command(args)

        self.assertIn("card_send_live.py", " ".join(command))
        self.assertIn("m4", command)
        self.assertIn("--report-dir", command)
        self.assertIn("storage/reports/m4/d3", command)
        self.assertIn("--show-card-json", command)

    def test_live_watch_callbacks_wraps_tail_files(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["live", "watch-callbacks"])

        command = build_live_command(args)

        self.assertEqual(command[0], "tail")
        self.assertIn("card_callbacks.jsonl", " ".join(command))
        self.assertIn("workflow_events.jsonl", " ".join(command))


if __name__ == "__main__":
    unittest.main()
