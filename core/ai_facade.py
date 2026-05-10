from __future__ import annotations

from core.contracts import AIWorkflowInput, AIWorkflowResult


PRE_MEETING_BRIEF = "pre_meeting_brief"
POST_MEETING_SUMMARY = "post_meeting_summary"
RISK_SCAN_REASONING = "risk_scan_reasoning"

SUPPORTED_WORKFLOWS = {
    PRE_MEETING_BRIEF,
    POST_MEETING_SUMMARY,
    RISK_SCAN_REASONING,
}


def run_ai_workflow(input: AIWorkflowInput) -> AIWorkflowResult:
    """Run an AI workflow through the stable facade boundary."""

    if input.workflow_type == PRE_MEETING_BRIEF:
        return run_pre_meeting_brief(input)
    if input.workflow_type == POST_MEETING_SUMMARY:
        return run_post_meeting_summary(input)
    if input.workflow_type == RISK_SCAN_REASONING:
        return run_risk_scan_reasoning(input)

    return AIWorkflowResult(
        trace_id=input.trace_id,
        workflow_type=input.workflow_type,
        status="unsupported",
        summary="Unsupported AI workflow type.",
        errors=[f"unsupported workflow_type: {input.workflow_type}"],
    )


def run_pre_meeting_brief(input: AIWorkflowInput) -> AIWorkflowResult:
    """Return a stable pre-meeting facade response until real AI logic is wired."""

    return _stub_result(input, PRE_MEETING_BRIEF, "Pre-meeting brief AI workflow is ready to be wired.")


def run_post_meeting_summary(input: AIWorkflowInput) -> AIWorkflowResult:
    """Return a stable post-meeting facade response until real AI logic is wired."""

    return _stub_result(input, POST_MEETING_SUMMARY, "Post-meeting summary AI workflow is ready to be wired.")


def run_risk_scan_reasoning(input: AIWorkflowInput) -> AIWorkflowResult:
    """Return a stable risk-scan facade response until real AI logic is wired."""

    return _stub_result(input, RISK_SCAN_REASONING, "Risk scan reasoning AI workflow is ready to be wired.")


def _stub_result(input: AIWorkflowInput, workflow_type: str, summary: str) -> AIWorkflowResult:
    """Build a deterministic placeholder result for runtime integration tests."""

    return AIWorkflowResult(
        trace_id=input.trace_id,
        workflow_type=workflow_type,
        status="stub",
        summary=summary,
        data={
            "input_payload_keys": sorted(input.payload.keys()),
            "allow_write": input.allow_write,
        },
        metrics={"facade_stub": True},
    )
