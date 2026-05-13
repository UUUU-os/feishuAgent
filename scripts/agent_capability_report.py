from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_capabilities import build_agent_capability_report


def parse_args() -> argparse.Namespace:
    """解析 D6 Agent 能力报告参数。"""

    parser = argparse.ArgumentParser(description="输出 MeetFlow D6 Agent 能力报告。")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出。")
    parser.add_argument("--diagram-only", action="store_true", help="只输出 Mermaid 流程图。")
    return parser.parse_args()


def main() -> int:
    """生成报告；该脚本只读本地工作流定义，不访问飞书。"""

    args = parse_args()
    report = build_agent_capability_report()
    if args.diagram_only:
        print(report.flow_diagram)
        return 0
    indent = 2 if args.pretty else None
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
