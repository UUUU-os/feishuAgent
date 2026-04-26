from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


# 配置文件的默认位置约定：
# 1. settings.example.json：仓库内的默认模板
# 2. settings.local.json：本地私有配置，可覆盖默认模板
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "settings.example.json"
LOCAL_CONFIG_PATH = CONFIG_DIR / "settings.local.json"


@dataclass(slots=True)
class AppSettings:
    """应用基础配置。"""

    name: str
    env: str
    debug: bool
    timezone: str


@dataclass(slots=True)
class FeishuSettings:
    """飞书开放平台相关配置。"""

    app_id: str
    app_secret: str
    base_url: str
    request_timeout_seconds: int
    max_retries: int
    default_identity: str
    redirect_uri: str
    user_oauth_scope: str
    user_access_token: str
    user_access_token_expires_at: int
    user_refresh_token: str
    user_refresh_token_expires_at: int
    bot_name: str
    default_chat_id: str


@dataclass(slots=True)
class LLMSettings:
    """模型服务配置。"""

    provider: str
    model: str
    api_base: str
    api_key: str
    temperature: float
    max_tokens: int
    reasoning_effort: str


@dataclass(slots=True)
class SchedulerSettings:
    """调度器配置，负责会前提醒和失败重试等时机控制。"""

    pre_meeting_minutes_before: int
    risk_scan_cron: str
    minute_retry_interval_minutes: int
    minute_retry_max_attempts: int


@dataclass(slots=True)
class RiskRuleSettings:
    """风险识别规则配置。"""

    stale_update_days: int
    due_soon_hours: int
    max_reminders_per_day: int


@dataclass(slots=True)
class LoggingSettings:
    """日志输出配置。"""

    level: str
    json_format: bool


@dataclass(slots=True)
class StorageSettings:
    """本地存储配置。"""

    db_path: str
    project_memory_dir: str
    audit_log_path: str


@dataclass(slots=True)
class Settings:
    """系统总配置对象，后续代码统一从这里取配置。"""

    app: AppSettings
    feishu: FeishuSettings
    llm: LLMSettings
    scheduler: SchedulerSettings
    risk_rules: RiskRuleSettings
    logging: LoggingSettings
    storage: StorageSettings

    def as_dict(self) -> dict[str, Any]:
        """便于调试或日志打印时转换为普通字典。"""

        return asdict(self)


# 环境变量映射表：
# key 是环境变量名；
# value 依次表示：
# - 配置大类，如 app / feishu / llm
# - 具体字段名
# - 类型转换函数，用来把字符串环境变量转成目标类型
ENV_MAPPING: dict[str, tuple[str, str, Any]] = {
    "MEETFLOW_APP_NAME": ("app", "name", str),
    "MEETFLOW_APP_ENV": ("app", "env", str),
    "MEETFLOW_APP_DEBUG": ("app", "debug", lambda value: value.lower() in {"1", "true", "yes", "on"}),
    "MEETFLOW_APP_TIMEZONE": ("app", "timezone", str),
    "MEETFLOW_FEISHU_APP_ID": ("feishu", "app_id", str),
    "MEETFLOW_FEISHU_APP_SECRET": ("feishu", "app_secret", str),
    "MEETFLOW_FEISHU_BASE_URL": ("feishu", "base_url", str),
    "MEETFLOW_FEISHU_REQUEST_TIMEOUT_SECONDS": ("feishu", "request_timeout_seconds", int),
    "MEETFLOW_FEISHU_MAX_RETRIES": ("feishu", "max_retries", int),
    "MEETFLOW_FEISHU_DEFAULT_IDENTITY": ("feishu", "default_identity", str),
    "MEETFLOW_FEISHU_REDIRECT_URI": ("feishu", "redirect_uri", str),
    "MEETFLOW_FEISHU_USER_OAUTH_SCOPE": ("feishu", "user_oauth_scope", str),
    "MEETFLOW_FEISHU_USER_ACCESS_TOKEN": ("feishu", "user_access_token", str),
    "MEETFLOW_FEISHU_USER_ACCESS_TOKEN_EXPIRES_AT": ("feishu", "user_access_token_expires_at", int),
    "MEETFLOW_FEISHU_USER_REFRESH_TOKEN": ("feishu", "user_refresh_token", str),
    "MEETFLOW_FEISHU_USER_REFRESH_TOKEN_EXPIRES_AT": ("feishu", "user_refresh_token_expires_at", int),
    "MEETFLOW_FEISHU_BOT_NAME": ("feishu", "bot_name", str),
    "MEETFLOW_FEISHU_DEFAULT_CHAT_ID": ("feishu", "default_chat_id", str),
    "MEETFLOW_LLM_PROVIDER": ("llm", "provider", str),
    "MEETFLOW_LLM_MODEL": ("llm", "model", str),
    "MEETFLOW_LLM_API_BASE": ("llm", "api_base", str),
    "MEETFLOW_LLM_API_KEY": ("llm", "api_key", str),
    "MEETFLOW_LLM_TEMPERATURE": ("llm", "temperature", float),
    "MEETFLOW_LLM_MAX_TOKENS": ("llm", "max_tokens", int),
    "MEETFLOW_LLM_REASONING_EFFORT": ("llm", "reasoning_effort", str),
    "MEETFLOW_SCHEDULER_PRE_MEETING_MINUTES": ("scheduler", "pre_meeting_minutes_before", int),
    "MEETFLOW_SCHEDULER_RISK_SCAN_CRON": ("scheduler", "risk_scan_cron", str),
    "MEETFLOW_SCHEDULER_MINUTE_RETRY_INTERVAL": ("scheduler", "minute_retry_interval_minutes", int),
    "MEETFLOW_SCHEDULER_MINUTE_RETRY_MAX_ATTEMPTS": ("scheduler", "minute_retry_max_attempts", int),
    "MEETFLOW_RISK_STALE_UPDATE_DAYS": ("risk_rules", "stale_update_days", int),
    "MEETFLOW_RISK_DUE_SOON_HOURS": ("risk_rules", "due_soon_hours", int),
    "MEETFLOW_RISK_MAX_REMINDERS_PER_DAY": ("risk_rules", "max_reminders_per_day", int),
    "MEETFLOW_LOG_LEVEL": ("logging", "level", str),
    "MEETFLOW_LOG_JSON": ("logging", "json_format", lambda value: value.lower() in {"1", "true", "yes", "on"}),
    "MEETFLOW_STORAGE_DB_PATH": ("storage", "db_path", str),
    "MEETFLOW_STORAGE_PROJECT_MEMORY_DIR": ("storage", "project_memory_dir", str),
    "MEETFLOW_STORAGE_AUDIT_LOG_PATH": ("storage", "audit_log_path", str),
}


def _load_json_file(path: Path) -> dict[str, Any]:
    """读取 JSON 配置文件并返回字典。"""

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个配置字典。

    当某个字段本身还是字典时，继续向下合并；
    否则直接用 override 的值覆盖 base。
    """

    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """使用环境变量覆盖配置。

    这一步通常用于：
    - 覆盖敏感信息，如 app_secret / api_key
    - 区分本地、测试、线上环境
    """

    merged = dict(data)
    for env_name, (section, key, caster) in ENV_MAPPING.items():
        raw_value = os.getenv(env_name)
        if raw_value is None or raw_value == "":
            continue
        section_values = dict(merged.get(section, {}))
        section_values[key] = caster(raw_value)
        merged[section] = section_values
    return merged


def _resolve_config_path(config_path: str | Path | None) -> Path:
    """决定本次实际要读取哪个配置文件。

    优先级如下：
    1. 调用 load_settings() 时显式传入的路径
    2. 环境变量 MEETFLOW_CONFIG_PATH
    3. 若存在 settings.local.json，则优先读取它
    4. 否则退回到 settings.example.json
    """

    if config_path is not None:
        return Path(config_path)

    env_path = os.getenv("MEETFLOW_CONFIG_PATH")
    if env_path:
        return Path(env_path)

    return LOCAL_CONFIG_PATH if LOCAL_CONFIG_PATH.exists() else DEFAULT_CONFIG_PATH


def _resolve_storage_paths(data: dict[str, Any]) -> dict[str, Any]:
    """把存储路径统一解析为基于项目根目录的绝对路径。

    这样做的好处是：
    - 无论从项目根目录还是其他目录启动脚本，路径都不会跑偏
    - 审计日志、数据库和项目记忆目录都能稳定落到仓库预期位置
    """

    merged = dict(data)
    storage_values = dict(merged.get("storage", {}))

    for key in ("db_path", "project_memory_dir", "audit_log_path"):
        raw_path = storage_values.get(key)
        if not raw_path:
            continue

        path = Path(raw_path)
        if not path.is_absolute():
            storage_values[key] = str(PROJECT_ROOT / path)

    merged["storage"] = storage_values
    return merged


def load_settings(config_path: str | Path | None = None) -> Settings:
    """加载系统配置，并返回强类型 Settings 对象。

    整体流程分三步：
    1. 先读取默认模板 settings.example.json
    2. 再读取本地配置或指定配置并覆盖默认值
    3. 最后再用环境变量做最高优先级覆盖
    """

    base = _load_json_file(DEFAULT_CONFIG_PATH)
    resolved_path = _resolve_config_path(config_path)

    merged = base
    if resolved_path.exists() and resolved_path != DEFAULT_CONFIG_PATH:
        merged = _deep_merge(base, _load_json_file(resolved_path))

    merged = _apply_env_overrides(merged)
    merged = _resolve_storage_paths(merged)

    return Settings(
        app=AppSettings(**merged["app"]),
        feishu=FeishuSettings(**merged["feishu"]),
        llm=LLMSettings(**merged["llm"]),
        scheduler=SchedulerSettings(**merged["scheduler"]),
        risk_rules=RiskRuleSettings(**merged["risk_rules"]),
        logging=LoggingSettings(**merged["logging"]),
        storage=StorageSettings(**merged["storage"]),
    )
