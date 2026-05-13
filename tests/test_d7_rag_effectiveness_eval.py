from __future__ import annotations

import unittest

from scripts.d7_rag_effectiveness_eval import DEFAULT_FIXTURE_PATH, run_d7_evaluation


class D7RagEffectivenessEvalTest(unittest.TestCase):
    """锁定 D7 RAG 与 Agent 效果评测的核心指标。"""

    def test_d7_report_reaches_demo_thresholds(self) -> None:
        report = run_d7_evaluation(DEFAULT_FIXTURE_PATH, top_k=3)
        data = report.to_dict()

        self.assertGreaterEqual(data["overall_score"], 0.9)
        self.assertEqual(data["data_profile"]["retrieval_cases"], 40)
        self.assertEqual(data["retrieval"]["case_count"], 40)
        self.assertGreaterEqual(data["retrieval"]["metrics"]["hit@3"], 0.8)
        self.assertGreaterEqual(data["retrieval"]["metrics"]["mrr"], 0.8)
        self.assertGreaterEqual(data["answer_quality"]["with_rag"]["metrics"]["evidence_coverage"], 0.8)
        self.assertGreater(
            data["answer_quality"]["with_rag"]["score"],
            data["answer_quality"]["without_rag"]["score"],
        )
        self.assertEqual(data["agent_quality"]["safety_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
