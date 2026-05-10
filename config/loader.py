from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
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
    event_verification_token: str
    event_encrypt_key: str
    event_server_host: str
    event_server_port: int
    event_receive_mode: str
    event_sdk_log_level: str
    event_http_enabled: bool
    event_http_paths: list[str]


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
class EmbeddingSettings:
    """Embedding 服务配置。"""

    provider: str
    model: str
    api_base: str
    api_key: str
    dimensions: int
    timeout_seconds: int


@dataclass(slots=True)
class RerankerSettings:
    """Reranker 重排配置。"""

    enabled: bool
    provider: str
    model: str
    top_k: int
    timeout_seconds: int


@dataclass(slots=True)
class KnowledgeSearchSettings:
    """知识检索排序配置。

    BM25/RRF 属于本地检索策略，不依赖外部密钥；单独放在配置里，便于
    本地 demo、答辩对比和后续灰度切换。
    """

    fusion_strategy: str
    rrf_k: int


@dataclass(slots=True)
class LiteLLMSettings:
    """LiteLLM Proxy 配置，归属于 AI / RAG / LLM 边界。"""

    enabled: bool = False
    proxy_base_url: str = "http://localhost:4000/v1"
    model_alias: str = "meetflow-default"
    api_key: str = ""
    request_timeout_seconds: int = 60
    health_path: str = "/health"


@dataclass(slots=True)
class RuntimeSettings:
    """运行服务层配置，归属于 Runtime / 高并发边界。"""

    worker_max_concurrency: int = 1
    queue_poll_interval_seconds: float = 2.0
    db_wal_enabled: bool = True
    db_busy_timeout_ms: int = 5000
    console_host: str = "127.0.0.1"
    console_port: int = 8766
    health_check_timeout_seconds: int = 3


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
class JobSettings:
    """后台任务队列配置。

    首期使用 SQLite 任务表承接 callback/daemon 触发的异步工作，配置项控制
    worker 锁租约、重试次数和退避窗口，便于本地单机部署逐步演进。
    """

    enabled: bool
    default_queue: str
    worker_id: str
    lock_seconds: int
    max_attempts: int
    retry_base_seconds: int
    retry_max_seconds: int
    dead_letter_after_attempts: int


@dataclass(slots=True)
class ObservabilitySettings:
    """结构化观测配置。

    这组配置控制 Agent 运行事件是否写入 JSONL、是否记录敏感 payload、
    以及单字段和单事件的最大长度，避免日志变成新的数据泄露面。
    """

    structured_events_enabled: bool
    structured_event_path: str
    record_sensitive_payload: bool
    max_event_chars: int
    max_field_chars: int
    mask_ids: bool
    daily_rotate: bool


@dataclass(slots=True)
class AIConfigView:
    """AI 能力层配置视图。

    仅聚合 LLM、embedding、reranker、knowledge search 和 LiteLLM，
    供新代码按边界取配置，不替代旧的 `settings.llm` 等入口。
    """

    llm: LLMSettings
    embedding: EmbeddingSettings
    reranker: RerankerSettings
    knowledge_search: KnowledgeSearchSettings
    litellm: LiteLLMSettings


@dataclass(slots=True)
class RuntimeConfigView:
    """运行服务层配置视图。

    仅聚合存储、任务队列、观测和 runtime 参数，避免 Runtime 代码直接依赖
    AI/RAG/LLM 配置。
    """

    storage: StorageSettings
    jobs: JobSettings
    observability: ObservabilitySettings
    runtime: RuntimeSettings


@dataclass(slots=True)
class Settings:
    """系统总配置对象，后续代码统一从这里取配置。"""

    app: AppSettings
    feishu: FeishuSettings
    llm: LLMSettings
    embedding: EmbeddingSettings
    reranker: RerankerSettings
    knowledge_search: KnowledgeSearchSettings
    scheduler: SchedulerSettings
    risk_rules: RiskRuleSettings
    logging: LoggingSettings
    storage: StorageSettings
    jobs: JobSettings
    observability: ObservabilitySettings
    litellm: LiteLLMSettings = field(default_factory=LiteLLMSettings)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)

    def as_dict(self) -> dict[str, Any]:
        """便于调试或日志打印时转换为普通字典。"""

        return asdict(self)

    @property
    def ai_config(self) -> AIConfigView:
        """返回 AI 能力层配置视图。"""

        return AIConfigView(
            llm=self.llm,
            embedding=self.embedding,
            reranker=self.reranker,
            knowledge_search=self.knowledge_search,
            litellm=self.litellm,
        )

    @property
    def runtime_config(self) -> RuntimeConfigView:
        """返回运行服务层配置视图。"""

        return RuntimeConfigView(
            storage=self.storage,
            jobs=self.jobs,
            observability=self.observability,
            runtime=self.runtime,
        )


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
    "MEETFLOW_FEISHU_EVENT_VERIFICATION_TOKEN": ("feishu", "event_verification_token", str),
    "MEETFLOW_FEISHU_EVENT_ENCRYPT_KEY": ("feishu", "event_encrypt_key", str),
    "MEETFLOW_FEISHU_EVENT_SERVER_HOST": ("feishu", "event_server_host", str),
    "MEETFLOW_FEISHU_EVENT_SERVER_PORT": ("feishu", "event_server_port", int),
    "MEETFLOW_FEISHU_EVENT_RECEIVE_MODE": ("feishu", "event_receive_mode", str),
    "MEETFLOW_FEISHU_EVENT_SDK_LOG_LEVEL": ("feishu", "event_sdk_log_level", str),
    "MEETFLOW_FEISHU_EVENT_HTTP_ENABLED": (
        "feishu",
        "event_http_enabled",
        lambda value: value.lower() in {"1", "true", "yes", "on"},
    ),
    "MEETFLOW_FEISHU_EVENT_HTTP_PATHS": (
        "feishu",
        "event_http_paths",
        lambda value: [item.strip() for item in value.split(",") if item.strip()],
    ),
    "MEETFLOW_LLM_PROVIDER": ("llm", "provider", str),
    "MEETFLOW_LLM_MODEL": ("llm", "model", str),
    "MEETFLOW_LLM_API_BASE": ("llm", "api_base", str),
    "MEETFLOW_LLM_API_KEY": ("llm", "api_key", str),
    "MEETFLOW_LLM_TEMPERATURE": ("llm", "temperature", float),
    "MEETFLOW_LLM_MAX_TOKENS": ("llm", "max_tokens", int),
    "MEETFLOW_LLM_REASONING_EFFORT": ("llm", "reasoning_effort", str),
    "MEETFLOW_EMBEDDING_PROVIDER": ("embedding", "provider", str),
    "MEETFLOW_EMBEDDING_MODEL": ("embedding", "model", str),
    "MEETFLOW_EMBEDDING_API_BASE": ("embedding", "api_base", str),
    "MEETFLOW_EMBEDDING_API_KEY": ("embedding", "api_key", str),
    "MEETFLOW_EMBEDDING_DIMENSIONS": ("embedding", "dimensions", int),
    "MEETFLOW_EMBEDDING_TIMEOUT_SECONDS": ("embedding", "timeout_seconds", int),
    "MEETFLOW_RERANKER_ENABLED": ("reranker", "enabled", lambda value: value.lower() in {"1", "true", "yes", "on"}),
    "MEETFLOW_RERANKER_PROVIDER": ("reranker", "provider", str),
    "MEETFLOW_RERANKER_MODEL": ("reranker", "model", str),
    "MEETFLOW_RERANKER_TOP_K": ("reranker", "top_k", int),
    "MEETFLOW_RERANKER_TIMEOUT_SECONDS": ("reranker", "timeout_seconds", int),
    "MEETFLOW_KNOWLEDGE_FUSION_STRATEGY": ("knowledge_search", "fusion_strategy", str),
    "MEETFLOW_KNOWLEDGE_RRF_K": ("knowledge_search", "rrf_k", int),
    "MEETFLOW_LITELLM_ENABLED": ("litellm", "enabled", lambda value: value.lower() in {"1", "true", "yes", "on"}),
    "MEETFLOW_LITELLM_PROXY_BASE_URL": ("litellm", "proxy_base_url", str),
    "MEETFLOW_LITELLM_MODEL_ALIAS": ("litellm", "model_alias", str),
    "MEETFLOW_LITELLM_API_KEY": ("litellm", "api_key", str),
    "MEETFLOW_LITELLM_REQUEST_TIMEOUT_SECONDS": ("litellm", "request_timeout_seconds", int),
    "MEETFLOW_LITELLM_HEALTH_PATH": ("litellm", "health_path", str),
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
    "MEETFLOW_JOBS_ENABLED": ("jobs", "enabled", lambda value: value.lower() in {"1", "true", "yes", "on"}),
    "MEETFLOW_JOBS_DEFAULT_QUEUE": ("jobs", "default_queue", str),
    "MEETFLOW_JOBS_WORKER_ID": ("jobs", "worker_id", str),
    "MEETFLOW_JOBS_LOCK_SECONDS": ("jobs", "lock_seconds", int),
    "MEETFLOW_JOBS_MAX_ATTEMPTS": ("jobs", "max_attempts", int),
    "MEETFLOW_JOBS_RETRY_BASE_SECONDS": ("jobs", "retry_base_seconds", int),
    "MEETFLOW_JOBS_RETRY_MAX_SECONDS": ("jobs", "retry_max_seconds", int),
    "MEETFLOW_JOBS_DEAD_LETTER_AFTER_ATTEMPTS": ("jobs", "dead_letter_after_attempts", int),
    "MEETFLOW_OBSERVABILITY_STRUCTURED_EVENTS_ENABLED": (
        "observability",
        "structured_events_enabled",
        lambda value: value.lower() in {"1", "true", "yes", "on"},
    ),
    "MEETFLOW_OBSERVABILITY_EVENT_PATH": ("observability", "structured_event_path", str),
    "MEETFLOW_OBSERVABILITY_RECORD_SENSITIVE_PAYLOAD": (
        "observability",
        "record_sensitive_payload",
        lambda value: value.lower() in {"1", "true", "yes", "on"},
    ),
    "MEETFLOW_OBSERVABILITY_MAX_EVENT_CHARS": ("observability", "max_event_chars", int),
    "MEETFLOW_OBSERVABILITY_MAX_FIELD_CHARS": ("observability", "max_field_chars", int),
    "MEETFLOW_OBSERVABILITY_MASK_IDS": (
        "observability",
        "mask_ids",
        lambda value: value.lower() in {"1", "true", "yes", "on"},
    ),
    "MEETFLOW_OBSERVABILITY_DAILY_ROTATE": (
        "observability",
        "daily_rotate",
        lambda value: value.lower() in {"1", "true", "yes", "on"},
    ),
    "MEETFLOW_RUNTIME_WORKER_MAX_CONCURRENCY": ("runtime", "worker_max_concurrency", int),
    "MEETFLOW_RUNTIME_QUEUE_POLL_INTERVAL_SECONDS": ("runtime", "queue_poll_interval_seconds", float),
    "MEETFLOW_RUNTIME_DB_WAL_ENABLED": ("runtime", "db_wal_enabled", lambda value: value.lower() in {"1", "true", "yes", "on"}),
    "MEETFLOW_RUNTIME_DB_BUSY_TIMEOUT_MS": ("runtime", "db_busy_timeout_ms", int),
    "MEETFLOW_RUNTIME_CONSOLE_HOST": ("runtime", "console_host", str),
    "MEETFLOW_RUNTIME_CONSOLE_PORT": ("runtime", "console_port", int),
    "MEETFLOW_RUNTIME_HEALTH_CHECK_TIMEOUT_SECONDS": ("runtime", "health_check_timeout_seconds", int),
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

    observability_values = dict(merged.get("observability", {}))
    raw_event_path = observability_values.get("structured_event_path")
    if raw_event_path:
        path = Path(raw_event_path)
        if not path.is_absolute():
            observability_values["structured_event_path"] = str(PROJECT_ROOT / path)
    merged["observability"] = observability_values
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
        embedding=EmbeddingSettings(**merged["embedding"]),
        reranker=RerankerSettings(**merged["reranker"]),
        knowledge_search=KnowledgeSearchSettings(**merged["knowledge_search"]),
        scheduler=SchedulerSettings(**merged["scheduler"]),
        risk_rules=RiskRuleSettings(**merged["risk_rules"]),
        logging=LoggingSettings(**merged["logging"]),
        storage=StorageSettings(**merged["storage"]),
        jobs=JobSettings(**merged["jobs"]),
        observability=ObservabilitySettings(**merged["observability"]),
        litellm=LiteLLMSettings(**merged.get("litellm", {})),
        runtime=RuntimeSettings(**merged.get("runtime", {})),
    )
