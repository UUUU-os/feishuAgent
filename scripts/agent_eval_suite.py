from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/agent_eval_suite.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.eval_metrics import AgentEvalResult, evaluate_agent_trace, score_secret_leakage_absent
from core.eval_trace import AgentTrace, PolicyDecisionTrace, ToolCallTrace


DEFAULT_FIXTURES_DIR = PROJECT_ROOT / "tests" / "e2e_fixtures" / "agent_trajectory"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "storage" / "reports" / "evaluation"


@dataclass(slots=True)
class AgentEvalSuiteReport:
    """Agent 轨迹评测套件报告。"""

    suite: str
    total_cases: int
    passed_cases: int
    score: float
    generated_at: int
    results: list[AgentEvalResult] = field(default_factory=list)
    safety_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """转换为报告 JSON。"""

        return {
            "suite": self.suite,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "score": self.score,
            "safety_score": self.safety_score,
            "generated_at": self.generated_at,
            "results": [item.to_dict() for item in self.results],
        }


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="MeetFlow Agent 轨迹评测套件。")
    parser.add_argument("--suite", default="agent_trajectory", help="评测套件名称。")
    parser.add_argument("--fixtures-dir", default=str(DEFAULT_FIXTURES_DIR), help="fixture 根目录。")
    parser.add_argument("--case-id", default="", help="只运行指定 case。")
    parser.add_argument("--provider", default="scripted_debug", help="记录本次评测 provider 名称。")
    parser.add_argument("--fail-under", type=float, default=0.95, help="最低通过分数。")
    parser.add_argument("--write-report", action="store_true", help="写入 storage/reports/evaluation。")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="报告输出目录。")
    return parser.parse_args()


def main() -> int:
    """脚本入口。"""

    args = parse_args()
    report = run_agent_eval_suite(
        fixtures_dir=Path(args.fixtures_dir),
        suite=args.suite,
        case_id=args.case_id,
    )
    report_dict = report.to_dict()
    report_dict["provider"] = args.provider
    print(json.dumps(report_dict, ensure_ascii=False, indent=2))

    if args.write_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        output_path = report_dir / f"{args.suite}_{int(time.time())}.json"
        output_path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        latest_path = report_dir / f"{args.suite}_latest.json"
        latest_path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n评测报告已写入：{output_path}")

    if report.score < args.fail_under:
        print(f"\n评测失败：score={report.score:.4f} 低于 fail-under={args.fail_under:.4f}")
        return 1
    if report.safety_score < 1.0:
        print("\n评测失败：报告疑似包含敏感字段。")
        return 1
    return 0


def run_agent_eval_suite(
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR,
    suite: str = "agent_trajectory",
    case_id: str = "",
) -> AgentEvalSuiteReport:
    """运行 Agent 轨迹评测套件。"""

    cases = discover_cases(fixtures_dir=fixtures_dir, case_id=case_id)
    results: list[AgentEvalResult] = []
    for case in cases:
        trace = parse_agent_trace(case["trace"])
        results.append(evaluate_agent_trace(case_id=str(case["case_id"]), trace=trace, expected=dict(case.get("expected") or {})))
    total = len(results)
    passed = sum(1 for item in results if item.passed)
    score = round(sum(item.score for item in results) / total, 4) if total else 0.0
    report = AgentEvalSuiteReport(
        suite=suite,
        total_cases=total,
        passed_cases=passed,
        score=score,
        generated_at=int(time.time()),
        results=results,
    )
    report.safety_score = score_secret_leakage_absent(report.to_dict())
    return report


def discover_cases(fixtures_dir: Path, case_id: str = "") -> list[dict[str, Any]]:
    """发现 agent trajectory case。"""

    paths = sorted(fixtures_dir.glob("*/case.json"))
    cases: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("case_id", path.parent.name)
        if case_id and data["case_id"] != case_id:
            continue
        cases.append(data)
    return cases


def parse_agent_trace(data: dict[str, Any]) -> AgentTrace:
    """从 fixture JSON 恢复 AgentTrace。"""

    tool_calls = [ToolCallTrace(**item) for item in list(data.get("tool_calls") or [])]
    policy_decisions = [PolicyDecisionTrace(**item) for item in list(data.get("policy_decisions") or [])]
    payload = dict(data)
    payload["tool_calls"] = tool_calls
    payload["policy_decisions"] = policy_decisions
    return AgentTrace(**payload)


if __name__ == "__main__":
    raise SystemExit(main())
