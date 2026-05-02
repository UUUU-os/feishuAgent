from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config.loader import Settings


COMMAND_PREFIX_TO_ACTION = {
    "确认创建": "confirm_create_task",
    "确认任务": "confirm_create_task",
    "拒绝创建": "reject_create_task",
    "拒绝任务": "reject_create_task",
    "修改任务": "edit_task_fields",
}


@dataclass(slots=True)
class ConfirmationCommand:
    """群消息中的待确认任务操作口令。"""

    action: str
    item_id: str
    owner_override: str = ""
    due_date_override: str = ""
    raw_text: str = ""
    message_id: str = ""
    sender_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def has_overrides(self) -> bool:
        """是否携带字段修改。"""

        return bool(self.owner_override or self.due_date_override)


def pending_actions_path(settings: Settings) -> Path:
    """待确认任务本地 registry 路径。"""

    return Path(settings.storage.db_path).parent / "post_meeting_pending_actions.json"


def watcher_state_path(settings: Settings) -> Path:
    """群消息监听器状态路径。"""

    return Path(settings.storage.db_path).parent / "post_meeting_confirmation_watcher_state.json"


def save_pending_action_values(
    settings: Settings,
    action_values: list[dict[str, Any]],
    source: dict[str, Any] | None = None,
) -> None:
    """保存待确认任务按钮上下文，供群消息确认时按 item_id 找回。"""

    if not action_values:
        return
    path = pending_actions_path(settings)
    data = load_json_object(path)
    now = int(time.time())
    source_payload = dict(source or {})
    for value in action_values:
        item_id = str(value.get("item_id") or "").strip()
        if not item_id:
            continue
        existing = data.get(item_id, {})
        if isinstance(existing, dict):
            merged_value = dict(existing.get("value") or {})
            merged_value.update(value)
        else:
            merged_value = dict(value)
        data[item_id] = {
            "item_id": item_id,
            "value": merged_value,
            "source": source_payload,
            "status": data.get(item_id, {}).get("status", "pending") if isinstance(data.get(item_id), dict) else "pending",
            "updated_at": now,
            "created_at": data.get(item_id, {}).get("created_at", now) if isinstance(data.get(item_id), dict) else now,
        }
    write_json_object(path, data)


def load_pending_action_value(settings: Settings, item_id: str) -> dict[str, Any] | None:
    """按任务 ID 读取待确认任务上下文。"""

    record = load_json_object(pending_actions_path(settings)).get(item_id)
    if not isinstance(record, dict):
        return None
    value = record.get("value")
    return dict(value) if isinstance(value, dict) else None


def update_pending_action_value(
    settings: Settings,
    item_id: str,
    updates: dict[str, Any],
    status: str = "pending",
) -> dict[str, Any] | None:
    """更新本地待确认任务字段。"""

    path = pending_actions_path(settings)
    data = load_json_object(path)
    record = data.get(item_id)
    if not isinstance(record, dict) or not isinstance(record.get("value"), dict):
        return None
    value = dict(record["value"])
    value.update({key: val for key, val in updates.items() if val})
    record["value"] = value
    record["status"] = status
    record["updated_at"] = int(time.time())
    data[item_id] = record
    write_json_object(path, data)
    return value


def claim_pending_action_status(
    settings: Settings,
    item_id: str,
    next_status: str,
    *,
    allowed_statuses: set[str] | None = None,
    result: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """抢占一条待确认任务的处理状态。

    卡片更新依赖飞书客户端刷新，真实群聊里用户可能在旧按钮消失前连续点击。
    因此在调用飞书写接口前先把本地 registry 标记为处理中，让后续回调能被
    `guard_pending_action_transition()` 拦截，避免确认和拒绝交叉生效。
    """

    if not item_id:
        return True, ""
    path = pending_actions_path(settings)
    data = load_json_object(path)
    record = data.get(item_id)
    if not isinstance(record, dict):
        return True, ""
    current_status = str(record.get("status") or "pending")
    if allowed_statuses is not None and current_status not in allowed_statuses:
        return False, current_status
    record["status"] = next_status
    record["updated_at"] = int(time.time())
    if result is not None:
        record["result"] = result
    data[item_id] = record
    write_json_object(path, data)
    return True, current_status


def bind_pending_action_message(
    settings: Settings,
    item_id: str,
    message_id: str,
    chat_id: str = "",
) -> None:
    """把待确认任务绑定到一条飞书消息。

    Reaction 只能定位到消息，不能定位到卡片内部元素。因此 reaction 模式下
    必须保存 message_id -> item_id 的映射。
    """

    if not item_id or not message_id:
        return
    path = pending_actions_path(settings)
    data = load_json_object(path)
    record = data.get(item_id)
    if not isinstance(record, dict):
        return
    source = record.get("source")
    if not isinstance(source, dict):
        source = {}
    source["message_id"] = message_id
    if chat_id:
        source["chat_id"] = chat_id
    record["source"] = source
    record["status"] = record.get("status") or "pending"
    record["updated_at"] = int(time.time())
    data[item_id] = record
    write_json_object(path, data)


def load_pending_action_records(settings: Settings) -> dict[str, dict[str, Any]]:
    """读取全部待确认任务 registry。"""

    data = load_json_object(pending_actions_path(settings))
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def mark_pending_action_status(settings: Settings, item_id: str, status: str, result: dict[str, Any] | None = None) -> None:
    """记录待确认任务处理状态。"""

    path = pending_actions_path(settings)
    data = load_json_object(path)
    record = data.get(item_id)
    if not isinstance(record, dict):
        return
    record["status"] = status
    record["updated_at"] = int(time.time())
    if result is not None:
        record["result"] = result
    data[item_id] = record
    write_json_object(path, data)


def parse_confirmation_command(text: str) -> ConfirmationCommand | None:
    """解析群消息确认口令。

    支持：
    - 确认创建 action_xxx
    - 确认创建 action_xxx 负责人=张三 截止=明天
    - 修改任务 action_xxx 负责人=张三 截止=明天
    - 拒绝创建 action_xxx
    """

    normalized = normalize_message_text(text)
    if not normalized:
        return None
    pattern = r"^(确认创建|确认任务|拒绝创建|拒绝任务|修改任务)\s+(`?)([A-Za-z0-9_\-:]+)\2(?:\s+(.+))?$"
    match = re.search(pattern, normalized)
    if not match:
        return None
    prefix = match.group(1)
    item_id = match.group(3)
    tail = match.group(4) or ""
    fields = parse_command_fields(tail)
    return ConfirmationCommand(
        action=COMMAND_PREFIX_TO_ACTION[prefix],
        item_id=item_id,
        owner_override=fields.get("owner", ""),
        due_date_override=fields.get("due_date", ""),
        raw_text=normalized,
    )


def parse_command_fields(text: str) -> dict[str, str]:
    """解析口令中的负责人和截止时间。"""

    fields: dict[str, str] = {}
    owner_match = re.search(r"(?:负责人|owner)\s*[=:：]\s*([^\s，,；;]+)", text, flags=re.IGNORECASE)
    due_match = re.search(r"(?:截止|截止时间|due|due_date)\s*[=:：]\s*([^\s，,；;]+)", text, flags=re.IGNORECASE)
    if owner_match:
        fields["owner"] = owner_match.group(1).strip()
    if due_match:
        fields["due_date"] = due_match.group(1).strip()
    return fields


def normalize_message_text(text: str) -> str:
    """规范化飞书消息文本，去除首尾空白和多余换行。"""

    text = re.sub(r"@[^\s]+\s*", "", text)
    return re.sub(r"\s+", " ", text.replace("\u200b", " ")).strip()


def extract_text_from_message(message: dict[str, Any]) -> str:
    """从飞书消息对象中提取可解析文本。"""

    content = message.get("content")
    if content is None:
        body = message.get("body")
        if isinstance(body, dict):
            content = body.get("content", "")
        else:
            content = ""

    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content
    elif isinstance(content, dict):
        parsed = content
    else:
        return ""
    if not isinstance(parsed, dict):
        return ""
    if isinstance(parsed.get("text"), str):
        return parsed["text"]
    if isinstance(parsed.get("content"), str):
        return parsed["content"]
    return json.dumps(parsed, ensure_ascii=False)


def load_watcher_state(settings: Settings) -> dict[str, Any]:
    """读取群消息监听器状态。"""

    return load_json_object(watcher_state_path(settings))


def save_watcher_state(settings: Settings, state: dict[str, Any]) -> None:
    """保存群消息监听器状态。"""

    write_json_object(watcher_state_path(settings), state)


def load_json_object(path: Path) -> dict[str, Any]:
    """读取 JSON object 文件。"""

    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_json_object(path: Path, data: dict[str, Any]) -> None:
    """原子性写入 JSON object。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
