from __future__ import annotations

import argparse
import importlib.util
import json
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

# 允许直接通过 `python3 scripts/live_environment_watch.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuClient
from config import load_settings
from core import KnowledgeIndexStore, MeetFlowStorage, configure_logging
from scripts.meetflow_agent_live_test import save_token_bundle
from scripts.meetflow_daemon import (
    DaemonState,
    enqueue_document_event_refresh,
    extract_event_file_token,
    extract_event_file_type,
    fetch_resource_for_index_job,
    is_document_event,
    scan_calendar_events,
    trigger_m3_due_events,
    trigger_m4_finished_events,
)
from scripts.pre_meeting_live_test import ensure_rag_event_subscription


DEFAULT_EVENT_TYPES = [
    "calendar.calendar.event.changed_v4",
    "drive.file.edit_v1",
    "drive.file.title_updated_v1",
    "drive.file.bitable_record_changed_v1",
    "drive.file.bitable_field_changed_v1",
]


def parse_args() -> argparse.Namespace:
    """解析真实环境观察脚本参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "MeetFlow 真实环境观察台：启动飞书长连接，清晰打印云文档/日程事件，"
            "并展示 RAG 刷新、M3/M4 卡片触发结果。"
        )
    )
    parser.add_argument("--doc", action="append", default=[], help="先加入并订阅的飞书文档 URL，可重复传。")
    parser.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取日历/文档使用的身份。")
    parser.add_argument("--calendar-id", default="primary", help="日历 ID，默认 primary。")
    parser.add_argument("--chat-id", default="", help="M4 发卡测试群；不传则使用配置 default_chat_id。")
    parser.add_argument("--duration-seconds", type=int, default=0, help="观察时长；0 表示一直运行。")
    parser.add_argument("--poll-seconds", type=int, default=60, help="没有事件时的兜底扫描间隔。")
    parser.add_argument("--lookahead-hours", type=int, default=24, help="向后扫描日程的小时数。")
    parser.add_argument("--m3-minutes-before", type=int, default=30, help="会议开始前多少分钟触发 M3。")
    parser.add_argument("--m4-lookback-hours", type=int, default=12, help="向前扫描已结束会议的小时数。")
    parser.add_argument("--m4-delay-minutes", type=int, default=5, help="会议结束后至少等待多少分钟再查妙记。")
    parser.add_argument("--rag-limit", type=int, default=20, help="每轮最多处理多少条 RAG 索引任务。")
    parser.add_argument("--event-types", default=",".join(DEFAULT_EVENT_TYPES), help="传给 lark-cli 的事件类型列表。")
    parser.add_argument("--python-bin", default="", help="RAG/MeetFlow 主进程使用的 Python；不传时自动寻找包含 chromadb 和 sentence_transformers 的解释器。")
    parser.add_argument("--lark-cli-bin", default="", help="lark-cli 可执行文件路径；不传时使用 PATH 中的 lark-cli。")
    parser.add_argument("--skip-lark-cli-app-check", action="store_true", help="跳过 lark-cli app_id 与项目配置一致性检查。")
    parser.add_argument("--force-subscribe", action="store_true", help="给 lark-cli event +subscribe 追加 --force，用于处理上次异常退出后的单实例锁。")
    parser.add_argument("--enable-m3", action="store_true", help="收到日程事件或兜底扫描时检查 M3。")
    parser.add_argument("--enable-m4", action="store_true", help="收到日程事件或兜底扫描时检查 M4。")
    parser.add_argument("--enable-rag", action="store_true", default=True, help="启用 RAG 事件刷新。")
    parser.add_argument("--no-rag", action="store_true", help="禁用 RAG 事件刷新。")
    parser.add_argument("--allow-card-send", action="store_true", help="允许脚本真实发送 M3/M4 卡片。默认只打印将发卡。")
    parser.add_argument("--dry-run-rag", action="store_true", help="RAG 也只打印任务，不实际刷新本地索引。")
    parser.add_argument("--process-existing-rag-jobs", action="store_true", help="处理启动前已经存在的 pending RAG 任务；默认跳过历史任务，避免 demo 数据刷屏。")
    parser.add_argument("--skip-subscribe", action="store_true", help="传 --doc 时只索引，不调用云文档事件订阅接口。")
    parser.add_argument("--skip-calendar-subscribe", action="store_true", help="不自动调用飞书日程变更订阅接口。")
    parser.add_argument("--as-bot", default="bot", choices=["bot"], help="长连接固定使用 bot 身份。")
    return parser.parse_args()


def main() -> int:
    """启动真实环境观察台。"""

    args = parse_args()
    if args.no_rag:
        args.enable_rag = False
    relaunch_with_rag_python_if_needed(args)

    settings = load_settings()
    configure_logging(settings.logging)
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(settings.feishu, user_token_callback=lambda bundle: save_token_bundle(settings, bundle))
    knowledge_store = KnowledgeIndexStore(
        settings.storage,
        embedding_settings=settings.embedding,
        reranker_settings=settings.reranker,
        search_settings=settings.knowledge_search,
    )
    knowledge_store.initialize()
    timezone = ZoneInfo(settings.app.timezone or "Asia/Shanghai")
    state = DaemonState(settings.storage.db_path)
    chat_id = args.chat_id or settings.feishu.default_chat_id
    ensure_lark_cli_app_matches(args, settings.feishu.app_id)

    print_banner(args)
    watch_started_at = int(time.time())
    register_initial_documents(args, client, knowledge_store)
    ensure_calendar_event_subscription(args, client)
    print_subscription_snapshot(knowledge_store)

    process = start_lark_event_subscriber(args.event_types, args.lark_cli_bin, force=args.force_subscribe)
    card_args = build_daemon_args(args, dry_run=not args.allow_card_send)
    rag_args = build_daemon_args(args, dry_run=args.dry_run_rag)
    next_scan_at = 0.0
    event_count = 0
    started_at = time.time()
    try:
        while True:
            if args.duration_seconds > 0 and time.time() - started_at >= args.duration_seconds:
                print_step("完成", f"达到观察时长 {args.duration_seconds}s，准备退出。")
                return 0

            for stream_name, line in read_process_lines(process, timeout=0.5):
                if stream_name == "stderr":
                    print_lark_cli_line(line)
                    continue
                event = parse_event_line(line)
                if not event:
                    continue
                event_count += 1
                handle_event(
                    event=event,
                    event_count=event_count,
                    args=args,
                    card_args=card_args,
                    rag_args=rag_args,
                    client=client,
                    knowledge_store=knowledge_store,
                    state=state,
                    timezone=timezone,
                    chat_id=chat_id,
                    watch_started_at=watch_started_at,
                )
                next_scan_at = time.time() + max(10, int(args.poll_seconds or 60))

            if process.poll() is not None:
                print_remaining_process_output(process)
                print_step("异常", f"lark-cli 长连接进程已退出 returncode={process.returncode}")
                return int(process.returncode or 1)

            if time.time() >= next_scan_at:
                run_fallback_scan(
                    args=args,
                    card_args=card_args,
                    rag_args=rag_args,
                    client=client,
                    knowledge_store=knowledge_store,
                    state=state,
                    timezone=timezone,
                    chat_id=chat_id,
                    watch_started_at=watch_started_at,
                )
                next_scan_at = time.time() + max(10, int(args.poll_seconds or 60))
    except KeyboardInterrupt:
        print_step("退出", "收到 Ctrl+C，正在关闭长连接。")
        return 0
    finally:
        stop_process(process)


def print_banner(args: argparse.Namespace) -> None:
    """打印启动配置，方便联调时确认脚本处于正确模式。"""

    card_mode = "真实发卡" if args.allow_card_send else "只观察发卡意图"
    rag_mode = "只打印" if args.dry_run_rag else "真实刷新本地索引"
    print("\n=== MeetFlow 真实环境观察台 ===")
    print(f"- 事件类型: {args.event_types}")
    print(f"- RAG: {'开启' if args.enable_rag else '关闭'}，{rag_mode}")
    print(f"- M3: {'开启' if args.enable_m3 else '关闭'}")
    print(f"- M4: {'开启' if args.enable_m4 else '关闭'}")
    print(f"- 卡片动作: {card_mode}")
    print(f"- 历史 RAG pending 任务: {'处理' if args.process_existing_rag_jobs else '跳过'}")
    print(f"- 长连接 force: {'开启' if args.force_subscribe else '关闭'}")
    print("- 操作提示: 运行后可以在飞书里编辑已订阅云文档、修改文档标题、添加/修改日程。")
    print("")


def ensure_lark_cli_app_matches(args: argparse.Namespace, expected_app_id: str) -> None:
    """确认长连接使用的 app_id 与项目 API 配置一致。

    云文档/日历订阅接口由 `FeishuClient` 按 `settings.feishu.app_id` 调用；
    长连接事件则由 `lark-cli` 按自己的全局配置建连。两者一旦不是同一个应用，
    飞书会把事件投递给订阅关系所属应用，而观察台连在另一个应用上，自然收不到。
    """

    if args.skip_lark_cli_app_check:
        return
    if not expected_app_id:
        return
    executable = resolve_lark_cli_bin(args.lark_cli_bin)
    try:
        completed = subprocess.run(
            [executable, "config", "show"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as error:
        raise SystemExit(f"无法读取 lark-cli 配置：{error}") from error
    output = completed.stdout or ""
    actual_app_id = extract_lark_cli_app_id(output)
    if not actual_app_id:
        raise SystemExit(
            "无法从 `lark-cli config show` 解析 appId。请先运行：\n"
            "python3 scripts/sync_lark_cli_config.py --yes"
        )
    if actual_app_id != expected_app_id:
        raise SystemExit(
            "lark-cli 长连接使用的 app_id 与项目配置不一致，长连接不会收到本项目订阅的事件。\n"
            f"- 项目 settings.feishu.app_id: {expected_app_id}\n"
            f"- lark-cli 当前 app_id: {actual_app_id}\n\n"
            "请先同步 lark-cli 配置：\n"
            "python3 scripts/sync_lark_cli_config.py --yes\n\n"
            "同步后再运行观察台。"
        )
    print_step("配置检查", f"lark-cli app_id 与项目一致: {actual_app_id}")


def extract_lark_cli_app_id(output: str) -> str:
    """从 `lark-cli config show` 输出中提取 appId。"""

    try:
        start = output.index("{")
        data, _ = json.JSONDecoder().raw_decode(output[start:])
        value = data.get("appId") if isinstance(data, dict) else ""
        return str(value or "").strip()
    except (ValueError, json.JSONDecodeError):
        return ""


def register_initial_documents(
    args: argparse.Namespace,
    client: FeishuClient,
    knowledge_store: KnowledgeIndexStore,
) -> None:
    """把命令行传入的文档先纳入 RAG，并按需订阅云文档事件。"""

    for doc in args.doc:
        print_step("文档接入", f"开始读取并索引: {doc}")
        try:
            resource = client.fetch_document_resource(
                document=doc,
                doc_format="xml",
                detail="simple",
                scope="full",
                identity=args.identity,  # type: ignore[arg-type]
            )
            index_result = knowledge_store.index_resource(resource, force=False)
            print_step(
                "文档索引",
                f"title={resource.title} resource_id={resource.resource_id} "
                f"status={index_result.status} chunks={index_result.document.chunk_count}",
            )
            if args.skip_subscribe:
                print_step("文档订阅", "已跳过云文档事件订阅。")
                continue
            subscription = ensure_rag_event_subscription(
                knowledge_store=knowledge_store,
                client=client,
                resource=resource,
                identity=args.identity,
            )
            print_step("文档订阅", json.dumps(subscription, ensure_ascii=False))
        except FeishuAPIError as error:
            print_step("文档失败", str(error))
        except RuntimeError as error:
            print_step(
                "索引失败",
                f"{error}。如果看到 ChromaDB 不可用，请用 --python-bin 指向 nlp_prep 的 Python。",
            )


def ensure_calendar_event_subscription(args: argparse.Namespace, client: FeishuClient) -> None:
    """在观察台启动时订阅日程变更事件。

    飞书日程变更事件需要先对具体日历建立订阅关系；否则新增/修改日程只能依赖
    后台定时扫描被发现，看不到长连接事件输出。
    """

    if args.skip_calendar_subscribe or not (args.enable_m3 or args.enable_m4):
        return
    print_step("日程订阅", f"开始订阅日历日程变更 calendar_id={args.calendar_id}")
    try:
        result = client.subscribe_calendar_event_changes(
            calendar_id=args.calendar_id,
            identity=args.identity,  # type: ignore[arg-type]
        )
        data = result.get("data", {}) if isinstance(result, dict) else {}
        print_step("日程订阅", f"订阅成功 result={json.dumps(data, ensure_ascii=False)}")
    except FeishuAPIError as error:
        print_step("日程订阅失败", str(error))


def print_subscription_snapshot(knowledge_store: KnowledgeIndexStore) -> None:
    """打印最近的订阅状态，方便确认文档是否已进入事件监听范围。"""

    subscriptions = knowledge_store.list_event_subscriptions(limit=10)
    if not subscriptions:
        print_step("订阅状态", "当前没有已记录的 RAG 文档事件订阅。可先传 --doc 添加。")
        return
    print_step("订阅状态", f"最近 {len(subscriptions)} 条订阅记录：")
    for item in subscriptions:
        print(
            f"  - resource_id={item.get('resource_id')} file_type={item.get('file_type')} "
            f"status={item.get('status')} updated_at={item.get('updated_at')} "
            f"error={item.get('last_error') or '-'}"
        )


def relaunch_with_rag_python_if_needed(args: argparse.Namespace) -> None:
    """确保主进程运行在具备 RAG 依赖的 Python 中。

    飞书长连接和 RAG 索引的依赖容易冲突：长连接只需要 `lark-cli`/`lark_oapi`，
    RAG 写入则需要 `chromadb` 和 `sentence_transformers`。观察台本身负责索引，
    因此主进程必须在 RAG 环境中；长连接仍由单独的 `lark-cli` 子进程承担。
    """

    if not args.enable_rag:
        return
    required_modules = ("chromadb", "sentence_transformers")
    if modules_available(required_modules):
        return
    if os.getenv("MEETFLOW_LIVE_WATCH_REEXEC") == "1":
        print_step(
            "环境错误",
            "当前 Python 缺少 RAG 依赖：chromadb/sentence_transformers。"
            "请用 nlp_prep 环境启动，或传 --python-bin。",
        )
        return
    python_bin = resolve_rag_python_bin(args.python_bin, required_modules)
    if not python_bin:
        print_step(
            "环境错误",
            "找不到包含 chromadb 和 sentence_transformers 的 Python。"
            "可以显式传 --python-bin /home/lear-ubuntu-22/miniconda3/envs/nlp_prep/bin/python。",
        )
        return
    print_step("环境切换", f"当前 Python 缺少 RAG 依赖，自动切换到: {python_bin}")
    env = dict(os.environ)
    env["MEETFLOW_LIVE_WATCH_REEXEC"] = "1"
    os.execve(str(python_bin), [str(python_bin), str(Path(__file__).resolve()), *sys.argv[1:]], env)


def modules_available(modules: tuple[str, ...]) -> bool:
    """检查当前解释器是否能导入指定模块。"""

    return all(importlib.util.find_spec(module) is not None for module in modules)


def resolve_rag_python_bin(preferred: str, required_modules: tuple[str, ...]) -> Path | None:
    """寻找具备 RAG 依赖的 Python 解释器。"""

    candidates: list[Path] = []
    if preferred:
        candidates.append(normalize_python_path(preferred))
    candidates.extend(discover_python_candidates())
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_python_path(str(candidate))
        key = str(normalized)
        if key in seen or not normalized.exists():
            continue
        seen.add(key)
        if probe_python_modules(normalized, required_modules):
            return normalized
    return None


def normalize_python_path(value: str) -> Path:
    """把解释器路径规范化为绝对路径。"""

    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).absolute()


def discover_python_candidates() -> list[Path]:
    """收集本机常见 Python 解释器候选。"""

    candidates: list[Path] = [
        Path(sys.executable),
        Path(sys.executable).with_name("python3"),
        Path(sys.executable).with_name("python"),
        PROJECT_ROOT / ".venv-lark-oapi" / "bin" / "python",
    ]
    for env_name in ("CONDA_PREFIX", "VIRTUAL_ENV"):
        env_root = os.getenv(env_name, "").strip()
        if env_root:
            candidates.append(Path(env_root) / "bin" / "python")
            candidates.append(Path(env_root) / "bin" / "python3")
    conda_env_root = Path.home() / "miniconda3" / "envs"
    if conda_env_root.exists():
        for env_dir in sorted(conda_env_root.iterdir()):
            if env_dir.is_dir():
                candidates.append(env_dir / "bin" / "python")
                candidates.append(env_dir / "bin" / "python3")
    candidates.extend([Path("/usr/bin/python3"), Path("/bin/python3")])
    return candidates


def probe_python_modules(python_bin: Path, modules: tuple[str, ...]) -> bool:
    """用子进程探测某个解释器是否具备所需模块。"""

    script = (
        "import importlib.util\n"
        f"modules = {modules!r}\n"
        "missing = [name for name in modules if importlib.util.find_spec(name) is None]\n"
        "raise SystemExit(0 if not missing else 3)\n"
    )
    try:
        completed = subprocess.run(
            [str(python_bin), "-c", script],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=12,
            check=False,
        )
    except Exception:
        return False
    return completed.returncode == 0


def start_lark_event_subscriber(event_types: str, lark_cli_bin: str, *, force: bool) -> subprocess.Popen[str]:
    """启动 lark-cli 长连接进程。"""

    executable = resolve_lark_cli_bin(lark_cli_bin)
    command = [
        executable,
        "event",
        "+subscribe",
        "--event-types",
        event_types,
        "--compact",
        "--quiet",
        "--as",
        "bot",
    ]
    if force:
        command.append("--force")
    print_step("长连接", "启动命令: " + " ".join(command))
    return subprocess.Popen(  # noqa: S603 - 本地真实联调脚本需要启动 lark-cli。
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def resolve_lark_cli_bin(preferred: str) -> str:
    """解析 lark-cli 可执行文件路径。"""

    if preferred:
        path = Path(preferred).expanduser()
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).absolute()
        return str(path)
    return shutil.which("lark-cli") or "lark-cli"


def read_process_lines(process: subprocess.Popen[str], timeout: float) -> list[tuple[str, str]]:
    """非阻塞读取 lark-cli stdout/stderr，避免某一侧缓冲导致卡住。"""

    streams = [stream for stream in (process.stdout, process.stderr) if stream is not None]
    if not streams:
        time.sleep(timeout)
        return []
    readable, _, _ = select.select(streams, [], [], timeout)
    lines: list[tuple[str, str]] = []
    for stream in readable:
        line = stream.readline()
        if not line:
            continue
        stream_name = "stdout" if stream is process.stdout else "stderr"
        lines.append((stream_name, line.rstrip("\n")))
    return lines


def print_remaining_process_output(process: subprocess.Popen[str]) -> None:
    """长连接子进程退出后，尽量把剩余 stdout/stderr 打完整。

    `lark-cli` 发生参数错误、权限错误或单实例锁冲突时，经常会输出多行 JSON。
    之前观察台只读到第一行 `{` 就发现进程退出，用户看不到真正原因。
    """

    for stream_name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        if stream is None:
            continue
        remaining = stream.read()
        if not remaining:
            continue
        for line in remaining.splitlines():
            if stream_name == "stderr":
                print_lark_cli_line(line)
            else:
                event = parse_event_line(line)
                if event:
                    print_step("未处理事件", json.dumps(event, ensure_ascii=False)[:1000])


def parse_event_line(line: str) -> dict[str, Any]:
    """解析 lark-cli 输出的一行事件 JSON。"""

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        print_step("事件解析", f"收到非 JSON 输出: {line[:300]}")
        return {}
    return event if isinstance(event, dict) else {}


def handle_event(
    *,
    event: dict[str, Any],
    event_count: int,
    args: argparse.Namespace,
    card_args: SimpleNamespace,
    rag_args: SimpleNamespace,
    client: FeishuClient,
    knowledge_store: KnowledgeIndexStore,
    state: DaemonState,
    timezone: ZoneInfo,
    chat_id: str,
    watch_started_at: int,
) -> None:
    """根据事件类型执行可观察动作。"""

    event_type = event_type_of(event)
    print_step(f"事件 #{event_count}", f"type={event_type} id={event.get('event_id') or event.get('id') or '-'}")
    if is_document_event(event):
        handle_document_event(event, args, rag_args, client, knowledge_store, watch_started_at)
        return
    if event_type.startswith("calendar."):
        print_step("日程事件", "收到日程变化，立即扫描日历并检查 M3/M4 触发条件。")
        run_calendar_checks(args, card_args, client, state, timezone, chat_id)
        return
    print_step("事件跳过", "当前事件类型没有绑定 MeetFlow 动作。")


def handle_document_event(
    event: dict[str, Any],
    args: argparse.Namespace,
    rag_args: SimpleNamespace,
    client: FeishuClient,
    knowledge_store: KnowledgeIndexStore,
    watch_started_at: int,
) -> None:
    """处理云文档事件，并展示 RAG 任务结果。"""

    file_token = extract_event_file_token(event)
    file_type = extract_event_file_type(event)
    print_step("RAG 事件", f"file_token={file_token or '-'} file_type={file_type or '-'}")
    if not args.enable_rag:
        print_step("RAG 跳过", "当前未启用 RAG。")
        return
    before_jobs = summarize_recent_jobs(knowledge_store)
    enqueue_document_event_refresh(knowledge_store, event, logger=ConsoleLogger())
    process_observed_pending_index_jobs(
        client=client,
        knowledge_store=knowledge_store,
        args=rag_args,
        logger=ConsoleLogger(),
        created_after=watch_started_at,
        include_existing=args.process_existing_rag_jobs,
    )
    after_jobs = summarize_recent_jobs(knowledge_store)
    print_step("RAG 结果", describe_job_delta(before_jobs, after_jobs))


def run_fallback_scan(
    *,
    args: argparse.Namespace,
    card_args: SimpleNamespace,
    rag_args: SimpleNamespace,
    client: FeishuClient,
    knowledge_store: KnowledgeIndexStore,
    state: DaemonState,
    timezone: ZoneInfo,
    chat_id: str,
    watch_started_at: int,
) -> None:
    """执行没有事件时的兜底扫描，并打印扫描结果。"""

    print_step("兜底扫描", "开始检查日程窗口和 RAG pending 任务。")
    if args.enable_m3 or args.enable_m4:
        run_calendar_checks(args, card_args, client, state, timezone, chat_id)
    if args.enable_rag:
        before_jobs = summarize_recent_jobs(knowledge_store)
        process_observed_pending_index_jobs(
            client=client,
            knowledge_store=knowledge_store,
            args=rag_args,
            logger=ConsoleLogger(),
            created_after=watch_started_at,
            include_existing=args.process_existing_rag_jobs,
        )
        after_jobs = summarize_recent_jobs(knowledge_store)
        print_step("RAG 兜底", describe_job_delta(before_jobs, after_jobs))


def process_observed_pending_index_jobs(
    *,
    client: FeishuClient,
    knowledge_store: KnowledgeIndexStore,
    args: SimpleNamespace,
    logger: Any,
    created_after: int,
    include_existing: bool,
) -> None:
    """处理观察台本轮产生的 RAG pending 任务。

    真实项目库里可能残留 demo/self-test 写入的 pending job。观察台的目标是解释
    “我刚刚在飞书做的操作带来了什么结果”，因此默认只处理本次启动后由长连接
    事件写入的 `reason=event` 任务；如果需要清理历史队列，可显式传
    `--process-existing-rag-jobs`。
    """

    pending_jobs = knowledge_store.list_index_jobs(status="pending", limit=max(1, int(args.rag_limit or 20)))
    skipped_existing = 0
    for job in pending_jobs:
        job_id = str(job.get("job_id") or "")
        resource_id = str(job.get("resource_id") or "")
        resource_type = str(job.get("resource_type") or "")
        source_url = str(job.get("source_url") or "")
        reason = str(job.get("reason") or "")
        created_at = int(job.get("created_at") or 0)
        if not include_existing and (reason != "event" or created_at < created_after):
            skipped_existing += 1
            continue
        if args.dry_run:
            logger.info("dry-run: 将处理 RAG 事件刷新任务 job_id=%s resource_id=%s", job_id, resource_id)
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
        except Exception as error:  # noqa: BLE001 - 观察台要继续运行，错误打印给用户看。
            knowledge_store.update_index_job_status(job_id, status="failed", last_error=str(error))
            logger.warning("处理 RAG 事件刷新任务失败 job_id=%s resource_id=%s error=%s", job_id, resource_id, error)
    if skipped_existing:
        logger.info("已跳过历史 RAG pending 任务 %s 条；如需清理请加 --process-existing-rag-jobs", skipped_existing)


def run_calendar_checks(
    args: argparse.Namespace,
    daemon_args: SimpleNamespace,
    client: FeishuClient,
    state: DaemonState,
    timezone: ZoneInfo,
    chat_id: str,
) -> None:
    """扫描日历并触发 M3/M4 检查。"""

    try:
        events = scan_calendar_events(client, daemon_args, timezone)
    except FeishuAPIError as error:
        print_step("日程失败", str(error))
        return
    print_step("日程扫描", f"扫描到 {len(events)} 个日程实例。")
    for event in events[:8]:
        print(f"  - {event.summary or '(无标题)'} start={event.start_time} end={event.end_time} event_id={event.event_id}")
    logger = ConsoleLogger()
    if args.enable_m3:
        trigger_m3_due_events(events, args=daemon_args, state=state, timezone=timezone, logger=logger)
    if args.enable_m4:
        if not chat_id and args.allow_card_send:
            print_step("M4 跳过", "缺少 --chat-id 或配置 default_chat_id，不能真实发卡。")
        else:
            trigger_m4_finished_events(events, args=daemon_args, state=state, chat_id=chat_id, timezone=timezone, logger=logger)


def build_daemon_args(args: argparse.Namespace, *, dry_run: bool) -> SimpleNamespace:
    """构造复用 daemon 触发函数所需的参数对象。"""

    return SimpleNamespace(
        identity=args.identity,
        calendar_id=args.calendar_id,
        poll_seconds=args.poll_seconds,
        lookahead_hours=args.lookahead_hours,
        m3_minutes_before=args.m3_minutes_before,
        m4_lookback_hours=args.m4_lookback_hours,
        m4_delay_minutes=args.m4_delay_minutes,
        rag_limit=args.rag_limit,
        dry_run=dry_run,
    )


def summarize_recent_jobs(knowledge_store: KnowledgeIndexStore) -> dict[str, str]:
    """读取最近索引任务的简要状态。"""

    return {str(job.get("job_id")): str(job.get("status")) for job in knowledge_store.list_index_jobs(limit=20)}


def describe_job_delta(before: dict[str, str], after: dict[str, str]) -> str:
    """把索引任务变化翻译成适合人看的短文本。"""

    changed: list[str] = []
    for job_id, status in after.items():
        old_status = before.get(job_id)
        if old_status != status:
            changed.append(f"{job_id}: {old_status or 'new'} -> {status}")
    return "；".join(changed) if changed else "没有新的任务状态变化。"


def event_type_of(event: dict[str, Any]) -> str:
    """从 compact/raw 事件中提取事件类型。"""

    if event.get("type"):
        return str(event.get("type"))
    if event.get("event_type"):
        return str(event.get("event_type"))
    header = event.get("header")
    if isinstance(header, dict):
        return str(header.get("event_type") or "")
    return ""


def print_lark_cli_line(line: str) -> None:
    """打印 lark-cli 自身日志。"""

    if line.strip():
        print(f"[lark-cli] {line}")


def print_step(label: str, message: str) -> None:
    """统一输出观察台步骤。"""

    now = time.strftime("%H:%M:%S")
    print(f"[{now}] [{label}] {message}", flush=True)


def stop_process(process: subprocess.Popen[str]) -> None:
    """关闭长连接子进程。"""

    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


class ConsoleLogger:
    """给 daemon 复用函数提供简洁的控制台 logger。"""

    def info(self, message: str, *args: Any) -> None:
        print_step("动作", message % args if args else message)

    def warning(self, message: str, *args: Any) -> None:
        print_step("警告", message % args if args else message)


if __name__ == "__main__":
    raise SystemExit(main())
