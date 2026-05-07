from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from config import StorageSettings
from core.jobs import JobQueue, build_job_id, compute_retry_delay


def make_storage(temp_dir: str) -> StorageSettings:
    """构造隔离的测试存储配置。"""

    root = Path(temp_dir)
    return StorageSettings(
        db_path=str(root / "meetflow.sqlite"),
        project_memory_dir=str(root / "projects"),
        audit_log_path=str(root / "workflow_runs.jsonl"),
    )


class JobQueueTest(unittest.TestCase):
    """验证 SQLite job queue 的幂等、领取和重试状态。"""

    def test_enqueue_creates_pending_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = JobQueue(make_storage(temp_dir))

            job = queue.enqueue(
                queue_name="workflow",
                job_type="pre_meeting.send_card",
                payload={"event_id": "event_test"},
                idempotency_key="m3:event_test",
            )

            self.assertEqual(job.status, "pending")
            self.assertEqual(job.queue_name, "workflow")
            self.assertEqual(job.payload["event_id"], "event_test")

    def test_enqueue_same_idempotency_key_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = JobQueue(make_storage(temp_dir))

            first = queue.enqueue(
                queue_name="workflow",
                job_type="post_meeting.send_cards",
                payload={"minute": "minute_1"},
                idempotency_key="m4:event_1",
            )
            second = queue.enqueue(
                queue_name="workflow",
                job_type="post_meeting.send_cards",
                payload={"minute": "minute_1"},
                idempotency_key="m4:event_1",
            )

            self.assertEqual(first.job_id, second.job_id)
            self.assertEqual(len(queue.list_jobs()), 1)

    def test_claim_due_job_locks_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = JobQueue(make_storage(temp_dir))
            job = queue.enqueue(
                queue_name="workflow",
                job_type="risk_scan.run",
                payload={"backend": "local"},
                idempotency_key="risk:local",
            )

            claimed = queue.claim_due_job(worker_id="worker_1", queues=["workflow"], lock_seconds=60)

            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertEqual(claimed.job_id, job.job_id)
            self.assertEqual(claimed.status, "running")
            self.assertEqual(claimed.locked_by, "worker_1")
            self.assertEqual(claimed.attempts, 1)

    def test_mark_retry_sets_available_at(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = JobQueue(make_storage(temp_dir))
            job = queue.enqueue(
                queue_name="workflow",
                job_type="agent_input.run",
                payload={"agent_input": {}},
                idempotency_key="agent:1",
                max_attempts=3,
            )
            claimed = queue.claim_due_job(worker_id="worker_1", queues=["workflow"])
            assert claimed is not None

            before = int(time.time())
            retried = queue.mark_retry(
                job.job_id,
                error=TimeoutError("timeout"),
                retry_base_seconds=30,
                retry_max_seconds=600,
            )

            self.assertEqual(retried.status, "retrying")
            self.assertGreaterEqual(retried.available_at, before + 30)
            self.assertEqual(retried.locked_by, "")

    def test_mark_failed_after_max_attempts_goes_dead_letter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = JobQueue(make_storage(temp_dir))
            job = queue.enqueue(
                queue_name="workflow",
                job_type="agent_input.run",
                payload={"agent_input": {}},
                idempotency_key="agent:dead",
                max_attempts=1,
            )
            claimed = queue.claim_due_job(worker_id="worker_1", queues=["workflow"])
            assert claimed is not None

            dead = queue.mark_retry(job.job_id, error=TimeoutError("timeout"))

            self.assertEqual(dead.status, "dead_letter")

    def test_build_job_id_and_retry_delay_are_stable(self) -> None:
        first = build_job_id(queue_name="workflow", job_type="x", idempotency_key="k", payload={"b": 1})
        second = build_job_id(queue_name="workflow", job_type="x", idempotency_key="k", payload={"b": 1})

        self.assertEqual(first, second)
        self.assertEqual(compute_retry_delay(1, base_seconds=30, max_seconds=600), 30)
        self.assertEqual(compute_retry_delay(2, base_seconds=30, max_seconds=600), 120)


if __name__ == "__main__":
    unittest.main()
