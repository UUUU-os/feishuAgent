from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 允许直接通过 `python3 scripts/storage_migrate.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core.logging import configure_logging
from core.migrations import MigrationError, MigrationRunner


def parse_args() -> argparse.Namespace:
    """解析数据库迁移命令。"""

    parser = argparse.ArgumentParser(description="MeetFlow SQLite schema migration 工具。")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true", help="查看 migration 应用状态。")
    action.add_argument("--apply", action="store_true", help="应用所有未执行 migration。")
    action.add_argument("--verify", action="store_true", help="校验当前 schema 是否满足运行要求。")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出状态，便于 CI/健康检查解析。")
    return parser.parse_args()


def main() -> int:
    """执行本地数据库 schema 迁移命令。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    runner = MigrationRunner(settings.storage.db_path)
    try:
        if args.apply:
            applied = runner.apply_pending()
            if args.json:
                print(json.dumps({"applied": [migration.name for migration in applied]}, ensure_ascii=False, indent=2))
            else:
                print(f"已应用 migration 数量：{len(applied)}")
                for migration in applied:
                    print(f"- {migration.version:04d} {migration.name}")
            return 0
        if args.verify:
            runner.verify()
            print("schema verify ok")
            return 0
        status = runner.status()
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            print(f"db_path: {status['db_path']}")
            print(f"applied_count: {status['applied_count']}")
            print(f"pending_count: {status['pending_count']}")
            if status["applied"]:
                print("applied:")
                for row in status["applied"]:
                    applied_at = datetime.fromtimestamp(row["applied_at"]).isoformat(timespec="seconds")
                    print(f"- {row['version']:04d} {row['name']} applied_at={applied_at}")
            if status["pending"]:
                print("pending:")
                for row in status["pending"]:
                    print(f"- {row['version']:04d} {row['name']}")
        return 0
    except MigrationError as error:
        print(f"migration failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
