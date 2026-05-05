from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/e2e_replay.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation import run_evaluation_suite


DEFAULT_FIXTURES_DIR = PROJECT_ROOT / "tests" / "e2e_fixtures"


def parse_args() -> argparse.Namespace:
    """解析离线 E2E 回放评测参数。"""

    parser = argparse.ArgumentParser(description="MeetFlow 离线 E2E 回放评测。")
    parser.add_argument("--cases", default=str(DEFAULT_FIXTURES_DIR), help="评测 fixture 根目录。")
    parser.add_argument("--case", default="", help="只运行指定 case_id。")
    parser.add_argument("--all", action="store_true", help="运行全部 case；保留该参数便于命令语义清晰。")
    parser.add_argument("--fail-under", type=float, default=1.0, help="suite 分数低于该值时返回非 0。")
    parser.add_argument("--write-report", action="store_true", help="把评测报告写入 report-dir。")
    parser.add_argument("--report-dir", default="storage/reports/evaluation", help="评测报告目录。")
    return parser.parse_args()


def main() -> int:
    """执行离线 E2E 回放评测。"""

    args = parse_args()
    report = run_evaluation_suite(args.cases, case_id=args.case)
    report_data = report.to_dict()
    print(json.dumps(report_data, ensure_ascii=False, indent=2))
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = PROJECT_ROOT / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        suffix = args.case or "all"
        report_path = report_dir / f"e2e_replay_{suffix}_{report.generated_at}.json"
        report_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n评测报告已写入：{report_path}")
    if report.score < float(args.fail_under):
        print(f"\n评测分数 {report.score:.4f} 低于阈值 {args.fail_under:.4f}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
