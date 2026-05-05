from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.migrations import MigrationError, MigrationRunner


class MigrationRunnerTest(unittest.TestCase):
    """验证 MeetFlow SQLite schema 可以从空库和旧库安全升级。"""

    def test_new_database_applies_all_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "meetflow.sqlite"
            runner = MigrationRunner(db_path)

            applied = runner.apply_pending()
            runner.verify()

            self.assertGreaterEqual(len(applied), 5)
            status = runner.status()
            self.assertEqual(status["pending_count"], 0)

    def test_old_database_gets_missing_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "meetflow.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE task_mappings (
                        item_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        owner TEXT NOT NULL,
                        due_date TEXT NOT NULL,
                        status TEXT NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.commit()

            runner = MigrationRunner(db_path)
            runner.apply_pending()
            runner.verify()

            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(task_mappings)").fetchall()}
            self.assertIn("minute_token", columns)
            self.assertIn("evidence_refs_json", columns)
            self.assertIn("review_session_id", columns)
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workflow_jobs'"
                ).fetchone()
            self.assertIsNotNone(row)

    def test_migration_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "meetflow.sqlite"
            runner = MigrationRunner(db_path)
            first = runner.apply_pending()
            second = runner.apply_pending()

            self.assertGreaterEqual(len(first), 5)
            self.assertEqual(second, [])

    def test_verify_reports_missing_required_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "meetflow.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        applied_at INTEGER NOT NULL
                    )
                    """
                )
                conn.commit()

            with self.assertRaises(MigrationError):
                MigrationRunner(db_path).verify()


if __name__ == "__main__":
    unittest.main()
