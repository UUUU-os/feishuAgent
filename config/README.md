# 配置系统说明

MeetFlow 的配置系统用于统一管理飞书凭证、模型参数、调度规则、风险阈值和日志配置。

## 配置优先级

配置按以下顺序覆盖，后者优先级更高：

1. `config/settings.example.json`
2. `config/settings.local.json`
3. 环境变量

这意味着：

- `settings.example.json` 负责提供默认结构和安全默认值
- `settings.local.json` 负责本地开发配置
- 环境变量负责覆盖敏感信息和部署差异

## 推荐文件

- `settings.example.json`：版本库内的配置模板
- `settings.local.json`：本地私有配置，不提交到 Git
- `llm_providers.example.json`：多厂商 LLM 配置模板，只放占位符
- `llm_providers.local.json`：本地私有 LLM key 配置，不提交到 Git

## 多厂商 LLM Key 模板

如果你需要同时保存 DeepSeek、OpenAI 或其他 OpenAI-compatible 厂商的 key，可以复制模板：

```bash
cp config/llm_providers.example.json config/llm_providers.local.json
```

然后在 `config/llm_providers.local.json` 中填写真实 key，并设置 `active_provider`。这个 local 文件已经加入 `.gitignore`，不要提交。

推荐优先使用环境变量保存 key，例如：

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek Key"
```

模板中每个 provider 的字段含义：

- `provider`：当前统一使用 `openai-compatible` 或 `dry-run`
- `display_name`：给人看的厂商名称
- `api_base`：OpenAI-compatible API base URL
- `api_key`：本地 key，占位符不要提交真实值
- `api_key_env`：推荐读取的环境变量名
- `model`：默认模型名
- `temperature`：采样温度
- `max_tokens`：最大输出 token 数
- `reasoning_effort`：推理强度，只有部分模型支持
- `enabled`：是否启用该配置项

## 关键环境变量

- `MEETFLOW_APP_ENV`
- `MEETFLOW_APP_DEBUG`
- `MEETFLOW_FEISHU_APP_ID`
- `MEETFLOW_FEISHU_APP_SECRET`
- `MEETFLOW_FEISHU_BASE_URL`
- `MEETFLOW_FEISHU_REQUEST_TIMEOUT_SECONDS`
- `MEETFLOW_FEISHU_MAX_RETRIES`
- `MEETFLOW_FEISHU_DEFAULT_IDENTITY`
- `MEETFLOW_FEISHU_REDIRECT_URI`
- `MEETFLOW_FEISHU_USER_OAUTH_SCOPE`
- `MEETFLOW_FEISHU_USER_ACCESS_TOKEN`
- `MEETFLOW_FEISHU_USER_ACCESS_TOKEN_EXPIRES_AT`
- `MEETFLOW_FEISHU_USER_REFRESH_TOKEN`
- `MEETFLOW_FEISHU_USER_REFRESH_TOKEN_EXPIRES_AT`
- `MEETFLOW_LLM_PROVIDER`
- `MEETFLOW_LLM_MODEL`
- `MEETFLOW_LLM_API_BASE`
- `MEETFLOW_LLM_API_KEY`
- `MEETFLOW_LLM_TEMPERATURE`
- `MEETFLOW_LLM_MAX_TOKENS`
- `MEETFLOW_LLM_REASONING_EFFORT`
- `MEETFLOW_EMBEDDING_PROVIDER`
- `MEETFLOW_EMBEDDING_MODEL`
- `MEETFLOW_EMBEDDING_API_BASE`
- `MEETFLOW_EMBEDDING_API_KEY`
- `MEETFLOW_EMBEDDING_DIMENSIONS`
- `MEETFLOW_EMBEDDING_TIMEOUT_SECONDS`
- `MEETFLOW_LOG_LEVEL`
- `MEETFLOW_STORAGE_DB_PATH`

## Embedding 配置

M3 知识检索使用 ChromaDB 作为向量数据库，embedding 支持两种真实模型来源：

- 开发阶段：`sentence-transformers`，使用本地开源模型，不需要商业 API key，但首次运行需要安装依赖并下载模型。
- 测试/生产阶段：`openai-compatible`，调用 OpenAI 或兼容厂商的 `/embeddings` 接口。

开发阶段免费模型示例：

```bash
pip install sentence-transformers
export MEETFLOW_EMBEDDING_PROVIDER="sentence-transformers"
export MEETFLOW_EMBEDDING_MODEL="BAAI/bge-small-zh-v1.5"
export MEETFLOW_EMBEDDING_DIMENSIONS="512"
```

切换到 OpenAI `text-embedding-3-small` 示例：

```bash
export MEETFLOW_EMBEDDING_PROVIDER="openai-compatible"
export MEETFLOW_EMBEDDING_API_BASE="https://api.openai.com/v1"
export MEETFLOW_EMBEDDING_API_KEY="你的 embedding API Key"
export MEETFLOW_EMBEDDING_MODEL="text-embedding-3-small"
export MEETFLOW_EMBEDDING_DIMENSIONS="1536"
```

## 使用方式

后续代码可通过以下方式读取配置：

```python
from config import load_settings

settings = load_settings()
print(settings.feishu.app_id)
print(settings.scheduler.pre_meeting_minutes_before)
```

如果需要读取指定配置文件：

```python
from pathlib import Path
from config import load_settings

settings = load_settings(Path("config/settings.local.json"))
```

## 飞书用户 OAuth 说明

如果你要让 MeetFlow 通过纯 Python 方式调用用户身份 API，至少需要这些字段：

- `feishu.user_oauth_scope`
- `feishu.user_access_token`
- `feishu.user_access_token_expires_at`
- `feishu.user_refresh_token`
- `feishu.user_refresh_token_expires_at`

其中：

- `user_oauth_scope` 建议使用空格分隔的 scope 字符串
- 读取飞书文档需要包含 `docx:document:readonly`
- 读取飞书妙记基础信息需要包含 `minutes:minutes:readonly`
- 读取飞书妙记 AI 产物需要包含 `minutes:minutes.artifacts:read`
- 读取飞书任务列表需要包含 `task:task:read`
- 创建飞书任务需要包含 `task:task:write`
- 使用用户身份发送飞书消息需要包含 `im:message.send_as_user` 和 `im:message`
- 使用机器人身份发送飞书消息需要在后台开通 `im:message:send_as_bot`，并确保机器人已加入目标群
- 如果要拿到 `refresh_token`，scope 中必须包含 `offline_access`
- `*_expires_at` 建议保存为 Unix 秒级时间戳，便于脚本和客户端自动判断是否过期
- 当前项目在 `T2.1 / T2.2` 的正式实现中，主要使用 **OAuth Device Flow** 获取用户令牌，因此日常登录不依赖 `redirect_uri`
- `redirect_uri` 字段目前保留为后续扩展浏览器授权流程的预留配置，不是当前主链路的必填项
