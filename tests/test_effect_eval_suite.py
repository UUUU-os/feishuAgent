from __future__ import annotations

import unittest

from scripts.effect_eval_suite import render_markdown_report, run_effect_suite


class EffectEvalSuiteTest(unittest.TestCase):
    """验证比赛效果评测套件能稳定覆盖核心闭环能力。"""

    def test_run_effect_suite(self) -> None:
        report = run_effect_suite()

        self.assertEqual(report.total_cases, 8)
        self.assertEqual(report.passed_cases, 8)
        self.assertGreater(report.total_saved_minutes, 0)
        self.assertTrue(all(item.manual_steps for item in report.results))
        self.assertTrue(all(item.agent_steps for item in report.results))
        self.assertTrue(all(item.operation_reduction > 0 for item in report.results))

    def test_render_markdown_report_contains_value_columns(self) -> None:
        report = run_effect_suite()
        markdown = render_markdown_report(report)

        self.assertIn("| 场景 | 引入的操作 | 是否通过 | 人工基线 | Agent 估算 | 节省 | 操作减少 | 效率提升来源 |", markdown)
        self.assertIn("## 场景对比明细", markdown)
        self.assertIn("人工流程：", markdown)
        self.assertIn("引入 MeetFlow 后：", markdown)
        self.assertIn("会前资料充分", markdown)
        self.assertIn("妙记有明确待办", markdown)
        self.assertIn("预计节省", markdown)


if __name__ == "__main__":
    unittest.main()
