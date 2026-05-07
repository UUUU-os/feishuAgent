from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.logging import get_logger, get_trace_id


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVENT_PATH = PROJECT_ROOT / "storage" / "workflow_events.jsonl"

SENSITIVE_KEYWORDS = (
    "access_token",
    "refresh_token",
    "app_secret",
    "api_key",
    "authorization",
    "bearer",
    "secret",
    "password",
    "client_secret",
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(api[_-]?key[\"'=:\s]+)([A-Za-z0-9._\-]+)", re.IGNORECASE),
    re.compile(r"(access[_-]?token[\"'=:\s]+)([A-Za-z0-9._\-]+)", re.IGNORECASE),
    re.compile(r"(refresh[_-]?token[\"'=:\s]+)([A-Za-z0-9._\-]+)", re.IGNORECASE),
)
ID_KEYS = {
    "open_id",
    "user_id",
    "owner_id",
    "document_id",
    "minute_token",
    "calendar_id",
    "calendar_event_id",
    "meeting_id",
    "task_id",
    "receive_id",
}


@dataclass(slots=True)
class EventWriterSettings:
    """结构化事件写入配置。

    这里单独定义轻量配置对象，避免观测模块强依赖 config.loader。
    """

    structured_events_enabled: bool = True
    structured_event_path: str = str(DEFAULT_EVENT_PATH)
    record_sensitive_payload: bool = False
    max_event_chars: int = 16000
    max_field_chars: int = 1000
    mask_ids: bool = True
    daily_rotate: bool = False


@dataclass(slots=True)
class StructuredEventWriter:
    """把 Agent 运行中的关键事件写成 JSONL。

    写入失败不能影响主业务流程；观测系统坏了不应该让 Agent 不可用。
    """

    settings: EventWriterSettings

    def emit(self, event_type: str, **fields: Any) -> None:
        """写入一条结构化事件。"""

        if not self.settings.structured_events_enabled:
            return

        event = {
            "event_type": event_type,
            "trace_id": fields.pop("trace_id", None) or get_trace_id(),
            "timestamp": fields.pop("timestamp", None) or utc_now_iso(),
            **fields,
        }
        sanitized = sanitize_event(
            event,
            record_sensitive_payload=self.settings.record_sensitive_payload,
            max_field_chars=self.settings.max_field_chars,
            mask_ids=self.settings.mask_ids,
        )
        text = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
        if len(text) > self.settings.max_event_chars:
            sanitized = truncate_oversized_event(sanitized, self.settings.max_event_chars)
            text = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))

        try:
            path = self._resolve_event_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as file:
                file.write(text + "\n")
        except Exception as error:  # noqa: BLE001 - 观测写入失败只降级为 warning。
            get_logger("meetflow.observability").warning("结构化事件写入失败 event_type=%s error=%s", event_type, error)

    def _resolve_event_path(self) -> Path:
        """按配置解析事件文件路径，支持可选按天切分。"""

        path = Path(self.settings.structured_event_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not self.settings.daily_rotate:
            return path
        date_suffix = datetime.now(timezone.utc).strftime("%Y%m%d")
        return path.with_name(f"{path.stem}.{date_suffix}{path.suffix}")


_GLOBAL_EVENT_WRITER: StructuredEventWriter | None = None


def configure_structured_events(settings: Any | None = None) -> StructuredEventWriter:
    """根据配置初始化全局结构化事件写入器。"""

    global _GLOBAL_EVENT_WRITER
    final_settings = build_event_writer_settings(settings)
    _GLOBAL_EVENT_WRITER = StructuredEventWriter(final_settings)
    return _GLOBAL_EVENT_WRITER


def get_event_writer() -> StructuredEventWriter:
    """读取全局事件写入器；未初始化时使用安全默认值。"""

    global _GLOBAL_EVENT_WRITER
    if _GLOBAL_EVENT_WRITER is None:
        _GLOBAL_EVENT_WRITER = StructuredEventWriter(EventWriterSettings())
    return _GLOBAL_EVENT_WRITER


def emit_structured_event(event_type: str, **fields: Any) -> None:
    """便捷写入结构化事件。"""

    get_event_writer().emit(event_type, **fields)


def build_event_writer_settings(settings: Any | None = None) -> EventWriterSettings:
    """从 Settings.observability 或类似对象构造事件写入配置。"""

    if settings is None:
        return EventWriterSettings()
    return EventWriterSettings(
        structured_events_enabled=bool(getattr(settings, "structured_events_enabled", True)),
        structured_event_path=str(getattr(settings, "structured_event_path", DEFAULT_EVENT_PATH)),
        record_sensitive_payload=bool(getattr(settings, "record_sensitive_payload", False)),
        max_event_chars=int(getattr(settings, "max_event_chars", 16000) or 16000),
        max_field_chars=int(getattr(settings, "max_field_chars", 1000) or 1000),
        mask_ids=bool(getattr(settings, "mask_ids", True)),
        daily_rotate=bool(getattr(settings, "daily_rotate", False)),
    )


def utc_now_iso() -> str:
    """生成 UTC ISO 时间戳，便于跨机器聚合。"""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def duration_ms_since(started_at: float) -> int:
    """根据 perf_counter 起点计算毫秒耗时。"""

    return int((time.perf_counter() - started_at) * 1000)


def sanitize_event(
    value: Any,
    record_sensitive_payload: bool = False,
    max_field_chars: int = 1000,
    mask_ids: bool = True,
    key: str = "",
) -> Any:
    """递归清洗事件字段，避免密钥和超长正文进入日志。"""

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            child_key = str(raw_key)
            normalized_key = child_key.lower()
            if is_sensitive_key(normalized_key) and not record_sensitive_payload:
                cleaned[child_key] = mask_secret(str(raw_value or ""))
                continue
            if mask_ids and normalized_key in ID_KEYS:
                cleaned[child_key] = mask_id(str(raw_value or ""))
                continue
            cleaned[child_key] = sanitize_event(
                raw_value,
                record_sensitive_payload=record_sensitive_payload,
                max_field_chars=max_field_chars,
                mask_ids=mask_ids,
                key=child_key,
            )
        return cleaned
    if isinstance(value, list):
        return [
            sanitize_event(
                item,
                record_sensitive_payload=record_sensitive_payload,
                max_field_chars=max_field_chars,
                mask_ids=mask_ids,
                key=key,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            sanitize_event(
                item,
                record_sensitive_payload=record_sensitive_payload,
                max_field_chars=max_field_chars,
                mask_ids=mask_ids,
                key=key,
            )
            for item in value
        ]
    if isinstance(value, str):
        text = value if record_sensitive_payload else mask_sensitive_text(value)
        return truncate_text(text, max_field_chars)
    return value


def truncate_oversized_event(event: dict[str, Any], max_event_chars: int) -> dict[str, Any]:
    """事件整体过大时做二次粗截断。"""

    compact = dict(event)
    compact["_event_truncated"] = True
    budget = max(200, max_event_chars // max(len(compact), 1))
    return sanitize_event(compact, max_field_chars=budget)


def is_sensitive_key(key: str) -> bool:
    """判断字段名是否明显携带密钥或 token。"""

    return any(keyword in key for keyword in SENSITIVE_KEYWORDS)


def mask_secret(value: str) -> str:
    """脱敏密钥类字符串。"""

    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}...{text[-4:]}"


def mask_id(value: str, prefix_chars: int = 6, suffix_chars: int = 4) -> str:
    """脱敏业务 ID，保留少量前后缀便于排查。"""

    text = str(value or "")
    if not text:
        return ""
    if len(text) <= prefix_chars + suffix_chars + 3:
        return text
    return f"{text[:prefix_chars]}...{text[-suffix_chars:]}"


def mask_sensitive_text(text: str) -> str:
    """对错误 body 或普通字符串中的敏感片段做脱敏。"""

    masked = str(text or "")
    for pattern in SENSITIVE_VALUE_PATTERNS:
        masked = pattern.sub(
            lambda match: (
                f"{match.group(1)}{mask_secret(match.group(2))}"
                if len(match.groups()) >= 2
                else mask_secret(match.group(0))
            ),
            masked,
        )
    return masked


def truncate_text(value: str, max_chars: int) -> str:
    """截断过长字符串。"""

    text = str(value or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "...（已截断）"


def safe_error_message(error: Exception | str, max_chars: int = 1000) -> str:
    """生成可写入日志和用户结果的安全错误摘要。"""

    message = str(error)
    return truncate_text(mask_sensitive_text(message), max_chars)


def summarize_arguments(arguments: dict[str, Any] | None, record_sensitive_payload: bool = False) -> dict[str, Any]:
    """默认只记录工具参数 key；DEBUG 场景才记录脱敏值。"""

    final_arguments = dict(arguments or {})
    keys = sorted(str(key) for key in final_arguments.keys())
    if not record_sensitive_payload:
        return {"argument_keys": keys}
    return {
        "argument_keys": keys,
        "arguments": sanitize_event(final_arguments, record_sensitive_payload=False),
    }


def summarize_tool_result(data: dict[str, Any] | None) -> dict[str, Any]:
    """把工具返回数据压缩成稳定摘要。"""

    final_data = data or {}
    summary: dict[str, Any] = {}
    if "count" in final_data:
        summary["count"] = final_data.get("count")
    if "omitted_count" in final_data:
        summary["omitted_count"] = final_data.get("omitted_count")
    if "low_confidence" in final_data:
        summary["low_confidence"] = final_data.get("low_confidence")
    if isinstance(final_data.get("items"), list):
        summary.setdefault("count", len(final_data["items"]))
    if isinstance(final_data.get("hits"), list):
        summary["hit_count"] = len(final_data["hits"])
    if "title" in final_data:
        summary["title"] = final_data.get("title")
    if "created" in final_data:
        summary["created"] = final_data.get("created")
    return summary or {"keys": sorted(str(key) for key in final_data.keys())[:20]}


def summarize_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    """提取 LLM 请求工具调用的安全摘要。"""

    summaries: list[dict[str, Any]] = []
    for call in tool_calls:
        arguments = getattr(call, "arguments", {}) or {}
        summaries.append(
            {
                "call_id": getattr(call, "call_id", ""),
                "tool_name": getattr(call, "tool_name", ""),
                "argument_keys": sorted(str(key) for key in arguments.keys()),
            }
        )
    return summaries


def normalize_url_template(url_or_path: str) -> str:
    """把外部 URL 归一为不泄露具体 ID 的路径模板。"""

    parsed = urlparse(url_or_path)
    path = parsed.path or url_or_path
    if "/open-apis/" in path:
        path = path.split("/open-apis/", 1)[1]
    path = "/" + path.lstrip("/")
    replacements = [
        (r"/calendars/[^/]+", "/calendars/{calendar_id}"),
        (r"/documents/[^/]+", "/documents/{document_id}"),
        (r"/minutes/[^/]+", "/minutes/{minute_token}"),
        (r"/tasks/[^/]+", "/tasks/{task_id}"),
    ]
    normalized = path
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def infer_feishu_api_name(url_or_path: str) -> str:
    """从飞书路径推断一个稳定 API 名称。"""

    path = normalize_url_template(url_or_path)
    if "tenant_access_token" in path:
        return "auth.tenant_access_token"
    if "oauth/token" in path:
        return "auth.oauth_token"
    if "device_authorization" in path:
        return "auth.device_authorization"
    if "calendar" in path and "instance_view" in path:
        return "calendar.instance_view"
    if "calendars/primary" in path:
        return "calendar.primary"
    if "docs_ai" in path and "documents" in path:
        return "docs.fetch"
    if "minutes" in path and "artifacts" in path:
        return "minutes.artifacts"
    if "minutes" in path:
        return "minutes.get"
    if "task" in path and "/tasks" in path:
        return "task.tasks"
    if "im/" in path and "messages" in path:
        return "im.messages"
    if "search/v1/user" in path:
        return "contact.search_user"
    return path.strip("/").replace("/", ".") or "unknown"
