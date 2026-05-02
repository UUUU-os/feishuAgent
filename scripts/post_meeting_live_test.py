from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/post_meeting_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuAuthError, FeishuClient, create_feishu_tool_registry
from cards import (
    build_auto_created_tasks_card,
    build_pending_action_item_button_card,
    build_pending_task_button_value,
)
from config import load_settings
from core import (
    AgentPolicy,
    AgentToolCall,
    Event,
    KnowledgeIndexStore,
    MeetFlowStorage,
    WorkflowContext,
    bind_pending_action_message,
    build_post_meeting_artifacts_from_input,
    build_task_create_arguments,
    build_task_mapping_payload,
    configure_logging,
    enrich_post_meeting_related_resources,
    get_logger,
    is_group_owner_candidate,
    save_pending_action_values,
)
from scripts.meetflow_agent_live_test import save_token_bundle


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="M4 会后总结真实妙记联调脚本。")
    parser.add_argument("--minute", required=True, help="飞书妙记 URL 或 minute token。")
    parser.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取妙记使用的身份。")
    parser.add_argument("--read-only", action="store_true", help="只读验证，不执行任何写操作。")
    parser.add_argument("--allow-write", action="store_true", help="允许通过 AgentPolicy 后执行写操作。")
    parser.add_argument("--send-card", action="store_true", help="在 allow-write 时发送会后总结/待确认卡片。")
    parser.add_argument(
        "--send-reaction-cards",
        action="store_true",
        help="为每个待确认任务额外发送一条可点表情确认的普通消息；保留参数名兼容旧命令。",
    )
    parser.add_argument("--chat-id", default="", help="测试群 chat_id；不传则使用配置 default_chat_id。")
    parser.add_argument("--receive-id-type", default="chat_id", help="接收者 ID 类型，默认 chat_id。")
    parser.add_argument("--timezone", default="", help="截止时间解析时区；不传使用 app.timezone。")
    parser.add_argument("--show-card-json", action="store_true", help="打印完整卡片 JSON。")
    parser.add_argument("--content-limit", type=int, default=1200, help="妙记正文预览字符数。")
    parser.add_argument("--report-dir", default="", help="保存 M3 风格 Markdown 运行报告的目录。")
    parser.add_argument("--skip-related-knowledge", action="store_true", help="跳过 M3 RAG 背景资料召回。")
    parser.add_argument("--related-top-n", type=int, default=5, help="会后总结卡片中展示的相关背景资料数量。")
    parser.add_argument(
        "--print-report-json",
        action="store_true",
        help="即使已写入 report 文件，也在控制台打印完整 JSON；默认只打印紧凑摘要。",
    )
    return parser.parse_args()


def main() -> int:
    """执行真实妙记只读或灰度写入验证。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.post_meeting.live_test")
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(
        settings.feishu,
        user_token_callback=lambda bundle: save_token_bundle(settings, bundle),
    )
    registry = create_feishu_tool_registry(client, default_chat_id=settings.feishu.default_chat_id)
    policy = AgentPolicy()

    try:
        logger.info("读取真实妙记 minute=%s identity=%s", args.minute, args.identity)
        resource = client.fetch_minute_resource(
            minute=args.minute,
            include_artifacts=True,
            identity=args.identity,
        )
        workflow_input = build_workflow_input_from_resource(resource)
        artifacts = build_post_meeting_artifacts_from_input(workflow_input)
        if not args.skip_related_knowledge:
            enrich_related_knowledge(settings=settings, artifacts=artifacts, top_n=args.related_top_n, report_logger=logger)
        context = build_policy_context(artifacts, trace_id=f"post_meeting_live:{int(time.time())}")
        report: dict[str, Any] = build_readonly_report(artifacts, content_limit=args.content_limit)

        if args.show_card_json:
            report["card_json"] = artifacts.card_payloads

        write_enabled = args.allow_write and not args.read_only
        if write_enabled:
            report["write_results"] = run_write_phase(
                args=args,
                settings=settings,
                registry=registry,
                policy=policy,
                storage=storage,
                context=context,
                artifacts=artifacts,
            )
        else:
            report["write_results"] = {
                "skipped": True,
                "reason": "未开启 --allow-write 或指定了 --read-only，本次不创建任务、不发送卡片。",
            }

        if args.report_dir:
            report_path = write_markdown_report(args=args, artifacts=artifacts, report=report)
            report["report_path"] = str(report_path)

        if args.report_dir and not args.print_report_json:
            print(json.dumps(build_compact_console_summary(report), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except FeishuAuthError as error:
        logger.error("飞书鉴权失败：%s", error)
        print(f"\n鉴权失败：{error}\n请先确认 OAuth 登录、应用权限和本地配置。")
        return 2
    except FeishuAPIError as error:
        logger.error("飞书接口调用失败：%s", error)
        print(f"\n接口调用失败：{error}\n")
        return 3
    except Exception as error:  # pragma: no cover - 真实联调脚本兜底
        logger.exception("未知异常")
        print(f"\n发生未知异常：{error}\n")
        return 4


def build_workflow_input_from_resource(resource: Any) -> Any:
    """把真实妙记 Resource 转成 M4 输入。"""

    from core import PostMeetingInput

    return PostMeetingInput(
        meeting_id=str(resource.source_meta.get("meeting_id") or resource.resource_id),
        calendar_event_id=str(resource.source_meta.get("calendar_event_id") or ""),
        minute_token=resource.resource_id,
        project_id=str(resource.source_meta.get("project_id") or "meetflow"),
        topic=resource.title,
        source_type=resource.resource_type,
        source_id=resource.resource_id,
        source_url=resource.source_url,
        raw_text=resource.content,
        raw_payload=dict(resource.source_meta),
    )


def enrich_related_knowledge(settings: Any, artifacts: Any, top_n: int, report_logger: Any) -> None:
    """尝试复用 M3 轻量 RAG，为会后总结卡片补充背景资料。"""

    try:
        knowledge_store = KnowledgeIndexStore(
            settings.storage,
            embedding_settings=settings.embedding,
            reranker_settings=settings.reranker,
            search_settings=settings.knowledge_search,
        )
        enrich_post_meeting_related_resources(
            artifacts=artifacts,
            knowledge_store=knowledge_store,
            top_n=max(1, min(top_n, 8)),
        )
    except Exception as error:  # pragma: no cover - 真实环境依赖可选 RAG 配置
        report_logger.warning("会后相关背景资料召回失败，继续使用普通会后卡片：%s", error)
        artifacts.extra["related_knowledge_status"] = "error"
        artifacts.extra["related_knowledge_error"] = str(error)


def build_policy_context(artifacts: Any, trace_id: str) -> WorkflowContext:
    """构造供 AgentPolicy 审核写工具使用的上下文。"""

    workflow_input = artifacts.workflow_input
    event = Event(
        event_id=f"{trace_id}:event",
        event_type="minute.ready",
        event_time=str(int(time.time())),
        source="post_meeting_live_test",
        actor="",
        payload=workflow_input.raw_payload,
        trace_id=trace_id,
    )
    return WorkflowContext(
        workflow_type="post_meeting_followup",
        trace_id=trace_id,
        event=event,
        meeting_id=workflow_input.meeting_id,
        calendar_event_id=workflow_input.calendar_event_id,
        minute_token=workflow_input.minute_token,
        project_id=workflow_input.project_id,
        raw_context={
            "decision": {
                "workflow_type": "post_meeting_followup",
                "idempotency_key": f"post_meeting:{workflow_input.minute_token or workflow_input.meeting_id}",
            }
        },
    )


def build_readonly_report(artifacts: Any, content_limit: int) -> dict[str, Any]:
    """生成真实妙记只读验证报告。"""

    cleaned = artifacts.cleaned_transcript
    return {
        "mode": "post_meeting_live_test",
        "workflow_input": summarize_workflow_input(artifacts.workflow_input, content_limit=content_limit),
        "cleaned_excerpt": cleaned.cleaned_text[:content_limit],
        "cleaned": {
            "line_count": len(cleaned.lines),
            "sections": [section.to_dict() for section in cleaned.sections],
            "signal_lines": list(cleaned.signal_lines),
            "extra": dict(cleaned.extra),
        },
        "decisions": [item.to_dict() for item in artifacts.decisions],
        "open_questions": [item.to_dict() for item in artifacts.open_questions],
        "action_items": [item.to_dict() for item in artifacts.action_items],
        "pending_action_items": [item.to_dict() for item in artifacts.pending_action_items],
        "related_knowledge": {
            "status": artifacts.extra.get("related_knowledge_status", ""),
            "query": artifacts.extra.get("related_knowledge_query", ""),
            "hit_count": len(artifacts.extra.get("related_knowledge_hits", []) or []),
            "reason": artifacts.extra.get("related_knowledge_reason", ""),
            "error": artifacts.extra.get("related_knowledge_error", ""),
        },
        "card_summary": {
            key: {
                "title": value.get("header", {}).get("title", {}).get("content", ""),
                "template": value.get("header", {}).get("template", ""),
                "elements": count_card_elements(value),
            }
            for key, value in artifacts.card_payloads.items()
            if isinstance(value, dict)
        },
    }


def write_markdown_report(args: argparse.Namespace, artifacts: Any, report: dict[str, Any]) -> Path:
    """把单次真实联调结果保存成 M3 风格 Markdown 报告。"""

    report_dir = Path(args.report_dir)
    if not report_dir.is_absolute():
        report_dir = PROJECT_ROOT / report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    workflow_input = artifacts.workflow_input
    mode = "write" if args.allow_write and not args.read_only else "readonly"
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"post_meeting_live_{workflow_input.minute_token}_{mode}_{suffix}.md"
    report_path.write_text(render_markdown_report(args=args, artifacts=artifacts, report=report), encoding="utf-8")
    return report_path


def build_compact_console_summary(report: dict[str, Any]) -> dict[str, Any]:
    """生成控制台紧凑摘要，避免一次测试同时刷出大 JSON 和 Markdown report。"""

    write_results = report.get("write_results", {})
    return {
        "mode": report.get("mode", "post_meeting_live_test"),
        "minute_token": report.get("workflow_input", {}).get("minute_token", ""),
        "action_item_count": len(report.get("action_items", [])),
        "pending_action_item_count": len(report.get("pending_action_items", [])),
        "related_knowledge": report.get("related_knowledge", {}),
        "created_tasks": len(write_results.get("created_tasks", [])) if isinstance(write_results, dict) else 0,
        "sent_cards": len(write_results.get("sent_cards", [])) if isinstance(write_results, dict) else 0,
        "report_path": report.get("report_path", ""),
    }


def render_markdown_report(args: argparse.Namespace, artifacts: Any, report: dict[str, Any]) -> str:
    """渲染单次 M4 运行报告，突出输入、阶段、产物和写入结果。"""

    workflow_input = artifacts.workflow_input
    cleaned = artifacts.cleaned_transcript
    write_results = report.get("write_results", {})
    lines: list[str] = [
        "# M4 会后总结真实联调报告",
        "",
        "## 1. 妙记输入",
        "",
        f"- minute_token: `{workflow_input.minute_token}`",
        f"- 标题: {workflow_input.topic}",
        f"- source_url: {workflow_input.source_url}",
        f"- source_type: `{workflow_input.source_type}`",
        f"- 读取身份: `{args.identity}`",
        f"- 内容来源: `minutes.get + minutes.artifacts`（AI 总结 / 待办 / 章节；不是逐字稿原文）",
        f"- raw_text_length: `{len(workflow_input.raw_text)}`",
        f"- allow_write: `{bool(args.allow_write and not args.read_only)}`",
        f"- send_card: `{bool(args.send_card)}`",
        "",
        "## 2. 工作流阶段",
        "",
        "```text",
        "真实妙记 -> AI 产物读取 -> PostMeetingInput -> clean_transcript -> extract_decisions/open_questions/action_items -> confidence/confirmation -> card render -> ToolRegistry + AgentPolicy 写入",
        "```",
        "",
        "## 3. 清洗与章节",
        "",
        f"- cleaned_line_count: `{len(cleaned.lines)}`",
        f"- section_count: `{len(cleaned.sections)}`",
        f"- signal_line_count: `{len(cleaned.signal_lines)}`",
        "",
    ]
    for section in cleaned.sections:
        lines.extend(
            [
                f"### {section.title}",
                "",
                f"- line_range: `{section.start_line}-{section.end_line}`",
                f"- signal_tags: `{', '.join(section.signal_tags)}`",
                "",
            ]
        )

    lines.extend(["## 4. Action Items", ""])
    if artifacts.action_items:
        for index, item in enumerate(artifacts.action_items, start=1):
            extra = item.extra or {}
            lines.extend(
                [
                    f"### Action Item {index}",
                    "",
                    f"- item_id: `{item.item_id}`",
                    f"- title: {item.title}",
                    f"- owner_candidate: `{item.owner or '未识别'}`",
                    f"- due_date_candidate: `{item.due_date or '未识别'}`",
                    f"- priority: `{item.priority}`",
                    f"- confidence: `{item.confidence:.2f}`",
                    f"- needs_confirm: `{item.needs_confirm}`",
                    f"- confirm_reason: {extra.get('confirm_reason', '') or '无'}",
                    f"- source_line: `{extra.get('source_line', '')}`",
                    f"- auto_create_candidate: `{extra.get('auto_create_candidate', False)}`",
                    "",
                    "#### Evidence",
                    "",
                ]
            )
            for ref in item.evidence_refs:
                lines.append(f"- `{ref.source_id}` {ref.source_type}: {ref.snippet}")
            lines.append("")
    else:
        lines.extend(["暂无 Action Items。", ""])

    lines.extend(["## 5. 决策与开放问题", ""])
    lines.append(f"- decisions_count: `{len(artifacts.decisions)}`")
    for item in artifacts.decisions:
        lines.append(f"  - `{item.decision_id}` {item.content}")
    lines.append(f"- open_questions_count: `{len(artifacts.open_questions)}`")
    for item in artifacts.open_questions:
        lines.append(f"  - `{item.question_id}` {item.content}")
    lines.append("")

    lines.extend(["## 6. 卡片产物", ""])
    for key, card in artifacts.card_payloads.items():
        if key == "pending_card" and not artifacts.pending_action_items:
            lines.append(f"- {key}: 未发送候选（没有待确认任务）")
            continue
        title = card.get("header", {}).get("title", {}).get("content", "")
        elements = count_card_elements(card)
        lines.append(f"- {key}: `{title}`，elements=`{elements}`")
    lines.append("")

    lines.extend(["## 6.1 相关背景资料", ""])
    related_hits = artifacts.extra.get("related_knowledge_hits", []) or []
    lines.append(f"- related_knowledge_status: `{artifacts.extra.get('related_knowledge_status', '')}`")
    lines.append(f"- related_knowledge_query: {artifacts.extra.get('related_knowledge_query', '')}")
    lines.append(f"- related_knowledge_hit_count: `{len(related_hits)}`")
    if artifacts.extra.get("related_knowledge_error"):
        lines.append(f"- related_knowledge_error: {artifacts.extra.get('related_knowledge_error', '')}")
    for hit in related_hits[:8]:
        lines.append(
            f"  - `{getattr(hit, 'ref_id', '')}` {getattr(hit, 'title', '')} "
            f"score=`{float(getattr(hit, 'score', 0.0) or 0.0):.2f}` url={getattr(hit, 'source_url', '')}"
        )
    lines.append("")

    lines.extend(["## 7. 写入结果", ""])
    lines.append(f"- created_tasks: `{len(write_results.get('created_tasks', []))}`")
    for item in write_results.get("created_tasks", []):
        tool_result = item.get("tool_result", {})
        lines.append(f"  - `{item.get('item_id', '')}` status=`{tool_result.get('status', '')}` title={item.get('title', '')}")
    lines.append(f"- skipped_tasks: `{len(write_results.get('skipped_tasks', []))}`")
    for item in write_results.get("skipped_tasks", []):
        lines.append(f"  - `{item.get('item_id', '')}` reason={item.get('reason', '')}")
    lines.append(f"- sent_cards: `{len(write_results.get('sent_cards', []))}`")
    for item in write_results.get("sent_cards", []):
        tool_result = item.get("tool_result", {})
        data = tool_result.get("data", {}) if isinstance(tool_result, dict) else {}
        lines.append(
            f"  - {item.get('card', '')}: status=`{tool_result.get('status', '')}`, "
            f"message_id=`{data.get('message_id', '')}`, chat_id=`{data.get('chat_id', '')}`"
        )
    if write_results.get("skipped"):
        lines.append(f"- write_skipped_reason: {write_results.get('reason', '')}")
    lines.append("")

    lines.extend(
        [
            "## 8. 结论",
            "",
            build_report_conclusion(artifacts, write_results),
            "",
        ]
    )
    return "\n".join(lines)


def build_report_conclusion(artifacts: Any, write_results: dict[str, Any]) -> str:
    """生成单次报告结论。"""

    created_count = len(write_results.get("created_tasks", []))
    sent_count = len(write_results.get("sent_cards", []))
    pending_count = len(artifacts.pending_action_items)
    if created_count:
        return f"本次已创建 {created_count} 个任务并发送 {sent_count} 张卡片。"
    if pending_count:
        return f"本次发送 {sent_count} 张卡片；{pending_count} 个 Action Item 进入待确认，未自动创建任务。"
    return f"本次发送 {sent_count} 张卡片；未抽取到可落地 Action Item。"


def summarize_workflow_input(workflow_input: Any, content_limit: int) -> dict[str, Any]:
    """生成不会刷屏的输入摘要，避免把完整妙记正文写到控制台。"""

    return {
        "meeting_id": workflow_input.meeting_id,
        "calendar_event_id": workflow_input.calendar_event_id,
        "minute_token": workflow_input.minute_token,
        "project_id": workflow_input.project_id,
        "topic": workflow_input.topic,
        "source_type": workflow_input.source_type,
        "source_id": workflow_input.source_id,
        "source_url": workflow_input.source_url,
        "raw_text_length": len(workflow_input.raw_text),
        "raw_text_excerpt": workflow_input.raw_text[:content_limit],
    }


def run_write_phase(
    args: argparse.Namespace,
    settings: Any,
    registry: Any,
    policy: AgentPolicy,
    storage: MeetFlowStorage,
    context: WorkflowContext,
    artifacts: Any,
) -> dict[str, Any]:
    """执行灰度写入：发送卡片并保存待确认任务，不自动创建任务。"""

    results: dict[str, Any] = {"created_tasks": [], "skipped_tasks": [], "sent_cards": []}
    for action_item in artifacts.action_items:
        results["skipped_tasks"].append(
            {
                "item_id": action_item.item_id,
                "title": action_item.title,
                "reason": action_item.extra.get("confirm_reason", "requires_human_confirmation"),
            }
        )

    successful_created_tasks = [
        item
        for item in results["created_tasks"]
        if item.get("tool_result", {}).get("status") == "success"
    ]
    if args.send_card or args.send_reaction_cards or successful_created_tasks:
        receive_id = args.chat_id or settings.feishu.default_chat_id
        if not receive_id:
            results["sent_cards"].append({"status": "skipped", "reason": "缺少 chat_id/default_chat_id"})
        else:
            if args.send_card:
                pending_values = [build_pending_task_button_value(item) for item in artifacts.pending_action_items]
                save_pending_action_values(
                    settings,
                    pending_values,
                    source={
                        "minute_token": context.minute_token,
                        "meeting_id": context.meeting_id,
                        "chat_id": receive_id,
                        "receive_id_type": args.receive_id_type,
                    },
                )
                for key, card in artifacts.card_payloads.items():
                    if key == "pending_card":
                        continue
                    if key == "pending_card" and not artifacts.pending_action_items:
                        continue
                    card_result = execute_with_policy(
                        registry=registry,
                        policy=policy,
                        context=context,
                        tool_name="im.send_card",
                        arguments={
                            "title": card.get("header", {}).get("title", {}).get("content", "MeetFlow 会后总结"),
                            "summary": "MeetFlow 会后总结与任务确认卡片",
                            "card": card,
                            "receive_id": receive_id,
                            "receive_id_type": args.receive_id_type,
                            "identity": "tenant",
                            "idempotency_key": f"{context.minute_token}:{key}:{int(time.time())}",
                        },
                        allow_write=True,
                        storage=storage,
                    )
                    results["sent_cards"].append({"card": key, "tool_result": card_result.to_dict()})
                for item in artifacts.pending_action_items:
                    item_id = getattr(item, "item_id", "")
                    card = build_pending_action_item_button_card(artifacts, item)
                    card_result = execute_with_policy(
                        registry=registry,
                        policy=policy,
                        context=context,
                        tool_name="im.send_card",
                        arguments={
                            "title": card.get("header", {}).get("title", {}).get("content", "MeetFlow 待确认任务"),
                            "summary": f"MeetFlow 待确认任务：{getattr(item, 'title', '') or item_id}",
                            "card": card,
                            "receive_id": receive_id,
                            "receive_id_type": args.receive_id_type,
                            "identity": "tenant",
                            "idempotency_key": f"{context.minute_token}:pending_button_card:{item_id}:{int(time.time())}",
                        },
                        allow_write=True,
                        storage=storage,
                    )
                    message_id = str(card_result.data.get("message_id") or "")
                    if message_id:
                        bind_pending_action_message(settings, item_id=item_id, message_id=message_id, chat_id=receive_id)
                    results["sent_cards"].append(
                        {"card": "pending_button_card", "item_id": item_id, "tool_result": card_result.to_dict()}
                    )
            if args.send_reaction_cards:
                pending_values = [build_pending_task_button_value(item) for item in artifacts.pending_action_items]
                save_pending_action_values(
                    settings,
                    pending_values,
                    source={
                        "minute_token": context.minute_token,
                        "meeting_id": context.meeting_id,
                        "chat_id": receive_id,
                        "receive_id_type": args.receive_id_type,
                        "interaction_mode": "reaction",
                    },
                )
                for item in artifacts.pending_action_items:
                    item_id = getattr(item, "item_id", "")
                    text = build_pending_action_item_reaction_text(artifacts, item)
                    text_result = execute_with_policy(
                        registry=registry,
                        policy=policy,
                        context=context,
                        tool_name="im.send_text",
                        arguments={
                            "text": text,
                            "receive_id": receive_id,
                            "receive_id_type": args.receive_id_type,
                            "identity": "tenant",
                            "idempotency_key": f"{context.minute_token}:reaction_message:{item_id}:{int(time.time())}",
                        },
                        allow_write=True,
                        storage=storage,
                    )
                    if text_result.status == "success":
                        message_id = str(text_result.data.get("message_id") or "")
                        bind_pending_action_message(settings, item_id=item_id, message_id=message_id, chat_id=receive_id)
                    results["sent_cards"].append({"card": "pending_reaction_message", "item_id": item_id, "tool_result": text_result.to_dict()})
            if successful_created_tasks:
                created_card = build_auto_created_tasks_card(artifacts, successful_created_tasks)
                card_result = execute_with_policy(
                    registry=registry,
                    policy=policy,
                    context=context,
                    tool_name="im.send_card",
                    arguments={
                        "title": created_card.get("header", {}).get("title", {}).get("content", "MeetFlow 已创建任务提醒"),
                        "summary": "MeetFlow 已创建任务提醒",
                        "card": created_card,
                        "receive_id": receive_id,
                        "receive_id_type": args.receive_id_type,
                        "identity": "tenant",
                        "idempotency_key": f"{context.minute_token}:auto_created_tasks:{int(time.time())}",
                    },
                    allow_write=True,
                    storage=storage,
                )
                results["sent_cards"].append({"card": "auto_created_tasks_card", "tool_result": card_result.to_dict()})
    return results


def execute_with_policy(
    registry: Any,
    policy: AgentPolicy,
    context: WorkflowContext,
    tool_name: str,
    arguments: dict[str, Any],
    allow_write: bool,
    storage: MeetFlowStorage,
) -> Any:
    """通过 ToolRegistry + AgentPolicy 执行一次工具调用。"""

    tool = registry.get(tool_name)
    tool_call = AgentToolCall(
        call_id=f"post_meeting_live:{tool.llm_name}:{int(time.time() * 1000)}",
        tool_name=tool.llm_name,
        arguments=arguments,
    )
    decision = policy.authorize_tool_call(
        context=context,
        tool=tool,
        tool_call=tool_call,
        allow_write=allow_write,
        storage=storage,
    )
    if not decision.is_allowed():
        from core import AgentToolResult

        return AgentToolResult(
            call_id=tool_call.call_id,
            tool_name=tool.internal_name,
            status=decision.status,
            content=f"工具 {tool.internal_name} 被 AgentPolicy 拦截：{decision.reason}",
            data={"policy_decision": decision.to_dict()},
            error_message=decision.reason,
            started_at=int(time.time()),
            finished_at=int(time.time()),
        )
    tool_call.arguments = decision.patched_arguments
    return registry.execute(tool_call)


def resolve_owner_open_ids(registry: Any, owner: str) -> list[str]:
    """用通讯录工具把负责人文本解析为 open_id。"""

    owner_text = owner.strip()
    if not owner_text:
        return []
    if is_group_owner_candidate(owner_text):
        return []
    if owner_text in {"我", "本人", "自己"}:
        result = registry.execute(AgentToolCall(call_id="resolve_current_user", tool_name="contact_get_current_user", arguments={}))
        open_id = str(result.data.get("open_id") or result.data.get("user_id") or "")
        return [open_id] if open_id else []

    result = registry.execute(
        AgentToolCall(
            call_id=f"resolve_owner:{owner_text}",
            tool_name="contact_search_user",
            arguments={"query": owner_text, "page_size": 5, "identity": "user"},
        )
    )
    items = result.data.get("items") or result.data.get("users") or []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            open_id = str(item.get("open_id") or item.get("user_id") or item.get("id") or "")
            if open_id:
                return [open_id]
    return []


def build_pending_action_item_reaction_text(artifacts: Any, item: Any) -> str:
    """构造可点 reaction 的普通文本消息。

    飞书 interactive card 在部分客户端没有表情入口，因此一键确认载体使用
    普通文本消息；watcher 通过这条消息的 message_id 找回 Action Item。
    """

    summary = getattr(artifacts, "meeting_summary", None)
    extra = getattr(item, "extra", {}) or {}
    evidence_refs = list(getattr(item, "evidence_refs", []) or [])
    snippet = ""
    if evidence_refs:
        snippet = str(getattr(evidence_refs[0], "snippet", "") or "")[:160]
    lines = [
        "MeetFlow 待确认任务",
        f"会议：{getattr(summary, 'topic', '') or '待识别会议'}",
        f"任务：{getattr(item, 'title', '') or '未命名任务'}",
        f"任务 ID：{getattr(item, 'item_id', '')}",
        f"负责人：{getattr(item, 'owner', '') or '待补充'}",
        f"截止时间：{getattr(item, 'due_date', '') or '待补充'}",
        f"待确认原因：{extra.get('confirm_reason', '') or '待人工复核'}",
    ]
    if snippet:
        lines.append(f"证据：{snippet}")
    lines.extend(
        [
            "",
            "操作：直接回复这条消息 `确认` = 创建任务；回复 `拒绝` = 不创建。",
            f"需要补字段时回复：确认创建 {getattr(item, 'item_id', '')} 负责人=姓名 截止=明天",
        ]
    )
    return "\n".join(lines)


def count_card_elements(card: dict[str, Any]) -> int:
    """兼容旧版 `elements` 和 schema 2.0 `body.elements` 的元素计数。"""

    if not isinstance(card, dict):
        return 0
    elements = card.get("elements")
    if isinstance(elements, list):
        return len(elements)
    body = card.get("body")
    if isinstance(body, dict) and isinstance(body.get("elements"), list):
        return len(body["elements"])
    return 0


def ActionItemFromToolData(data: dict[str, Any]) -> Any:
    """从工具返回数据中还原最小 ActionItem，便于保存 task_mapping。"""

    from core import ActionItem

    if "item_id" in data and "title" in data:
        return ActionItem(
            item_id=str(data.get("item_id") or ""),
            title=str(data.get("title") or ""),
            owner=str(data.get("owner") or ""),
            due_date=str(data.get("due_date") or ""),
            status=str(data.get("status") or "todo"),
        )
    return ActionItem(
        item_id=str(data.get("guid") or data.get("task_id") or ""),
        title=str(data.get("summary") or ""),
        status=str(data.get("status") or "todo"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
