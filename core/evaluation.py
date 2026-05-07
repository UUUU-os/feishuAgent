from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import StorageSettings
from core.jobs import JobQueue
from core.models import Resource
from core.post_meeting import PostMeetingInput, build_post_meeting_artifacts_from_input
from core.pre_meeting import (
    PreMeetingBriefInput,
    build_initial_meeting_brief,
    build_retrieval_query,
    identify_meeting_topic,
    recall_related_resources,
    render_pre_meeting_card_payload,
)
from core.risk_scan import enrich_risks_with_task_mappings, normalize_task_snapshots, scan_risks
from core.storage import MeetFlowStorage


@dataclass(slots=True)
class EvaluationAssertion:
    """评测中的一条断言结果。

    它比普通 unittest 更适合生成报告：失败时保留实际值和期望值，方便答辩
    或 CI 里直接定位是抽取、卡片、风险还是队列退化。
    """

    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为报告 JSON。"""

        return {
            "name": self.name,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
        }


@dataclass(slots=True)
class EvaluationCase:
    """一条可回放业务评测样本。"""

    case_id: str
    workflow: str
    description: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    fixture_path: str = ""


@dataclass(slots=True)
class EvaluationResult:
    """单条评测样本的执行结果。"""

    case_id: str
    workflow: str
    passed: bool
    score: float
    assertions: list[EvaluationAssertion] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为报告 JSON。"""

        return {
            "case_id": self.case_id,
            "workflow": self.workflow,
            "passed": self.passed,
            "score": self.score,
            "assertions": [item.to_dict() for item in self.assertions],
            "artifacts": self.artifacts,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass(slots=True)
class EvaluationSuiteReport:
    """评测套件聚合报告。"""

    total_cases: int
    passed_cases: int
    score: float
    results: list[EvaluationResult] = field(default_factory=list)
    generated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为报告 JSON。"""

        return {
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "score": self.score,
            "generated_at": self.generated_at,
            "results": [item.to_dict() for item in self.results],
        }


def load_evaluation_case(path: str | Path) -> EvaluationCase:
    """读取单条 JSON fixture。"""

    fixture_path = Path(path)
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return EvaluationCase(
        case_id=str(data.get("case_id") or fixture_path.parent.name),
        workflow=str(data.get("workflow") or ""),
        description=str(data.get("description") or ""),
        input=dict(data.get("input") or {}),
        expected=dict(data.get("expected") or {}),
        fixture_path=str(fixture_path),
    )


def discover_evaluation_cases(fixtures_dir: str | Path, case_id: str = "") -> list[EvaluationCase]:
    """发现评测样本目录下的 case.json。"""

    root = Path(fixtures_dir)
    paths = sorted(root.glob("*/case.json"))
    cases = [load_evaluation_case(path) for path in paths]
    if case_id:
        cases = [case for case in cases if case.case_id == case_id]
    return cases


def run_evaluation_suite(fixtures_dir: str | Path, case_id: str = "") -> EvaluationSuiteReport:
    """运行一组离线评测样本。"""

    results = [run_evaluation_case(case) for case in discover_evaluation_cases(fixtures_dir, case_id=case_id)]
    passed_cases = sum(1 for result in results if result.passed)
    total_cases = len(results)
    return EvaluationSuiteReport(
        total_cases=total_cases,
        passed_cases=passed_cases,
        score=round(passed_cases / total_cases, 4) if total_cases else 0.0,
        results=results,
        generated_at=int(time.time()),
    )


def run_evaluation_case(case: EvaluationCase) -> EvaluationResult:
    """运行单条评测样本。"""

    started = time.perf_counter()
    try:
        if case.workflow == "m3_pre_meeting":
            assertions, artifacts = evaluate_m3_pre_meeting(case)
        elif case.workflow == "m4_post_meeting":
            assertions, artifacts = evaluate_m4_post_meeting(case)
        elif case.workflow == "m5_risk_scan":
            assertions, artifacts = evaluate_m5_risk_scan(case)
        elif case.workflow == "job_queue":
            assertions, artifacts = evaluate_job_queue(case)
        else:
            raise ValueError(f"不支持的评测 workflow：{case.workflow}")
        passed = all(item.passed for item in assertions)
        score = round(sum(1 for item in assertions if item.passed) / len(assertions), 4) if assertions else 0.0
        return EvaluationResult(
            case_id=case.case_id,
            workflow=case.workflow,
            passed=passed,
            score=score,
            assertions=assertions,
            artifacts=artifacts,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as error:  # noqa: BLE001 - 评测失败要变成报告，而不是中断整套 suite。
        return EvaluationResult(
            case_id=case.case_id,
            workflow=case.workflow,
            passed=False,
            score=0.0,
            assertions=[],
            artifacts={},
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=str(error),
        )


def evaluate_m3_pre_meeting(case: EvaluationCase) -> tuple[list[EvaluationAssertion], dict[str, Any]]:
    """评测 M3 会前知识卡片的确定性产物。"""

    case_input = dict(case.input)
    resources = [Resource(**item) for item in case_input.pop("related_resources", [])]
    workflow_input = PreMeetingBriefInput(related_resources=resources, **case_input)
    topic_signal = identify_meeting_topic(workflow_input)
    retrieval_query = build_retrieval_query(workflow_input, topic_signal)
    retrieval_result = recall_related_resources(workflow_input, retrieval_query, top_k=case.expected.get("top_k", 6))
    brief = build_initial_meeting_brief(
        workflow_input=workflow_input,
        retrieval_query=retrieval_query,
        topic_signal=topic_signal,
        retrieval_result=retrieval_result,
    )
    card_payload = render_pre_meeting_card_payload(brief)
    artifacts = {
        "topic": brief.topic,
        "confidence": brief.confidence,
        "summary": brief.summary,
        "facts": card_payload.facts,
        "must_read_count": len(brief.must_read_resources),
        "risk_count": len(brief.risks),
        "current_question_count": len(brief.current_questions),
    }
    assertions = [
        assert_contains("topic_contains", brief.topic, case.expected.get("topic_contains", "")),
        assert_min_count("min_must_read_resources", len(brief.must_read_resources), case.expected.get("min_must_read_resources", 0)),
        assert_min_count("min_current_questions", len(brief.current_questions), case.expected.get("min_current_questions", 0)),
        assert_min_count("min_risks", len(brief.risks), case.expected.get("min_risks", 0)),
    ]
    return assertions, artifacts


def evaluate_m4_post_meeting(case: EvaluationCase) -> tuple[list[EvaluationAssertion], dict[str, Any]]:
    """评测 M4 会后总结和行动项抽取。"""

    workflow_input = PostMeetingInput(**case.input)
    artifacts_obj = build_post_meeting_artifacts_from_input(workflow_input)
    action_items = artifacts_obj.action_items
    pending_items = artifacts_obj.pending_action_items
    titles = [item.title for item in action_items]
    owners = [item.owner for item in action_items]
    due_dates = [item.due_date for item in action_items]
    artifacts = {
        "action_item_count": len(action_items),
        "pending_action_item_count": len(pending_items),
        "titles": titles,
        "owners": owners,
        "due_dates": due_dates,
        "decision_count": len(artifacts_obj.decisions),
        "open_question_count": len(artifacts_obj.open_questions),
    }
    assertions = [
        assert_min_count("min_action_items", len(action_items), case.expected.get("min_action_items", 0)),
        assert_min_count("min_pending_action_items", len(pending_items), case.expected.get("min_pending_action_items", 0)),
        assert_any_contains("title_contains", titles, case.expected.get("title_contains", "")),
        assert_any_equals("owner", owners, case.expected.get("owner", "")),
        assert_any_contains("due_date_contains", due_dates, case.expected.get("due_date_contains", "")),
    ]
    return assertions, artifacts


def evaluate_m5_risk_scan(case: EvaluationCase) -> tuple[list[EvaluationAssertion], dict[str, Any]]:
    """评测 M5 风险规则和 M4 来源证据富化。"""

    now = int(case.input.get("now") or time.time())
    snapshots = normalize_task_snapshots(list(case.input.get("tasks") or []))
    result = scan_risks(
        tasks=snapshots,
        now=now,
        stale_update_days=int(case.input.get("stale_update_days", 3)),
        due_soon_hours=int(case.input.get("due_soon_hours", 24)),
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = MeetFlowStorage(
            StorageSettings(
                db_path=str(Path(temp_dir) / "meetflow.sqlite"),
                project_memory_dir=str(Path(temp_dir) / "projects"),
                audit_log_path=str(Path(temp_dir) / "audit.jsonl"),
            )
        )
        storage.initialize()
        for mapping in list(case.input.get("task_mappings") or []):
            storage.save_task_mapping(**mapping)
        enriched = enrich_risks_with_task_mappings(result, storage)
    risk_types = [risk.risk_type for risk in enriched.risks]
    evidence_sources = [
        str((risk.evidence.get("m4_task_mapping") or {}).get("source_url") or "")
        for risk in enriched.risks
    ]
    artifacts = {
        "scanned_count": enriched.scanned_count,
        "risk_count": enriched.risk_count,
        "risk_types": risk_types,
        "evidence_sources": evidence_sources,
        "summary": enriched.summary,
    }
    assertions = [
        assert_min_count("min_risks", enriched.risk_count, case.expected.get("min_risks", 0)),
        assert_list_contains_all("risk_types", risk_types, list(case.expected.get("risk_types") or [])),
        assert_any_contains("evidence_source_contains", evidence_sources, case.expected.get("evidence_source_contains", "")),
    ]
    return assertions, artifacts


def evaluate_job_queue(case: EvaluationCase) -> tuple[list[EvaluationAssertion], dict[str, Any]]:
    """评测 SQLite job queue 的入队、领取和完成路径。"""

    with tempfile.TemporaryDirectory() as temp_dir:
        storage = StorageSettings(
            db_path=str(Path(temp_dir) / "meetflow.sqlite"),
            project_memory_dir=str(Path(temp_dir) / "projects"),
            audit_log_path=str(Path(temp_dir) / "audit.jsonl"),
        )
        queue = JobQueue(storage)
        jobs = []
        for item in list(case.input.get("jobs") or []):
            jobs.append(queue.enqueue(**item))
        claimed = queue.claim_due_job(
            worker_id=str(case.input.get("worker_id") or "eval_worker"),
            queues=list(case.input.get("queues") or ["workflow"]),
            lock_seconds=60,
        )
        if claimed is not None and case.input.get("mark_succeeded", True):
            queue.mark_succeeded(claimed.job_id, result={"eval": "ok"})
        latest_jobs = queue.list_jobs(limit=10)
    artifacts = {
        "enqueued_count": len(jobs),
        "claimed_job_type": claimed.job_type if claimed else "",
        "claimed_status": claimed.status if claimed else "",
        "final_statuses": {job.job_id: job.status for job in latest_jobs},
    }
    assertions = [
        assert_min_count("min_enqueued", len(jobs), case.expected.get("min_enqueued", 0)),
        assert_equals("claimed_job_type", artifacts["claimed_job_type"], case.expected.get("claimed_job_type", "")),
        assert_any_equals("final_status", list(artifacts["final_statuses"].values()), case.expected.get("final_status", "")),
    ]
    return assertions, artifacts


def assert_equals(name: str, actual: Any, expected: Any) -> EvaluationAssertion:
    """判断实际值是否等于期望值。"""

    if expected in ("", None):
        return EvaluationAssertion(name=name, passed=True, expected=expected, actual=actual)
    return EvaluationAssertion(name=name, passed=actual == expected, expected=expected, actual=actual)


def assert_contains(name: str, actual: str, expected: str) -> EvaluationAssertion:
    """判断字符串包含关系；空期望表示跳过。"""

    if not expected:
        return EvaluationAssertion(name=name, passed=True, expected=expected, actual=actual)
    return EvaluationAssertion(
        name=name,
        passed=expected.lower() in str(actual).lower(),
        expected=expected,
        actual=actual,
    )


def assert_any_contains(name: str, actual_items: list[str], expected: str) -> EvaluationAssertion:
    """判断列表中是否有元素包含期望文本。"""

    if not expected:
        return EvaluationAssertion(name=name, passed=True, expected=expected, actual=actual_items)
    passed = any(expected.lower() in str(item).lower() for item in actual_items)
    return EvaluationAssertion(name=name, passed=passed, expected=expected, actual=actual_items)


def assert_any_equals(name: str, actual_items: list[str], expected: str) -> EvaluationAssertion:
    """判断列表中是否有元素等于期望文本。"""

    if not expected:
        return EvaluationAssertion(name=name, passed=True, expected=expected, actual=actual_items)
    return EvaluationAssertion(name=name, passed=expected in actual_items, expected=expected, actual=actual_items)


def assert_min_count(name: str, actual: int, expected: int) -> EvaluationAssertion:
    """判断数量是否达到下限。"""

    expected_count = int(expected or 0)
    return EvaluationAssertion(name=name, passed=actual >= expected_count, expected=expected_count, actual=actual)


def assert_list_contains_all(name: str, actual_items: list[str], expected_items: list[str]) -> EvaluationAssertion:
    """判断实际列表是否包含所有期望项。"""

    missing = [item for item in expected_items if item not in actual_items]
    return EvaluationAssertion(
        name=name,
        passed=not missing,
        expected=expected_items,
        actual=actual_items,
        message=f"missing={missing}" if missing else "",
    )
