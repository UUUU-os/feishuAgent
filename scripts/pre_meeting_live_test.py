from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# 允许直接通过 `python3 scripts/pre_meeting_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuAuthError, FeishuClient
from config import LLMSettings, load_settings
from core import (
    CalendarEvent,
    GenerationSettings,
    KnowledgeIndexStore,
    LLMConfigError,
    MeetFlowStorage,
    Resource,
    build_pre_meeting_trigger_plan,
    configure_logging,
    create_llm_provider,
    get_logger,
)
from core.agent import create_meetflow_agent
from scripts.agent_demo import ScriptedDebugProvider
from scripts.meetflow_agent_live_test import build_llm_settings, print_result, save_token_bundle


def parse_args() -> argparse.Namespace:
    """解析 M3 会前真实联调参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "真实联调 MeetFlow M3 会前知识卡片："
            "选择一条真实会议、可选拉取真实文档/妙记做索引，然后执行 pre_meeting_brief。"
        )
    )
    parser.add_argument("--calendar-id", default="primary", help="日历 ID，默认 primary。")
    parser.add_argument("--event-id", default="", help="指定要测试的 event_id；不传则自动选择最近一条即将开始的会议。")
    parser.add_argument("--identity", default="", choices=["tenant", "user"], help="飞书身份；不传则读取配置默认值。")
    parser.add_argument("--start-time", default="", help="查询开始时间，秒级时间戳。")
    parser.add_argument("--end-time", default="", help="查询结束时间，秒级时间戳。")
    parser.add_argument("--lookahead-hours", type=int, default=24, help="未显式传时间范围时，默认向后查询多少小时。")
    parser.add_argument("--project-id", default="meetflow", help="项目 ID。")
    parser.add_argument("--doc", action="append", default=[], help="需要纳入本次会前知识索引的飞书文档 URL 或 token，可传多次。")
    parser.add_argument("--minute", action="append", default=[], help="需要纳入本次会前知识索引的飞书妙记 URL 或 token，可传多次。")
    parser.add_argument(
        "--llm-provider",
        default="scripted_debug",
        help="scripted_debug 用稳定工具链验证；settings/default 或自定义 provider 名会使用真实 LLM。",
    )
    parser.add_argument("--model", default="", help="临时覆盖模型名。")
    parser.add_argument("--api-base", default="", help="临时覆盖 OpenAI-compatible API base。")
    parser.add_argument("--api-key-env", default="", help="从指定环境变量读取 API key。")
    parser.add_argument("--temperature", type=float, default=None, help="临时覆盖采样温度。")
    parser.add_argument("--max-tokens", type=int, default=None, help="临时覆盖最大输出 token 数。")
    parser.add_argument("--max-iterations", type=int, default=4, help="Agent Loop 最大轮数。")
    parser.add_argument("--allow-write", action="store_true", help="允许真正发送会前卡片。默认只读联调。")
    parser.add_argument("--enable-idempotency", action="store_true", help="启用幂等去重。真实重复触发建议开启。")
    parser.add_argument("--show-full", action="store_true", help="打印完整 AgentRunResult。")
    parser.add_argument(
        "--report-dir",
        default="storage/reports/m3",
        help="链路可视化报告输出目录，默认 storage/reports/m3。",
    )
    return parser.parse_args()


def main() -> int:
    """执行一次 M3 会前真实联调。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.pre_meeting.live_test")
    identity = args.identity or settings.feishu.default_identity

    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(settings.feishu, user_token_callback=lambda bundle: save_token_bundle(settings, bundle))
    knowledge_store = KnowledgeIndexStore(
        settings.storage,
        embedding_settings=settings.embedding,
        reranker_settings=settings.reranker,
    )
    knowledge_store.initialize()

    try:
        start_time, end_time = resolve_time_window(args, settings.app.timezone)
        event = select_target_event(
            client=client,
            calendar_id=args.calendar_id,
            start_time=start_time,
            end_time=end_time,
            identity=identity,
            event_id=args.event_id,
        )
        resources = fetch_supporting_resources(
            client=client,
            docs=args.doc,
            minutes=args.minute,
            identity=identity,
        )
        index_summaries = index_supporting_resources(knowledge_store, resources)
    except FeishuAuthError as error:
        logger.error("飞书鉴权失败：%s", error)
        print(
            "\n鉴权失败。请先检查：\n"
            "1. 本地用户 token 是否仍有效；必要时重新运行 python3 scripts/oauth_device_login.py\n"
            "2. 本次读取文档/妙记所需的 scope 是否已授权\n"
            "3. 如果后续要真发卡，测试群和机器人权限是否可用\n"
        )
        return 2
    except FeishuAPIError as error:
        logger.error("飞书真实联调失败：%s", error)
        print(f"\n真实联调失败：{error}\n")
        return 3

    trigger_event = build_trigger_event(event=event, project_id=args.project_id, resources=resources)
    trigger_plan = build_pre_meeting_trigger_plan(
        trigger_event,
        project_id=args.project_id,
        source="pre_meeting_live_test",
    )

    try:
        llm_provider, llm_settings = build_live_llm(args, settings.llm)
    except LLMConfigError as error:
        print(f"\nLLM 配置错误：{error}")
        print("建议：先用 --llm-provider scripted_debug 跑通真实飞书与知识索引链路，再切真实模型。")
        return 4

    agent = create_meetflow_agent(
        settings=settings,
        llm_provider=llm_provider,
        storage=storage,
        enable_idempotency=args.enable_idempotency,
        user_token_callback=lambda bundle: save_token_bundle(settings, bundle),
    )
    agent.loop.max_iterations = args.max_iterations

    result = agent.run(
        agent_input=trigger_plan.agent_input,
        workflow_goal=build_live_goal(event=event, resources=resources, allow_write=args.allow_write),
        generation_settings=GenerationSettings(
            model=llm_settings.model,
            temperature=llm_settings.temperature,
            max_tokens=llm_settings.max_tokens,
            reasoning_effort=llm_settings.reasoning_effort,
            timeout_seconds=90,
        ),
        allow_write=args.allow_write,
    )

    result_dict = result.to_dict()
    report_paths = write_observability_report(
        report_dir=PROJECT_ROOT / args.report_dir,
        event=event,
        identity=identity,
        resources=resources,
        index_summaries=index_summaries,
        knowledge_store=knowledge_store,
        trigger_plan=trigger_plan.to_dict(),
        allow_write=args.allow_write,
        result=result_dict,
    )

    print_runtime_summary(
        event=event,
        identity=identity,
        resources=resources,
        index_summaries=index_summaries,
        trigger_plan=trigger_plan.to_dict(),
        allow_write=args.allow_write,
        result=result_dict,
        show_full=args.show_full,
        report_paths=report_paths,
    )
    return 0 if result.status in {"success", "max_iterations", "skipped"} else 1


def resolve_time_window(args: argparse.Namespace, timezone_name: str) -> tuple[str, str]:
    """解析真实会议查询时间窗口。"""

    if args.start_time and args.end_time:
        return args.start_time, args.end_time
    timezone = ZoneInfo(timezone_name or "Asia/Shanghai")
    start = datetime.now(timezone)
    end = start + timedelta(hours=max(1, int(args.lookahead_hours or 24)))
    return str(int(start.timestamp())), str(int(end.timestamp()))


def select_target_event(
    client: FeishuClient,
    calendar_id: str,
    start_time: str,
    end_time: str,
    identity: str,
    event_id: str = "",
) -> CalendarEvent:
    """从真实日历中选择一条用于 M3 联调的会议。"""

    events = client.list_calendar_event_instances(
        calendar_id=calendar_id,
        start_time=start_time,
        end_time=end_time,
        identity=identity,  # type: ignore[arg-type]
    )
    if not events:
        raise FeishuAPIError("给定时间窗口内没有可用于测试的会议，请扩大查询时间范围。")
    if event_id:
        for item in events:
            if item.event_id == event_id:
                return item
        raise FeishuAPIError(f"没有找到指定 event_id 的会议：{event_id}")
    return sorted(events, key=lambda item: safe_event_timestamp(item.start_time))[0]


def fetch_supporting_resources(
    client: FeishuClient,
    docs: list[str],
    minutes: list[str],
    identity: str,
) -> list[Resource]:
    """读取本次测试要纳入知识索引的真实资源。"""

    resources: list[Resource] = []
    for document in docs:
        resources.append(
            client.fetch_document_resource(
                document=document,
                doc_format="xml",
                detail="simple",
                scope="full",
                identity=identity,  # type: ignore[arg-type]
            )
        )
    for minute in minutes:
        resources.append(
            client.fetch_minute_resource(
                minute=minute,
                include_artifacts=True,
                identity=identity,  # type: ignore[arg-type]
            )
        )
    return resources


def index_supporting_resources(
    knowledge_store: KnowledgeIndexStore,
    resources: list[Resource],
) -> list[dict[str, Any]]:
    """按当前 embedding 指纹重建本次测试资源索引。"""

    summaries: list[dict[str, Any]] = []
    for resource in resources:
        result = knowledge_store.index_resource(resource, force=True)
        summaries.append(
            {
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "title": resource.title,
                "status": result.status,
                "skipped": result.skipped,
                "chunk_count": result.document.chunk_count,
                "knowledge_namespace": result.document.metadata.get("knowledge_namespace", ""),
            }
        )
    return summaries


def build_trigger_event(event: CalendarEvent, project_id: str, resources: list[Resource]) -> dict[str, Any]:
    """把真实会议和索引资源转成会前触发 payload。"""

    participants = [
        {
            "attendee_id": attendee.attendee_id,
            "display_name": attendee.display_name,
            "attendee_type": attendee.attendee_type,
            "rsvp_status": attendee.rsvp_status,
            "is_optional": attendee.is_optional,
            "is_organizer": attendee.is_organizer,
        }
        for attendee in event.attendees
    ]
    related_resources = [resource.to_dict() for resource in resources]
    attachments = [
        {
            "title": resource.title,
            "url": resource.source_url,
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "updated_at": resource.updated_at,
        }
        for resource in resources
    ]
    return {
        "event_id": event.event_id,
        "calendar_event_id": event.event_id,
        "meeting_id": event.event_id,
        "project_id": project_id,
        "summary": event.summary,
        "description": event.description,
        "start_time": event.start_time,
        "end_time": event.end_time,
        "participants": participants,
        "attendees": participants,
        "related_resources": related_resources,
        "attachments": attachments,
        "app_link": event.app_link,
    }


def build_live_llm(args: argparse.Namespace, fallback: LLMSettings) -> tuple[ScriptedDebugProvider | Any, LLMSettings]:
    """构造本次会前真实联调使用的 LLM。"""

    if args.llm_provider == "scripted_debug":
        return (
            ScriptedDebugProvider(),
            LLMSettings(
                provider="scripted-debug",
                model="scripted-debug",
                api_base="",
                api_key="",
                temperature=0.0,
                max_tokens=1000,
                reasoning_effort="",
            ),
        )
    llm_settings = build_llm_settings(args, fallback)
    return create_llm_provider(llm_settings), llm_settings


def build_live_goal(event: CalendarEvent, resources: list[Resource], allow_write: bool) -> str:
    """构造更贴近 M3 联调目标的工作流说明。"""

    resource_hint = "、".join(
        [resource.title for resource in resources[:3] if resource.title]
    ) or "当前没有额外索引资源，只能依赖会议上下文和已有知识库"
    write_hint = (
        "允许调用写工具发送最终会前卡片。"
        if allow_write
        else "当前只读联调，不要发送真实卡片，只输出会前卡片草案和引用。"
    )
    return (
        f"请围绕真实会议《{event.summary or event.event_id}》生成会前知识卡片。\n"
        f"- 本次补充索引资源：{resource_hint}\n"
        f"- 会议开始时间: {event.start_time}\n"
        f"- 会议描述: {event.description or '无'}\n"
        f"- 参会人数: {len(event.attendees)}\n"
        f"- {write_hint}\n"
        "- 结论必须基于 knowledge_search / knowledge_fetch_chunk 或当前会议上下文，不要编造资料。\n"
        "- 如果证据不足，要明确指出资料不足或仅为可能相关资料。"
    )


def print_runtime_summary(
    event: CalendarEvent,
    identity: str,
    resources: list[Resource],
    index_summaries: list[dict[str, Any]],
    trigger_plan: dict[str, Any],
    allow_write: bool,
    result: dict[str, Any],
    show_full: bool,
    report_paths: dict[str, str],
) -> None:
    """打印本次真实联调的高信号摘要。"""

    summary = {
        "selected_event": {
            "event_id": event.event_id,
            "summary": event.summary,
            "start_time": event.start_time,
            "end_time": event.end_time,
            "attendee_count": len(event.attendees),
        },
        "identity": identity,
        "allow_write": allow_write,
        "seeded_resource_count": len(resources),
        "seeded_resources": [
            {
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "title": resource.title,
            }
            for resource in resources
        ],
        "index_summaries": index_summaries,
        "trigger_id": trigger_plan.get("trigger_id", ""),
        "agent_input_payload_keys": sorted(list((trigger_plan.get("agent_input") or {}).get("payload", {}).keys())),
        "report_markdown": report_paths.get("markdown", ""),
        "report_json": report_paths.get("json", ""),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print_result(result, show_full=show_full)


def write_observability_report(
    report_dir: Path,
    event: CalendarEvent,
    identity: str,
    resources: list[Resource],
    index_summaries: list[dict[str, Any]],
    knowledge_store: KnowledgeIndexStore,
    trigger_plan: dict[str, Any],
    allow_write: bool,
    result: dict[str, Any],
) -> dict[str, str]:
    """输出 M3 真实联调可观察性报告。"""

    report_dir.mkdir(parents=True, exist_ok=True)
    trace_id = str(result.get("trace_id") or int(time.time()))
    base_name = f"pre_meeting_live_{trace_id}"
    details = build_observability_details(
        event=event,
        identity=identity,
        resources=resources,
        index_summaries=index_summaries,
        knowledge_store=knowledge_store,
        trigger_plan=trigger_plan,
        allow_write=allow_write,
        result=result,
    )
    markdown_path = report_dir / f"{base_name}.md"
    json_path = report_dir / f"{base_name}.json"
    markdown_path.write_text(render_observability_markdown(details), encoding="utf-8")
    json_path.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"markdown": str(markdown_path), "json": str(json_path)}


def build_observability_details(
    event: CalendarEvent,
    identity: str,
    resources: list[Resource],
    index_summaries: list[dict[str, Any]],
    knowledge_store: KnowledgeIndexStore,
    trigger_plan: dict[str, Any],
    allow_write: bool,
    result: dict[str, Any],
) -> dict[str, Any]:
    """组装报告所需的会议、索引、检索和卡片数据。"""

    resource_details: list[dict[str, Any]] = []
    for resource in resources:
        chunks = knowledge_store.list_chunks(resource.resource_id)
        resource_details.append(
            {
                "resource": resource.to_dict(),
                "document": knowledge_store.get_document(resource.resource_id),
                "chunks": [summarize_chunk(chunk) for chunk in chunks],
            }
        )

    artifacts = extract_pre_meeting_artifacts(result)
    tool_results = extract_tool_results(result)
    return {
        "event": event.to_dict(),
        "identity": identity,
        "allow_write": allow_write,
        "index_summaries": index_summaries,
        "resources": resource_details,
        "trigger_plan": trigger_plan,
        "pre_meeting_artifacts": artifacts,
        "tool_results": tool_results,
        "agent_result": {
            "trace_id": result.get("trace_id", ""),
            "workflow_type": result.get("workflow_type", ""),
            "status": result.get("status", ""),
            "summary": result.get("summary", ""),
            "final_answer": result.get("final_answer", ""),
        },
    }


def summarize_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """压缩 chunk 展示字段，避免报告被长正文淹没。"""

    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    text = str(chunk.get("text") or "")
    return {
        "chunk_id": chunk.get("chunk_id", ""),
        "chunk_type": chunk.get("chunk_type", ""),
        "chunk_order": chunk.get("chunk_order", 0),
        "parent_chunk_id": chunk.get("parent_chunk_id", ""),
        "doc_type": chunk.get("doc_type", ""),
        "content_tokens": chunk.get("content_tokens", 0),
        "source_locator": chunk.get("source_locator", ""),
        "toc_path": metadata.get("toc_path", []),
        "positions": metadata.get("positions", {}),
        "child_chunk_ids": metadata.get("child_chunk_ids", []) if isinstance(metadata.get("child_chunk_ids"), list) else [],
        "keywords": metadata.get("keywords", [])[:12] if isinstance(metadata.get("keywords"), list) else [],
        "questions": metadata.get("questions", [])[:8] if isinstance(metadata.get("questions"), list) else [],
        "text_preview": clip_text(text, 500),
    }


def extract_pre_meeting_artifacts(result: dict[str, Any]) -> dict[str, Any]:
    """从 AgentRunResult 中取出会前工作流确定性阶段产物。"""

    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    raw_context = context.get("raw_context") if isinstance(context.get("raw_context"), dict) else {}
    return raw_context.get("pre_meeting_brief", {}) if isinstance(raw_context.get("pre_meeting_brief"), dict) else {}


def extract_tool_results(result: dict[str, Any]) -> list[dict[str, Any]]:
    """抽取工具调用结果，重点展示 knowledge.search 的证据包。"""

    loop_state = result.get("loop_state") if isinstance(result.get("loop_state"), dict) else {}
    tool_results = loop_state.get("tool_results") if isinstance(loop_state.get("tool_results"), list) else []
    normalized: list[dict[str, Any]] = []
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "tool_name": item.get("tool_name", ""),
                "status": item.get("status", ""),
                "content": clip_text(str(item.get("content", "")), 1200),
                "data": item.get("data", {}),
                "error_message": item.get("error_message", ""),
            }
        )
    return normalized


def render_observability_markdown(details: dict[str, Any]) -> str:
    """渲染便于人工阅读的 M3 链路报告。"""

    event = details.get("event", {})
    artifacts = details.get("pre_meeting_artifacts", {})
    retrieval_query = artifacts.get("retrieval_query", {}) if isinstance(artifacts, dict) else {}
    card_payload = artifacts.get("card_payload", {}) if isinstance(artifacts, dict) else {}
    lines = [
        "# M3 会前知识卡片真实联调报告",
        "",
        "## 1. 会议输入",
        "",
        f"- event_id: `{event.get('event_id', '')}`",
        f"- 标题: {event.get('summary', '')}",
        f"- 开始时间: `{event.get('start_time', '')}`",
        f"- 结束时间: `{event.get('end_time', '')}`",
        f"- 参会人数: `{len(event.get('attendees', []) or [])}`",
        f"- allow_write: `{details.get('allow_write', False)}`",
        "",
        "## 2. 工作流阶段",
        "",
        "```text",
        "真实日历会议 -> 真实文档读取 -> 文档清洗与 chunk -> 向量/关键词索引 -> meeting.soon -> PreMeetingBriefWorkflow -> knowledge.search -> 会前卡片草案",
        "```",
        "",
        "## 3. 检索 Query",
        "",
        "```json",
        json.dumps(retrieval_query, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 4. 索引资源与 Chunk",
        "",
    ]
    for resource_detail in details.get("resources", []):
        resource = resource_detail.get("resource", {})
        chunks = resource_detail.get("chunks", [])
        parent_chunks = [chunk for chunk in chunks if chunk.get("chunk_type") == "parent_section"]
        child_chunks = [chunk for chunk in chunks if chunk.get("chunk_type") != "parent_section"]
        lines.extend(
            [
                f"### {resource.get('title', resource.get('resource_id', '未命名资源'))}",
                "",
                f"- resource_id: `{resource.get('resource_id', '')}`",
                f"- resource_type: `{resource.get('resource_type', '')}`",
                f"- source_url: {resource.get('source_url', '')}",
                f"- chunk_count: `{len(chunks)}`（可检索子 chunk `{len(child_chunks)}`，父级上下文 chunk `{len(parent_chunks)}`）",
                "",
            ]
        )
        if child_chunks:
            lines.extend(["#### 可检索子 Chunk", ""])
        for chunk in child_chunks:
            lines.extend(
                [
                    f"##### child `{chunk.get('chunk_order', 0)}`",
                    "",
                    f"- chunk_id: `{chunk.get('chunk_id', '')}`",
                    f"- chunk_type: `{chunk.get('chunk_type', '')}`",
                    f"- parent_chunk_id: `{chunk.get('parent_chunk_id', '')}`",
                    f"- content_tokens: `{chunk.get('content_tokens', 0)}`",
                    f"- source_locator: `{chunk.get('source_locator', '')}`",
                    f"- toc_path: `{chunk.get('toc_path', [])}`",
                    f"- keywords: `{chunk.get('keywords', [])}`",
                    "",
                    "```text",
                    str(chunk.get("text_preview", "")),
                    "```",
                    "",
                ]
            )
        if parent_chunks:
            lines.extend(
                [
                    "#### 父级上下文 Chunk",
                    "",
                    "> parent_section 不直接作为检索结果返回，主要用于 `knowledge.fetch_chunk` 按 `parent_chunk_id` 展开同章节上下文。",
                    "",
                ]
            )
        for chunk in parent_chunks:
            lines.extend(
                [
                    f"##### parent `{chunk.get('chunk_order', 0)}`",
                    "",
                    f"- chunk_id: `{chunk.get('chunk_id', '')}`",
                    f"- content_tokens: `{chunk.get('content_tokens', 0)}`",
                    f"- source_locator: `{chunk.get('source_locator', '')}`",
                    f"- toc_path: `{chunk.get('toc_path', [])}`",
                    f"- child_chunk_ids: `{chunk.get('child_chunk_ids', [])}`",
                    "",
                    "```text",
                    str(chunk.get("text_preview", "")),
                    "```",
                    "",
                ]
            )

    lines.extend(
        [
            "## 5. 工具检索结果",
            "",
        ]
    )
    for tool_result in details.get("tool_results", []):
        lines.extend(
            [
                f"### {tool_result.get('tool_name', '')} `{tool_result.get('status', '')}`",
                "",
                "```json",
                json.dumps(tool_result.get("data", {}), ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## 6. 卡片 Payload 草案",
            "",
            "```json",
            json.dumps(card_payload, ensure_ascii=False, indent=2),
            "```",
            "",
            "## 7. Agent 最终结果",
            "",
            f"- status: `{details.get('agent_result', {}).get('status', '')}`",
            f"- trace_id: `{details.get('agent_result', {}).get('trace_id', '')}`",
            "",
            "```text",
            clip_text(str(details.get("agent_result", {}).get("final_answer", "")), 2000),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def clip_text(text: str, limit: int) -> str:
    """截断长文本，保留报告可读性。"""

    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def safe_event_timestamp(value: str) -> int:
    """把会议时间转换成可排序的秒级时间戳。"""

    text = str(value or "").strip()
    if text.isdigit():
        number = int(text)
        return number // 1000 if number > 10_000_000_000 else number
    return int(time.time()) + 365 * 24 * 60 * 60


if __name__ == "__main__":
    raise SystemExit(main())
