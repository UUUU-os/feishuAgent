from __future__ import annotations

import unittest

from scripts.agent_eval_suite import DEFAULT_FIXTURES_DIR, run_agent_eval_suite


class AgentEvalSuiteTest(unittest.TestCase):
    """验证 Agent 轨迹评测套件可以读取 fixture 并生成质量门报告。"""

    def test_run_agent_eval_suite(self) -> None:
        report = run_agent_eval_suite(fixtures_dir=DEFAULT_FIXTURES_DIR)

        self.assertGreaterEqual(report.total_cases, 3)
        self.assertEqual(report.passed_cases, report.total_cases)
        self.assertGreaterEqual(report.score, 0.95)
        self.assertEqual(report.safety_score, 1.0)


if __name__ == "__main__":
    unittest.main()
