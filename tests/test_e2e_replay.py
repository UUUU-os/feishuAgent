from __future__ import annotations

import unittest
from pathlib import Path

from core.evaluation import discover_evaluation_cases, run_evaluation_suite


FIXTURES_DIR = Path(__file__).resolve().parent / "e2e_fixtures"


class E2EReplayTest(unittest.TestCase):
    """验证脱敏 E2E fixture 能覆盖 M3/M4/M5/队列主链路。"""

    def test_discover_cases(self) -> None:
        cases = discover_evaluation_cases(FIXTURES_DIR)
        case_ids = {case.case_id for case in cases}

        self.assertIn("m3_pre_meeting_basic", case_ids)
        self.assertIn("m4_post_meeting_with_tasks", case_ids)
        self.assertIn("m5_risk_from_m4_mapping", case_ids)
        self.assertIn("job_queue_recovery", case_ids)

    def test_run_all_e2e_replay_cases(self) -> None:
        report = run_evaluation_suite(FIXTURES_DIR)

        self.assertEqual(report.total_cases, 4)
        self.assertEqual(report.passed_cases, 4)
        self.assertEqual(report.score, 1.0)

    def test_run_single_case(self) -> None:
        report = run_evaluation_suite(FIXTURES_DIR, case_id="m4_post_meeting_with_tasks")

        self.assertEqual(report.total_cases, 1)
        self.assertEqual(report.results[0].case_id, "m4_post_meeting_with_tasks")
        self.assertTrue(report.results[0].passed)


if __name__ == "__main__":
    unittest.main()
