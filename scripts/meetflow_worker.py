from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/meetflow_worker.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuClient
from config import load_settings
from core.agent import create_meetflow_agent
from core.jobs import JobQueue, JobRecord, is_retryable_error
from core.knowledge import KnowledgeIndexStore
from core.llm import DryRunLLMProvider
from core.logging import configure_logging, get_logger
from core.models import AgentInput, Resource
from core.observability import configure_structured_events, duration_ms_since, safe_error_message
from core.storage import MeetFlowStorage


def parse_args() -> argparse.Namespace:
    """解析 MeetFlow worker 参数。"""

    parser = argparse.ArgumentParser(description="MeetFlow 后台任务 worker。")
    parser.add_argument("--queues", default="workflow,risk_scan,rag_refresh", help="逗号分隔的队列名。")
    parser.add_argument("--worker-id", default="", help="worker 标识；不传使用配置 jobs.worker_id。")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="无任务时的轮询间隔。")
    parser.add_argument("--once", action="store_true", help="只领取并处理一次，到期任务为空也退出。")
    parser.add_argument("--dry-run", action="store_true", help="只查看 pending job，不领取、不执行。")
    parser.add_argument("--max-jobs", type=int, default=0, help="最多处理多少条任务；0 表示不限制。")
    parser.add_argument("--lock-seconds", type=int, default=0, help="单条任务锁租约秒数；不传使用配置。")
    return parser.parse_args()


def main() -> int:
    """启动后台任务 worker。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    configure_structured_events(settings.observability)
    logger = get_logger("meetflow.worker")
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    queue = JobQueue(settings.storage)
    queues = parse_queues(args.queues or settings.jobs.default_queue)
    worker_id = args.worker_id or settings.jobs.worker_id or f"meetflow-worker-{int(time.time())}"
    lock_seconds = args.lock_seconds or settings.jobs.lock_seconds

    if args.dry_run:
        pending = [job for job in queue.list_jobs(status="pending", limit=20) if job.queue_name in queues]
        print(
            json.dumps(
                {
                    "worker_id": worker_id,
                    "queues": queues,
                    "pending_count": len(pending),
                    "pending": [summarize_job(job) for job in pending],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    logger.info("MeetFlow worker 启动 worker_id=%s queues=%s once=%s", worker_id, ",".join(queues), args.once)
    processed = 0
    while True:
        job = queue.claim_due_job(worker_id=worker_id, queues=queues, lock_seconds=lock_seconds)
        if job is None:
            if args.once:
                logger.info("没有到期任务，worker 退出。")
                return 0
            time.sleep(max(float(args.poll_seconds or 2.0), 0.2))
            continue
        processed += 1
        process_job(queue=queue, job=job, settings=settings, logger=logger)
        if args.once or (args.max_jobs and processed >= args.max_jobs):
            return 0


def process_job(*, queue: JobQueue, job: JobRecord, settings: Any, logger: Any) -> None:
    """执行一条 job，并按错误类型更新任务状态。"""

    started_at = time.perf_counter()
    try:
        result = dispatch_job(job=job, settings=settings, logger=logger)
        result["duration_ms"] = duration_ms_since(started_at)
        queue.mark_succeeded(job.job_id, result=result)
    except Exception as error:  # noqa: BLE001 - worker 需要捕获单条任务失败并写入队列表。
        logger.exception("任务执行失败 job_id=%s job_type=%s error=%s", job.job_id, job.job_type, safe_error_message(error))
        if is_retryable_error(error):
            queue.mark_retry(
                job.job_id,
                error=error,
                retry_base_seconds=settings.jobs.retry_base_seconds,
                retry_max_seconds=settings.jobs.retry_max_seconds,
                dead_letter_after_attempts=settings.jobs.dead_letter_after_attempts,
            )
        else:
            queue.mark_failed(job.job_id, error=error)


def dispatch_job(*, job: JobRecord, settings: Any, logger: Any) -> dict[str, Any]:
    """按 job_type 分发到现有 MeetFlow 业务入口。"""

    if job.job_type == "agent_input.run":
        return run_agent_input_job(job, settings=settings)
    if job.job_type == "pre_meeting.send_card":
        return run_subprocess_job(build_pre_meeting_command(job.payload), logger=logger)
    if job.job_type == "post_meeting.send_cards":
        return run_subprocess_job(build_post_meeting_command(job.payload, settings=settings), logger=logger)
    if job.job_type == "risk_scan.run":
        return run_subprocess_job(build_risk_scan_command(job.payload), logger=logger)
    if job.job_type == "rag_refresh.document":
        return run_rag_refresh_job(job.payload, settings=settings)
    raise ValueError(f"不支持的 job_type：{job.job_type}")


def run_agent_input_job(job: JobRecord, *, settings: Any) -> dict[str, Any]:
    """执行由卡片回调产生的 AgentInput。"""

    raw_agent_input = job.payload.get("agent_input")
    if not isinstance(raw_agent_input, dict):
        raise ValueError("agent_input.run 缺少 agent_input payload")
    agent_input = AgentInput(**raw_agent_input)
    agent_provider = str(job.payload.get("agent_provider") or "dry-run")
    llm_provider = DryRunLLMProvider() if agent_provider == "dry-run" else None
    agent = create_meetflow_agent(settings, llm_provider=llm_provider)
    result = agent.run(agent_input, allow_write=bool(job.payload.get("allow_write", False)))
    return {
        "trace_id": result.trace_id,
        "workflow_name": result.workflow_name,
        "status": result.status,
        "summary": result.summary,
    }


def run_rag_refresh_job(payload: dict[str, Any], *, settings: Any) -> dict[str, Any]:
    """刷新单篇知识资源索引。"""

    resource_type = str(payload.get("resource_type") or payload.get("file_type") or "docx")
    source = str(payload.get("source_url") or payload.get("resource_id") or payload.get("doc_token") or "").strip()
    if not source:
        raise ValueError("rag_refresh.document 缺少 source_url/resource_id/doc_token")
    identity = str(payload.get("identity") or "user")
    client = FeishuClient(settings.feishu)
    store = KnowledgeIndexStore(
        settings.storage,
        embedding_settings=settings.embedding,
        reranker_settings=settings.reranker,
    )
    store.initialize()
    resource = fetch_resource(client=client, resource_type=resource_type, source=source, identity=identity)
    index_job_id = str(payload.get("index_job_id") or "").strip()
    if index_job_id:
        store.update_index_job_status(index_job_id, status="running")
    result = store.refresh_resource(resource, reason=str(payload.get("reason") or "worker"), force=bool(payload.get("force_index", False)))
    if index_job_id:
        status = "skipped" if result.skipped else "succeeded"
        content_tokens = sum(chunk.content_tokens for chunk in result.chunks)
        store.update_index_job_status(
            index_job_id,
            status=status,
            chunk_count=result.document.chunk_count,
            content_tokens=content_tokens,
        )
    return {"resource_id": resource.resource_id, "resource_type": resource.resource_type, "index_result": result.to_dict()}


def fetch_resource(*, client: FeishuClient, resource_type: str, source: str, identity: str) -> Resource:
    """按资源类型拉取飞书资源，供 RAG 刷新 job 使用。"""

    normalized = resource_type.lower()
    if normalized in {"doc", "docx", "wiki", "document"}:
        return client.fetch_document_resource(
            document=source,
            doc_format="xml",
            detail="simple",
            scope="full",
            identity=identity,  # type: ignore[arg-type]
        )
    if normalized in {"minute", "minutes", "feishu_minute"}:
        return client.fetch_minute_resource(
            minute=source,
            include_artifacts=True,
            identity=identity,  # type: ignore[arg-type]
        )
    raise ValueError(f"暂不支持自动刷新资源类型：{resource_type}")


def build_pre_meeting_command(payload: dict[str, Any]) -> list[str]:
    """把 M3 job payload 转换为现有统一发卡命令。"""

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "card_send_live.py"),
        "m3",
        "--identity",
        str(payload.get("identity") or "user"),
        "--calendar-id",
        str(payload.get("calendar_id") or "primary"),
        "--llm-provider",
        str(payload.get("llm_provider") or "scripted_debug"),
        "--idempotency-suffix",
        str(payload.get("idempotency_suffix") or f"worker-{int(time.time())}"),
    ]
    extend_if_present(command, "--event-id", payload.get("event_id"))
    extend_if_present(command, "--event-title", payload.get("event_title"))
    extend_if_present(command, "--date", payload.get("date"))
    extend_if_present(command, "--project-id", payload.get("project_id"))
    for doc in payload.get("docs") or payload.get("doc") or []:
        extend_if_present(command, "--doc", doc)
    for minute in payload.get("minutes") or payload.get("minute") or []:
        extend_if_present(command, "--minute", minute)
    if payload.get("force_index"):
        command.append("--force-index")
    if payload.get("write_report"):
        command.append("--write-report")
    return command


def build_post_meeting_command(payload: dict[str, Any], *, settings: Any) -> list[str]:
    """把 M4 job payload 转换为现有统一发卡命令。"""

    minute = str(payload.get("minute") or payload.get("minute_url") or payload.get("minute_token") or "").strip()
    if not minute:
        raise ValueError("post_meeting.send_cards 缺少 minute")
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "card_send_live.py"),
        "m4",
        "--minute",
        minute,
        "--identity",
        str(payload.get("identity") or "user"),
        "--chat-id",
        str(payload.get("chat_id") or settings.feishu.default_chat_id),
    ]
    if payload.get("show_card_json"):
        command.append("--show-card-json")
    if payload.get("skip_related_knowledge"):
        command.append("--skip-related-knowledge")
    return command


def build_risk_scan_command(payload: dict[str, Any]) -> list[str]:
    """把 M5 job payload 转换为风险巡检命令。"""

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "risk_scan_demo.py"),
        "--backend",
        str(payload.get("backend") or "local"),
    ]
    for key, option in {
        "chat_id": "--chat-id",
        "identity": "--identity",
        "send_identity": "--send-identity",
        "completed": "--completed",
    }.items():
        extend_if_present(command, option, payload.get(key))
    for key, option in {
        "page_size": "--page-size",
        "page_limit": "--page-limit",
        "stale_update_days": "--stale-update-days",
        "due_soon_hours": "--due-soon-hours",
        "max_reminders": "--max-reminders",
    }.items():
        extend_if_present(command, option, payload.get(key))
    if payload.get("show_card"):
        command.append("--show-card")
    if payload.get("allow_write"):
        command.append("--allow-write")
    return command


def run_subprocess_job(command: list[str], *, logger: Any) -> dict[str, Any]:
    """执行兼容旧链路的子进程命令。"""

    logger.info("执行 job 子命令 command=%s", " ".join(command))
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"子命令执行失败 returncode={result.returncode} message={message[:1000]}")
    return {
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "")[-2000:],
        "stderr_tail": (result.stderr or "")[-1000:],
    }


def extend_if_present(command: list[str], option: str, value: Any) -> None:
    """有值时追加命令行参数。"""

    if value is None or value == "":
        return
    command.extend([option, str(value)])


def parse_queues(value: str) -> list[str]:
    """解析逗号分隔队列名。"""

    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def summarize_job(job: JobRecord) -> dict[str, Any]:
    """生成 dry-run 可展示的任务摘要，不输出完整 payload。"""

    return {
        "job_id": job.job_id,
        "queue_name": job.queue_name,
        "job_type": job.job_type,
        "status": job.status,
        "attempts": job.attempts,
        "available_at": job.available_at,
        "payload_keys": sorted(job.payload.keys()),
    }


if __name__ == "__main__":
    raise SystemExit(main())
