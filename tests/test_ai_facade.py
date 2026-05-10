from __future__ import annotations

import unittest

from core.ai_facade import (
    POST_MEETING_SUMMARY,
    PRE_MEETING_BRIEF,
    RISK_SCAN_REASONING,
    run_ai_workflow,
    run_post_meeting_summary,
    run_pre_meeting_brief,
    run_risk_scan_reasoning,
)
from core.contracts import AIWorkflowInput, AIWorkflowResult


class AIWorkflowContractTest(unittest.TestCase):
    """Verify the stable Runtime-to-AI contract."""

    def test_input_defaults_and_dict_roundtrip(self) -> None:
        workflow_input = AIWorkflowInput(workflow_type=PRE_MEETING_BRIEF)

        self.assertEqual(workflow_input.payload, {})
        self.assertEqual(workflow_input.trace_id, "")
        self.assertFalse(workflow_input.allow_write)
        self.assertEqual(
            AIWorkflowInput.from_dict(workflow_input.to_dict()),
            workflow_input,
        )

    def test_result_defaults_and_dict_roundtrip(self) -> None:
        result = AIWorkflowResult(
            trace_id="trace_1",
            workflow_type=POST_MEETING_SUMMARY,
            status="stub",
        )

        self.assertEqual(result.summary, "")
        self.assertEqual(result.data, {})
        self.assertEqual(result.evidence_refs, [])
        self.assertEqual(result.metrics, {})
        self.assertEqual(result.errors, [])
        self.assertEqual(AIWorkflowResult.from_dict(result.to_dict()), result)


class AIFacadeTest(unittest.TestCase):
    """Verify the AI facade exposes stable workflow entry points."""

    def test_run_ai_workflow_routes_pre_meeting(self) -> None:
        result = run_ai_workflow(
            AIWorkflowInput(
                workflow_type=PRE_MEETING_BRIEF,
                payload={"event_id": "event_1"},
                trace_id="trace_pre",
            )
        )

        self.assertEqual(result.workflow_type, PRE_MEETING_BRIEF)
        self.assertEqual(result.trace_id, "trace_pre")
        self.assertEqual(result.status, "stub")
        self.assertEqual(result.data["input_payload_keys"], ["event_id"])
        self.assertTrue(result.metrics["facade_stub"])

    def test_specific_facade_functions_pin_workflow_type(self) -> None:
        base_input = AIWorkflowInput(workflow_type="ignored", trace_id="trace_x", allow_write=True)

        self.assertEqual(run_pre_meeting_brief(base_input).workflow_type, PRE_MEETING_BRIEF)
        self.assertEqual(run_post_meeting_summary(base_input).workflow_type, POST_MEETING_SUMMARY)
        self.assertEqual(run_risk_scan_reasoning(base_input).workflow_type, RISK_SCAN_REASONING)

    def test_run_ai_workflow_reports_unsupported_type(self) -> None:
        result = run_ai_workflow(AIWorkflowInput(workflow_type="unknown", trace_id="trace_bad"))

        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.trace_id, "trace_bad")
        self.assertTrue(result.errors)


if __name__ == "__main__":
    unittest.main()
