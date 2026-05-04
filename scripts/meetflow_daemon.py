from __future__ import annotations

import argparse
import json
import select
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# 允许直接通过 `python3 scripts/meetflow_daemon.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuClient
from config import load_settings
from core import CalendarEvent, KnowledgeIndexStore, MeetFlowStorage, Resource, configure_logging, get_logger


def parse_args() -> argparse.Namespace:
    """解析 MeetFlow 后台守护进程参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "MeetFlow 后台守护进程：周期扫描日历，触发 M3 会前卡片、M4 会后卡片，"
            "并刷新已索引知识文档。支持从 lark-cli event +subscribe 管道读取事件作为实时唤醒。"
        )
    )
    parser.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取日历/文档使用的身份。")
    parser.add_argument("--calendar-id", default="primary", help="日历 ID，默认 primary。")
    parser.add_argument("--chat-id", default="", help="M4 发卡测试群；不传则使用配置 default_chat_id。")
    parser.add_argument("--poll-seconds", type=int, default=60, help="日历扫描兜底间隔。")
    parser.add_argument("--lookahead-hours", type=int, default=24, help="向后扫描日程的小时数。")
    parser.add_argument("--m3-minutes-before", type=int, default=30, help="会议开始前多少分钟发送 M3 卡片。")
    parser.add_argument("--m4-lookback-hours", type=int, default=12, help="向前扫描已结束会议的小时数。")
    parser.add_argument("--m4-delay-minutes", type=int, default=5, help="会议结束后至少等待多少分钟再查妙记。")
    parser.add_argument("--rag-refresh-seconds", type=int, default=600, help="知识文档刷新兜底间隔。")
    parser.add_argument("--rag-limit", type=int, default=20, help="每轮最多检查最近多少篇已索引文档。")
    parser.add_argument("--enable-m3", action="store_true", help="启用 M3 会前自动发卡。")
    parser.add_argument("--enable-m4", action="store_true", help="启用 M4 会后自动发卡。")
    parser.add_argument("--enable-rag", action="store_true", help="启用 RAG 文档自动刷新。")
    parser.add_argument("--event-stdin", action="store_true", help="从 stdin 读取 lark-cli event +subscribe NDJSON 事件作为实时唤醒。")
    parser.add_argument("--dry-run", action="store_true", help="只打印将触发的动作，不真正发卡或刷新索引。")
    parser.add_argument("--once", action="store_true", help="只执行一轮扫描，便于本地验证和 systemd 健康检查。")
    return parser.parse_args()


def main() -> int:
    """启动 MeetFlow 后台守护进程。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.daemon")
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(settings.feishu)
    knowledge_store = KnowledgeIndexStore(
        settings.storage,
        embedding_settings=settings.embedding,
        reranker_settings=settings.reranker,
    )
    knowledge_store.initialize()
    state = DaemonState(settings.storage.db_path)
    timezone = ZoneInfo(settings.app.timezone or "Asia/Shanghai")
    chat_id = args.chat_id or settings.feishu.default_chat_id
    if args.enable_m4 and not chat_id and not args.dry_run:
        raise SystemExit("启用 M4 自动发卡需要 --chat-id 或 feishu.default_chat_id。")

    logger.info(
        "MeetFlow daemon 启动 enable_m3=%s enable_m4=%s enable_rag=%s event_stdin=%s dry_run=%s",
        args.enable_m3,
        args.enable_m4,
        args.enable_rag,
        args.event_stdin,
        args.dry_run,
    )
    ensure_daemon_calendar_subscription(client=client, args=args, logger=logger)
    next_calendar_scan = 0.0
    next_rag_scan = 0.0
    while True:
        now = time.time()
        event_hint = read_event_hint_from_stdin(args.event_stdin, timeout=0.2)
        if event_hint:
            logger.info("收到飞书事件唤醒 type=%s", event_hint.get("type") or event_hint.get("event_type", ""))
            next_calendar_scan = 0.0
            if is_document_event(event_hint):
                enqueue_document_event_refresh(knowledge_store, event_hint, logger=logger)
                next_rag_scan = 0.0

        if (args.enable_m3 or args.enable_m4) and now >= next_calendar_scan:
            events = scan_calendar_events(client, args, timezone)
            if args.enable_m3:
                trigger_m3_due_events(events, args=args, state=state, timezone=timezone, logger=logger)
            if args.enable_m4:
                trigger_m4_finished_events(events, args=args, state=state, chat_id=chat_id, timezone=timezone, logger=logger)
            next_calendar_scan = now + max(10, int(args.poll_seconds or 60))

        if args.enable_rag and now >= next_rag_scan:
            refresh_recent_knowledge_documents(
                client=client,
                knowledge_store=knowledge_store,
                args=args,
                logger=logger,
            )
            next_rag_scan = now + max(60, int(args.rag_refresh_seconds or 600))

        if args.once:
            return 0
        time.sleep(0.8)


def ensure_daemon_calendar_subscription(client: FeishuClient, args: argparse.Namespace, logger: Any) -> None:
    """启动后台服务时订阅日程变更事件。

    飞书的 `calendar.calendar.event.changed_v4` 需要先对具体日历调用订阅接口；
    否则长连接即使已建立，也不会收到该日历下新增/修改日程的事件。
    """

    if not (args.enable_m3 or args.enable_m4):
        return
    try:
        client.subscribe_calendar_event_changes(
            calendar_id=args.calendar_id,
            identity=args.identity,  # type: ignore[arg-type]
        )
        logger.info("已确保日程变更订阅 calendar_id=%s identity=%s", args.calendar_id, args.identity)
    except FeishuAPIError as error:
        logger.warning("订阅日程变更失败，后台将依赖定时扫描兜底 calendar_id=%s error=%s", args.calendar_id, error)


class DaemonState:
    """用 JSON 文件记录后台守护进程已处理事件。

    状态和业务存储分开，便于清理 daemon 的扫描水位而不影响 workflow 运行记录。
    """

    def __init__(self, db_path: str) -> None:
        self.path = Path(db_path).parent / "meetflow_daemon_state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"processed": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"processed": {}}

    def has(self, key: str) -> bool:
        """判断某个后台动作是否已处理。"""

        return key in dict(self.data.get("processed") or {})

    def mark(self, key: str, payload: dict[str, Any]) -> None:
        """记录某个后台动作已经处理。"""

        processed = dict(self.data.get("processed") or {})
        processed[key] = {"updated_at": int(time.time()), **payload}
        self.data["processed"] = processed
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_event_hint_from_stdin(enabled: bool, timeout: float) -> dict[str, Any]:
    """从 lark-cli event +subscribe 的 NDJSON 中读取一条事件。

    事件只作为唤醒信号，业务详情仍通过项目自己的 FeishuClient/工具链读取，
    避免直接信任事件 payload 中不完整或权限受限的字段。
    """

    if not enabled:
        time.sleep(timeout)
        return {}
    readable, _, _ = select.select([sys.stdin], [], [], timeout)
    if not readable:
        return {}
    line = sys.stdin.readline()
    if not line:
        return {}
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {}


def scan_calendar_events(client: FeishuClient, args: argparse.Namespace, timezone: ZoneInfo) -> list[CalendarEvent]:
    """扫描最近已结束和即将开始的日程实例。"""

    now = datetime.now(timezone)
    start = now - timedelta(hours=max(1, int(args.m4_lookback_hours or 12)))
    end = now + timedelta(hours=max(1, int(args.lookahead_hours or 24)))
    return client.list_calendar_event_instances(
        calendar_id=args.calendar_id,
        start_time=str(int(start.timestamp())),
        end_time=str(int(end.timestamp())),
        identity=args.identity,  # type: ignore[arg-type]
    )


def trigger_m3_due_events(
    events: list[CalendarEvent],
    *,
    args: argparse.Namespace,
    state: DaemonState,
    timezone: ZoneInfo,
    logger: Any,
) -> None:
    """对进入会前窗口的日程触发 M3 发卡。"""

    now_ts = int(datetime.now(timezone).timestamp())
    window_seconds = max(0, int(args.m3_minutes_before or 30)) * 60
    for event in events:
        start_ts = parse_event_timestamp(event.start_time)
        if start_ts <= 0:
            continue
        due_in = start_ts - now_ts
        if due_in < 0 or due_in > window_seconds:
            continue
        key = f"m3:{event.event_id}:{args.m3_minutes_before}"
        if state.has(key):
            continue
        command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "card_send_live.py"),
            "m3",
            "--identity",
            args.identity,
            "--calendar-id",
            args.calendar_id,
            "--event-id",
            event.event_id,
            "--idempotency-suffix",
            f"daemon-{int(time.time())}",
        ]
        run_command(command, dry_run=args.dry_run, logger=logger, action="m3")
        state.mark(key, {"summary": event.summary, "start_time": event.start_time})


def trigger_m4_finished_events(
    events: list[CalendarEvent],
    *,
    args: argparse.Namespace,
    state: DaemonState,
    chat_id: str,
    timezone: ZoneInfo,
    logger: Any,
) -> None:
    """对已结束会议查询妙记并触发 M4 发卡。"""

    now_ts = int(datetime.now(timezone).timestamp())
    delay_seconds = max(0, int(args.m4_delay_minutes or 5)) * 60
    for event in events:
        end_ts = parse_event_timestamp(event.end_time)
        if end_ts <= 0 or now_ts - end_ts < delay_seconds:
            continue
        key = f"m4:{event.event_id}"
        if state.has(key):
            continue
        minute_token = query_minute_token_by_calendar_event_id(event.event_id, logger=logger)
        if not minute_token:
            logger.info("会议暂未生成可用妙记 event_id=%s summary=%s", event.event_id, event.summary)
            continue
        command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "card_send_live.py"),
            "m4",
            "--identity",
            "user",
            "--minute",
            minute_token,
            "--chat-id",
            chat_id,
        ]
        run_command(command, dry_run=args.dry_run, logger=logger, action="m4")
        state.mark(key, {"summary": event.summary, "minute_token": minute_token})


def query_minute_token_by_calendar_event_id(event_id: str, logger: Any) -> str:
    """通过 VC 录制桥接命令从日程 event_id 查询 minute_token。"""

    command = [
        "lark-cli",
        "vc",
        "+recording",
        "--calendar-event-ids",
        event_id,
        "--format",
        "json",
        "--as",
        "user",
    ]
    try:
        result = subprocess.run(command, cwd=PROJECT_ROOT, check=False, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.warning("查询会议录制失败 event_id=%s error=%s", event_id, error)
        return ""
    if result.returncode != 0:
        logger.info("会议录制暂不可用 event_id=%s stderr=%s", event_id, result.stderr.strip()[:300])
        return ""
    return extract_minute_token_from_recording_json(result.stdout)


def extract_minute_token_from_recording_json(text: str) -> str:
    """从 vc +recording 输出中提取第一条可用 minute_token。"""

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ""
    candidates: list[Any] = []
    if isinstance(data, dict):
        candidates.extend(data.get("recordings") or [])
        candidates.extend(data.get("items") or [])
        if isinstance(data.get("data"), dict):
            candidates.extend(data["data"].get("recordings") or [])
            candidates.extend(data["data"].get("items") or [])
    for item in candidates:
        if not isinstance(item, dict):
            continue
        token = str(item.get("minute_token") or "").strip()
        if token:
            return token
        url = str(item.get("recording_url") or "").strip()
        marker = "/minutes/"
        if marker in url:
            return url.split(marker, 1)[1].split("?", 1)[0].strip("/")
    return ""


def refresh_recent_knowledge_documents(
    *,
    client: FeishuClient,
    knowledge_store: KnowledgeIndexStore,
    args: argparse.Namespace,
    logger: Any,
) -> None:
    """对最近索引过的文档做增量刷新兜底。"""

    process_pending_index_jobs(client=client, knowledge_store=knowledge_store, args=args, logger=logger)
    jobs = knowledge_store.enqueue_recent_document_refresh_jobs(limit=max(1, int(args.rag_limit or 20)))
    for job in jobs:
        if args.dry_run:
            logger.info("dry-run: 将刷新知识文档 resource_id=%s source_url=%s", job.resource_id, job.source_url)
            continue
        resource = fetch_resource_for_index_job(client, job.resource_type, job.source_url or job.resource_id, args.identity)
        if not resource:
            logger.info("跳过暂不支持自动拉取的知识资源 resource_id=%s type=%s", job.resource_id, job.resource_type)
            continue
        try:
            knowledge_store.refresh_resource(resource, reason="daemon", force=False)
        except Exception as error:  # noqa: BLE001 - daemon 不能因单篇文档失败退出。
            logger.warning("刷新知识文档失败 resource_id=%s error=%s", job.resource_id, error)


def process_pending_index_jobs(
    *,
    client: FeishuClient,
    knowledge_store: KnowledgeIndexStore,
    args: argparse.Namespace,
    logger: Any,
) -> None:
    """优先处理长连接事件写入的 pending index_jobs。"""

    pending_jobs = knowledge_store.list_index_jobs(status="pending", limit=max(1, int(args.rag_limit or 20)))
    for job in pending_jobs:
        job_id = str(job.get("job_id") or "")
        resource_id = str(job.get("resource_id") or "")
        resource_type = str(job.get("resource_type") or "")
        source_url = str(job.get("source_url") or "")
        if args.dry_run:
            logger.info("dry-run: 将处理事件刷新任务 job_id=%s resource_id=%s", job_id, resource_id)
            continue
        knowledge_store.update_index_job_status(job_id, status="running")
        try:
            resource = fetch_resource_for_index_job(client, resource_type, source_url or resource_id, args.identity)
            if not resource:
                knowledge_store.update_index_job_status(job_id, status="failed", last_error="unsupported_resource_type")
                continue
            index_result = knowledge_store.index_resource(resource, force=False)
            content_tokens = sum(chunk.content_tokens for chunk in index_result.chunks)
            knowledge_store.update_index_job_status(
                job_id,
                status="succeeded" if not index_result.skipped else "skipped",
                chunk_count=index_result.document.chunk_count,
                content_tokens=content_tokens,
            )
        except Exception as error:  # noqa: BLE001 - 单个事件任务失败不能拖垮 daemon。
            knowledge_store.update_index_job_status(job_id, status="failed", last_error=str(error))
            logger.warning("处理事件刷新任务失败 job_id=%s resource_id=%s error=%s", job_id, resource_id, error)


def enqueue_document_event_refresh(knowledge_store: KnowledgeIndexStore, event: dict[str, Any], logger: Any) -> None:
    """长连接收到云文档事件后，优先为对应文档写入刷新任务。"""

    file_token = extract_event_file_token(event)
    file_type = extract_event_file_type(event)
    if not file_token:
        logger.info("文档事件缺少 file_token，等待定时扫描兜底 event=%s", event)
        return
    subscription = knowledge_store.get_event_subscription(file_token)
    resource_type = file_type or "docx"
    source_url = ""
    title = ""
    if subscription:
        resource_type = str(subscription.get("resource_type") or resource_type)
        source_url = str(subscription.get("source_url") or "")
    job = knowledge_store.enqueue_index_job(
        resource_id=file_token,
        resource_type=resource_type,
        reason="event",
        source_url=source_url,
        payload={
            "title": title,
            "file_token": file_token,
            "file_type": file_type,
            "event_type": str(event.get("type") or event.get("event_type") or ""),
        },
    )
    logger.info("已根据文档事件写入刷新任务 job_id=%s file_token=%s", job.job_id, file_token)


def extract_event_file_token(event: dict[str, Any]) -> str:
    """从 compact/raw 飞书文档事件中提取 file_token。"""

    for key in ("file_token", "resource_id", "token"):
        value = event.get(key)
        if value:
            return str(value).strip()
    nested_event = event.get("event")
    if isinstance(nested_event, dict):
        for key in ("file_token", "resource_id", "token"):
            value = nested_event.get(key)
            if value:
                return str(value).strip()
    header = event.get("header")
    if isinstance(header, dict):
        value = header.get("resource_id")
        if value:
            return str(value).strip()
    return ""


def extract_event_file_type(event: dict[str, Any]) -> str:
    """从 compact/raw 飞书文档事件中提取 file_type。"""

    for key in ("file_type", "type"):
        value = event.get(key)
        if value and key == "file_type":
            return str(value).strip()
    nested_event = event.get("event")
    if isinstance(nested_event, dict):
        value = nested_event.get("file_type")
        if value:
            return str(value).strip()
    return ""


def fetch_resource_for_index_job(client: FeishuClient, resource_type: str, source: str, identity: str) -> Resource | None:
    """按资源类型重新拉取文档内容供索引刷新。"""

    normalized = str(resource_type or "").lower()
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
    return None


def is_document_event(event: dict[str, Any]) -> bool:
    """判断事件是否可能意味着知识文档变化。"""

    event_type = str(event.get("type") or event.get("event_type") or "")
    return event_type.startswith(("drive.", "docx.", "wiki.", "sheet.", "bitable."))


def parse_event_timestamp(value: Any) -> int:
    """解析秒级、毫秒级或日期字符串。"""

    raw = str(value or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        timestamp = int(raw)
        return timestamp // 1000 if timestamp > 10_000_000_000 else timestamp
    try:
        return int(datetime.fromisoformat(raw).timestamp())
    except ValueError:
        return 0


def run_command(command: list[str], *, dry_run: bool, logger: Any, action: str) -> None:
    """执行后台触发命令。"""

    logger.info("触发后台动作 action=%s command=%s", action, " ".join(command))
    if dry_run:
        return
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False, text=True)
    if result.returncode != 0:
        logger.warning("后台动作失败 action=%s returncode=%s", action, result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
