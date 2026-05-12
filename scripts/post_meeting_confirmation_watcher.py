from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/post_meeting_confirmation_watcher.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuClient, create_feishu_tool_registry
from config import load_settings
from core import (
    AgentPolicy,
    AgentToolCall,
    ConfirmationCommand,
    Event,
    MeetFlowStorage,
    WorkflowContext,
    configure_logging,
    extract_text_from_message,
    get_logger,
    handle_post_meeting_card_callback,
    load_pending_action_records,
    load_pending_action_value,
    load_watcher_state,
    mark_pending_action_status,
    parse_confirmation_command,
    save_watcher_state,
    update_pending_action_value,
)
from scripts.meetflow_agent_live_test import save_token_bundle


CONFIRM_REACTIONS = {"CheckMark", "DONE", "OK", "THUMBSUP", "Yes", "LGTM"}
REJECT_REACTIONS = {"CrossMark", "No", "ThumbsDown", "ERROR"}


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="M4 待确认任务群消息监听器。")
    parser.add_argument("--chat-id", default="", help="监听的群 chat_id；不传使用配置 default_chat_id。")
    parser.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取群消息使用的身份。")
    parser.add_argument("--interval", type=float, default=5.0, help="轮询间隔秒数。")
    parser.add_argument("--since-minutes", type=int, default=30, help="首次启动回看最近多少分钟。")
    parser.add_argument("--page-size", type=int, default=30, help="每次读取消息条数，最大 50。")
    parser.add_argument("--watch-reactions", action="store_true", help="轮询待确认任务消息上的表情反应。")
    parser.add_argument("--once", action="store_true", help="只轮询一次，便于自测。")
    parser.add_argument("--dry-run", action="store_true", help="只解析口令，不执行写操作。")
    return parser.parse_args()


def main() -> int:
    """启动群消息轮询，处理待确认任务口令。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.post_meeting.confirmation_watcher")
    storage = MeetFlowStorage(settings.storage)
    storage.initialize()
    client = FeishuClient(settings.feishu, user_token_callback=lambda bundle: save_token_bundle(settings, bundle))
    registry = create_feishu_tool_registry(client, default_chat_id=settings.feishu.default_chat_id)
    policy = AgentPolicy()
    chat_id = args.chat_id or settings.feishu.default_chat_id
    if not chat_id:
        raise SystemExit("请传入 --chat-id，或在配置中设置 feishu.default_chat_id")

    logger.info("M4 待确认任务群消息监听器启动 chat_id=%s identity=%s", chat_id, args.identity)
    while True:
        try:
            processed = poll_once(
                args=args,
                settings=settings,
                client=client,
                registry=registry,
                policy=policy,
                storage=storage,
                chat_id=chat_id,
                logger=logger,
            )
        except FeishuAPIError as error:
            message = build_permission_hint(str(error), args.identity)
            logger.error(message)
            print(message)
            return 2
        if args.once:
            print({"processed": processed})
            return 0
        time.sleep(max(args.interval, 1.0))


def poll_once(
    args: argparse.Namespace,
    settings: Any,
    client: FeishuClient,
    registry: Any,
    policy: AgentPolicy,
    storage: MeetFlowStorage,
    chat_id: str,
    logger: Any,
) -> int:
    """轮询一次群消息并处理确认口令。"""

    state = load_watcher_state(settings)
    handled_count = 0
    if args.watch_reactions:
        handled_count += poll_reactions_once(
            args=args,
            settings=settings,
            client=client,
            registry=registry,
            policy=policy,
            storage=storage,
            chat_id=chat_id,
            logger=logger,
        )
        state = load_watcher_state(settings)
    chat_state = state.setdefault(chat_id, {})
    processed_ids = list(chat_state.get("processed_message_ids") or [])
    processed_set = set(processed_ids)
    start_time = int(chat_state.get("last_seen_time") or (time.time() - args.since_minutes * 60))
    end_time = int(time.time()) + 5
    data = client.list_chat_messages(
        chat_id=chat_id,
        start_time=start_time,
        end_time=end_time,
        sort_type="ByCreateTimeAsc",
        page_size=args.page_size,
        identity=args.identity,
    )
    messages = data.get("items") or data.get("messages") or []
    latest_time = start_time
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_id = str(message.get("message_id") or "")
        if message_id and message_id in processed_set:
            continue
        latest_time = max(latest_time, parse_message_time(message))
        text = extract_text_from_message(message)
        command = parse_confirmation_command(text)
        if not command:
            command = build_reply_confirmation_command(settings=settings, message=message, text=text)
        if not command:
            if message_id:
                processed_ids.append(message_id)
            continue
        command.message_id = message_id
        command.sender_id = extract_sender_id(message)
        logger.info("识别到 M4 确认口令 message_id=%s action=%s item_id=%s", message_id, command.action, command.item_id)
        if args.dry_run:
            handled_count += 1
        else:
            result_text = handle_confirmation_command(
                command=command,
                settings=settings,
                client=client,
                registry=registry,
                policy=policy,
                storage=storage,
                chat_id=chat_id,
            )
            send_watcher_reply(
                registry=registry,
                policy=policy,
                storage=storage,
                chat_id=chat_id,
                text=result_text,
                idempotency_key=f"post_meeting_confirmation_reply:{message_id or command.item_id}:{command.action}",
            )
            handled_count += 1
        if message_id:
            processed_ids.append(message_id)
    chat_state["processed_message_ids"] = processed_ids[-500:]
    chat_state["last_seen_time"] = max(latest_time, end_time - 2)
    state[chat_id] = chat_state
    save_watcher_state(settings, state)
    return handled_count


def poll_reactions_once(
    args: argparse.Namespace,
    settings: Any,
    client: FeishuClient,
    registry: Any,
    policy: AgentPolicy,
    storage: MeetFlowStorage,
    chat_id: str,
    logger: Any,
) -> int:
    """轮询已绑定待确认任务消息上的 reaction。"""

    state = load_watcher_state(settings)
    reaction_state = state.setdefault("reactions", {})
    processed_reaction_ids = set(reaction_state.get("processed_reaction_ids") or [])
    handled_count = 0
    records = load_pending_action_records(settings)
    for item_id, record in records.items():
        if record.get("status") not in {"pending", "", None}:
            continue
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        message_id = str(source.get("message_id") or "")
        if not message_id:
            continue
        data = client.list_message_reactions(message_id=message_id, page_size=50, identity=args.identity)
        for reaction in list(data.get("items") or []):
            if not isinstance(reaction, dict):
                continue
            reaction_id = str(reaction.get("reaction_id") or "")
            if reaction_id and reaction_id in processed_reaction_ids:
                continue
            emoji_type = extract_reaction_emoji_type(reaction)
            action = reaction_to_action(emoji_type)
            if not action:
                continue
            logger.info("识别到 M4 reaction 确认 message_id=%s item_id=%s emoji=%s", message_id, item_id, emoji_type)
            command = ConfirmationCommand(
                action=action,
                item_id=item_id,
                raw_text=f"reaction:{emoji_type}",
                message_id=reaction_id or message_id,
                sender_id=extract_reaction_operator_id(reaction),
            )
            result_text = handle_confirmation_command(
                command=command,
                settings=settings,
                client=client,
                registry=registry,
                policy=policy,
                storage=storage,
                chat_id=chat_id,
            )
            send_watcher_reply(
                registry=registry,
                policy=policy,
                storage=storage,
                chat_id=chat_id,
                text=result_text,
                idempotency_key=f"post_meeting_reaction_reply:{reaction_id or message_id}:{action}",
            )
            handled_count += 1
            if reaction_id:
                processed_reaction_ids.add(reaction_id)
            print(result_text)
    reaction_state["processed_reaction_ids"] = list(processed_reaction_ids)[-1000:]
    state["reactions"] = reaction_state
    save_watcher_state(settings, state)
    return handled_count


def handle_confirmation_command(
    command: Any,
    settings: Any,
    client: FeishuClient,
    registry: Any,
    policy: AgentPolicy,
    storage: MeetFlowStorage,
    chat_id: str,
) -> str:
    """执行一个群消息确认口令。"""

    records = load_pending_action_records(settings)
    record = records.get(command.item_id)
    if not record:
        return f"没有找到待确认任务：{command.item_id}。请确认任务 ID 是否来自最新的 MeetFlow 待确认卡片。"
        
    status = record.get("status")
    if status == "created":
        return f"该任务（{command.item_id}）已由系统创建完毕，无需重复操作。"
    if status == "reject_create_task":
        return f"该任务（{command.item_id}）已被拒绝创建，操作已失效。"
    if status not in {"pending", "", None}:
        return f"该任务（{command.item_id}）当前状态为 '{status}'，无法执行此操作。"

    action_value = load_pending_action_value(settings, command.item_id)
    if not action_value:
        return f"没有找到待确认任务的缓存数据：{command.item_id}。"

    if command.action == "edit_task_fields":
        updates = {}
        if command.owner_override:
            updates["owner"] = command.owner_override
        if command.due_date_override:
            updates["due_date"] = command.due_date_override
        if not updates:
            return f"请补充修改字段，例如：修改任务 {command.item_id} 负责人=姓名 截止=明天"
        updated = update_pending_action_value(settings, command.item_id, updates=updates, status="pending")
        if not updated:
            return f"没有找到待确认任务：{command.item_id}。"
        return f"已更新待确认任务 {command.item_id}。回复 `确认创建 {command.item_id}` 即可创建。"

    action_value = dict(action_value)
    action_value["action"] = command.action
    if command.owner_override:
        action_value["owner_override"] = command.owner_override
    if command.due_date_override:
        action_value["due_date_override"] = command.due_date_override
    payload = {
        "header": {"event_id": command.message_id},
        "event": {
            "message": {"chat_id": chat_id, "message_id": command.message_id},
            "operator": {"open_id": command.sender_id},
            "action": {"value": action_value},
        },
    }
    result = handle_post_meeting_card_callback(
        payload=payload,
        settings=settings,
        client=client,
        storage=storage,
        policy=policy,
    )
    mark_pending_action_status(
        settings,
        command.item_id,
        status=resolve_pending_status_after_command(command.action, result.status),
        result={"status": result.status, "message": result.message, "data": result.data},
    )
    return result.message


def resolve_pending_status_after_command(action: str, result_status: str) -> str:
    """根据处理结果更新待确认任务状态。

    确认创建失败时不能把任务改成 `confirm_create_task`，否则用户补充字段后
    无法再次确认。只有真正创建成功才标记 created；拒绝才终止；其他失败
    保持 pending，允许继续修改或再次确认。
    """

    if action == "confirm_create_task":
        return "created" if result_status == "success" else "pending"
    if action == "reject_create_task":
        return "reject_create_task" if result_status == "success" else "pending"
    if action == "edit_task_fields":
        return "pending"
    return action if result_status == "success" else "pending"


def build_reply_confirmation_command(settings: Any, message: dict[str, Any], text: str) -> ConfirmationCommand | None:
    """把“回复这条消息：确认/拒绝”转换成待确认任务命令。

    飞书回复消息会携带 parent/root/thread 等引用字段。不同客户端返回字段略有
    差异，所以这里宽松匹配多个候选字段，只要能命中本地 `message_id -> item_id`
    registry，就不要求用户复制 action_id。
    """

    action = reply_text_to_action(text)
    if not action:
        return None
    item_id = find_pending_item_id_by_message_refs(settings, extract_message_reference_ids(message))
    if not item_id:
        return None
    return ConfirmationCommand(
        action=action,
        item_id=item_id,
        raw_text=text,
        message_id=str(message.get("message_id") or ""),
        sender_id=extract_sender_id(message),
    )


def reply_text_to_action(text: str) -> str:
    """把短回复文本映射成动作。"""

    import re
    text = re.sub(r"@[^\s]+\s*", "", str(text or ""))
    normalized = text.replace("\u200b", "").strip().strip("`").strip()
    normalized = normalized.replace("。", "").replace("！", "").replace("!", "")
    if normalized in {"确认", "创建", "确认创建", "同意", "通过", "yes", "Yes", "YES", "ok", "OK"}:
        return "confirm_create_task"
    if normalized in {"拒绝", "不创建", "取消", "否", "不同意", "no", "No", "NO"}:
        return "reject_create_task"
    return ""


def extract_message_reference_ids(message: dict[str, Any]) -> list[str]:
    """提取回复消息可能引用的父消息 ID。"""

    refs: list[str] = []
    for key in ["parent_id", "root_id", "thread_id", "upper_message_id", "message_id"]:
        value = message.get(key)
        if isinstance(value, str) and value:
            refs.append(value)
    parent = message.get("parent")
    if isinstance(parent, dict):
        for key in ["message_id", "parent_id", "root_id", "thread_id"]:
            value = parent.get(key)
            if isinstance(value, str) and value:
                refs.append(value)
    return list(dict.fromkeys(refs))


def find_pending_item_id_by_message_refs(settings: Any, message_ids: list[str]) -> str:
    """通过父消息 ID 查找待确认任务 ID。"""

    wanted = set(message_ids)
    if not wanted:
        return ""
    for item_id, record in load_pending_action_records(settings).items():
        if record.get("status") not in {"pending", "", None}:
            continue
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        if str(source.get("message_id") or "") in wanted:
            return item_id
    return ""


def send_watcher_reply(
    registry: Any,
    policy: AgentPolicy,
    storage: MeetFlowStorage,
    chat_id: str,
    text: str,
    idempotency_key: str,
) -> None:
    """通过 ToolRegistry + AgentPolicy 发送监听器处理结果。"""

    context = WorkflowContext(
        workflow_type="post_meeting_followup",
        trace_id=f"post_meeting_confirmation_watcher:{int(time.time())}",
        event=Event(
            event_id=idempotency_key,
            event_type="message.command",
            event_time=str(int(time.time())),
            source="post_meeting_confirmation_watcher",
            actor="",
            payload={"text": text},
            trace_id=f"post_meeting_confirmation_watcher:{int(time.time())}",
        ),
        raw_context={"decision": {"idempotency_key": idempotency_key}},
    )
    tool = registry.get("im.send_text")
    tool_call = AgentToolCall(
        call_id=f"post_meeting_confirmation_reply:{int(time.time() * 1000)}",
        tool_name=tool.llm_name,
        arguments={
            "text": text,
            "receive_id": chat_id,
            "receive_id_type": "chat_id",
            "identity": "tenant",
            "idempotency_key": idempotency_key,
        },
    )
    decision = policy.authorize_tool_call(context=context, tool=tool, tool_call=tool_call, allow_write=True, storage=storage)
    if decision.is_allowed():
        tool_call.arguments = decision.patched_arguments
        registry.execute(tool_call)


def parse_message_time(message: dict[str, Any]) -> int:
    """解析飞书消息时间，兼容秒和毫秒。"""

    raw = str(message.get("create_time") or message.get("update_time") or "0")
    try:
        value = int(raw)
    except ValueError:
        return int(time.time())
    if value > 10_000_000_000:
        value //= 1000
    return value


def extract_sender_id(message: dict[str, Any]) -> str:
    """提取消息发送者 open_id。"""

    sender = message.get("sender")
    if not isinstance(sender, dict):
        return ""
    sender_id = sender.get("id")
    if isinstance(sender_id, dict):
        return str(sender_id.get("open_id") or sender_id.get("user_id") or "")
    return str(sender.get("open_id") or sender.get("user_id") or sender_id or "")


def extract_reaction_emoji_type(reaction: dict[str, Any]) -> str:
    """提取 reaction 的 emoji_type。"""

    reaction_type = reaction.get("reaction_type")
    if isinstance(reaction_type, dict):
        return str(reaction_type.get("emoji_type") or "")
    return str(reaction.get("emoji_type") or reaction.get("reaction_type") or "")


def extract_reaction_operator_id(reaction: dict[str, Any]) -> str:
    """提取 reaction 操作者 ID。"""

    operator = reaction.get("operator")
    if not isinstance(operator, dict):
        return ""
    return str(operator.get("operator_id") or operator.get("open_id") or operator.get("user_id") or "")


def reaction_to_action(emoji_type: str) -> str:
    """把飞书 reaction 映射为待确认任务动作。"""

    if emoji_type in CONFIRM_REACTIONS:
        return "confirm_create_task"
    if emoji_type in REJECT_REACTIONS:
        return "reject_create_task"
    return ""


def build_permission_hint(error_text: str, identity: str) -> str:
    """把飞书消息读取权限错误转换成可操作提示。"""

    if "im:message.group_msg:get_as_user" in error_text:
        return (
            "读取群消息失败：当前 user 授权缺少 `im:message.group_msg:get_as_user`。"
            "请在飞书开发者后台添加该 scope、发布应用变更，然后重新执行用户 OAuth 授权。"
        )
    if "im:message.group_msg" in error_text:
        return (
            "读取群消息失败：当前机器人身份缺少 `im:message.group_msg`。"
            "请在飞书开发者后台添加该 scope、发布应用变更，并确认机器人仍在测试群中。"
        )
    if "im:message.reactions:read" in error_text:
        return (
            "读取消息表情失败：当前授权缺少 `im:message.reactions:read`。"
            "请在飞书开发者后台添加该 scope、发布应用变更，然后重新执行用户 OAuth 授权。"
        )
    return f"读取群消息失败（identity={identity}）：{error_text}"


if __name__ == "__main__":
    raise SystemExit(main())
