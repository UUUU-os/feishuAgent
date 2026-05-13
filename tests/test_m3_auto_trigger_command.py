from __future__ import annotations

import argparse
import unittest

from core.models import CalendarEvent
from scripts.live_environment_watch import build_daemon_args
from scripts.meetflow_daemon import build_m3_card_send_command, build_m4_agent_command
from scripts.meetflow_worker import build_post_meeting_command, build_pre_meeting_command


class M3AutoTriggerCommandTest(unittest.TestCase):
    """锁定自动监听触发 M3/M4 时使用 D2/D4 真实演示参数。"""

    def test_live_watch_daemon_args_default_to_d2_settings_provider(self) -> None:
        args = argparse.Namespace(
            identity="user",
            calendar_id="primary",
            poll_seconds=15,
            lookahead_hours=24,
            m3_minutes_before=9,
            m3_llm_provider="settings",
            no_m3_write_report=False,
            m4_lookback_hours=12,
            m4_delay_minutes=5,
            m4_llm_provider="settings",
            m4_max_iterations=8,
            rag_limit=20,
        )

        daemon_args = build_daemon_args(args, dry_run=False)

        self.assertEqual(daemon_args.m3_llm_provider, "settings")
        self.assertTrue(daemon_args.m3_write_report)
        self.assertEqual(daemon_args.m4_llm_provider, "settings")
        self.assertEqual(daemon_args.m4_max_iterations, 8)

    def test_daemon_m3_command_uses_event_id_and_d2_provider(self) -> None:
        event = CalendarEvent(
            event_id="event_demo_0",
            summary="MeetFlow 测试会议",
            start_time="1778661900",
            end_time="1778663700",
        )
        args = argparse.Namespace(
            identity="user",
            calendar_id="primary",
            m3_llm_provider="settings",
            m3_write_report=True,
        )

        command = build_m3_card_send_command(event, args=args)

        self.assertIn("scripts/card_send_live.py", command[1])
        self.assertIn("m3", command)
        self.assertIn("--event-id", command)
        self.assertIn("event_demo_0", command)
        self.assertIn("--llm-provider", command)
        self.assertIn("settings", command)
        self.assertIn("--write-report", command)

    def test_daemon_m4_command_uses_d4_agent_script(self) -> None:
        args = argparse.Namespace(
            m4_llm_provider="settings",
            m4_max_iterations=8,
        )

        command = build_m4_agent_command("https://bytedance.larkoffice.com/minutes/minute_demo", args=args)

        self.assertIn("scripts/post_meeting_agent_live_test.py", command[1])
        self.assertIn("--minute-token", command)
        self.assertIn("https://bytedance.larkoffice.com/minutes/minute_demo", command)
        self.assertIn("--llm-provider", command)
        self.assertIn("settings", command)
        self.assertIn("--max-iterations", command)
        self.assertIn("8", command)
        self.assertIn("--idempotency-suffix", command)
        suffix_index = command.index("--idempotency-suffix") + 1
        self.assertTrue(command[suffix_index].startswith("daemon-"))
        self.assertNotIn("scripts/card_send_live.py", " ".join(command))

    def test_worker_m4_command_uses_d4_agent_script(self) -> None:
        command = build_post_meeting_command(
            {
                "minute_token": "minute_demo",
                "llm_provider": "settings",
                "max_iterations": 8,
            },
            settings=object(),
        )

        self.assertIn("scripts/post_meeting_agent_live_test.py", command[1])
        self.assertIn("--minute-token", command)
        self.assertIn("minute_demo", command)
        self.assertIn("--llm-provider", command)
        self.assertIn("settings", command)
        self.assertIn("--max-iterations", command)
        self.assertIn("8", command)
        self.assertNotIn("scripts/card_send_live.py", " ".join(command))

    def test_worker_m3_command_keeps_enqueued_d2_provider_and_report(self) -> None:
        command = build_pre_meeting_command(
            {
                "identity": "user",
                "calendar_id": "primary",
                "event_id": "event_demo_0",
                "llm_provider": "settings",
                "idempotency_suffix": "daemon-event_demo_0-9",
                "write_report": True,
            }
        )

        self.assertIn("--llm-provider", command)
        self.assertIn("settings", command)
        self.assertIn("--event-id", command)
        self.assertIn("event_demo_0", command)
        self.assertIn("--write-report", command)


if __name__ == "__main__":
    unittest.main()
