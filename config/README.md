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
- `settings.local.json`：项目用户自己的本地私有配置，不提交到 Git；真实运行时优先以这里为准
- `llm_providers.example.json`：历史多厂商 LLM 配置参考模板，只放占位符；当前真实脚本不再从这里读取 key

## 单一真实配置入口

MeetFlow 真实运行、真实联调和 Agent Demo 统一读取当前项目的
`config/settings.local.json`。每个开发者只需要维护自己本机项目下的这个 local 文件，
不要再为真实调用额外维护 `config/llm_providers.local.json`。

`settings.local.json` 中 `llm` 字段含义：

- `provider`：模型厂商或兼容适配器，例如 `doubao-ark`、`openai-compatible` 或 `dry-run`
- `api_base`：OpenAI-compatible API base URL
- `api_key`：本地 key，占位符不要提交真实值；真实 key 只能放在 `settings.local.json` 或显式环境变量中
- `model`：默认模型名
- `temperature`：采样温度
- `max_tokens`：最大输出 token 数
- `reasoning_effort`：推理强度，只有部分模型支持

### 豆包 / 火山方舟配置

豆包方舟接口兼容 OpenAI Chat Completions。项目内可以用两种方式接入：

直接改 `config/settings.local.json` 的 `llm` 段，让整个项目默认使用豆包：

```json
"llm": {
  "provider": "doubao-ark",
  "model": "ep-替换为你的推理接入点ID",
  "api_base": "https://ark.cn-beijing.volces.com/api/v3",
  "api_key": "替换为你的火山方舟 API Key",
  "temperature": 0.2,
  "max_tokens": 4000,
  "reasoning_effort": ""
}
```

后续脚本统一传 `--llm-provider settings`；`doubao` 等 provider 名只作为与当前
settings 是否匹配的校验别名，不再读取独立 provider 配置文件：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/pre_meeting_live_test.py \
  --llm-provider settings \
  --event-title "MeetFlow 测试会议"
```

说明：

- `model` 可以填写豆包模型 ID，也可以填写方舟控制台里的 `ep-...` 推理接入点 ID。
- `api_key` 必须填写火山方舟 API Key 本体，不要填写 `ep-...`，也不要把 `Bearer ` 前缀一起写进配置；当前代码会自动去掉误填的 `Bearer ` 前缀，并对 `ep-...` 错填到 `api_key` 给出本地错误提示。
- `api_base` 推荐填写 `https://ark.cn-beijing.volces.com/api/v3`。如果误填成完整 `.../chat/completions`，当前代码也会兼容，不会重复拼接路径。
- `provider` 可写 `doubao-ark`、`doubao`、`volcengine-ark`、`volcengine` 或 `ark`。
- `reasoning_effort` 对豆包不按 OpenAI 语义处理，建议保持空字符串。

## 关键环境变量

本地开发和真实联调优先写 `config/settings.local.json`。以下环境变量仍保留给部署系统或
临时覆盖使用；项目脚本自身不再依赖独立 `llm_providers.local.json`。

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
- `MEETFLOW_FEISHU_EVENT_VERIFICATION_TOKEN`
- `MEETFLOW_FEISHU_EVENT_ENCRYPT_KEY`
- `MEETFLOW_FEISHU_EVENT_SERVER_HOST`
- `MEETFLOW_FEISHU_EVENT_SERVER_PORT`
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
- `MEETFLOW_RERANKER_ENABLED`
- `MEETFLOW_RERANKER_PROVIDER`
- `MEETFLOW_RERANKER_MODEL`
- `MEETFLOW_RERANKER_TOP_K`
- `MEETFLOW_RERANKER_TIMEOUT_SECONDS`
- `MEETFLOW_LOG_LEVEL`
- `MEETFLOW_STORAGE_DB_PATH`
- `MEETFLOW_OBSERVABILITY_STRUCTURED_EVENTS_ENABLED`
- `MEETFLOW_OBSERVABILITY_EVENT_PATH`
- `MEETFLOW_OBSERVABILITY_RECORD_SENSITIVE_PAYLOAD`
- `MEETFLOW_OBSERVABILITY_MAX_EVENT_CHARS`
- `MEETFLOW_OBSERVABILITY_MAX_FIELD_CHARS`
- `MEETFLOW_OBSERVABILITY_MASK_IDS`
- `MEETFLOW_OBSERVABILITY_DAILY_ROTATE`

## 飞书事件回调配置

群聊卡片按钮交互需要在飞书开发者后台配置回调地址，并把对应的
verification token 写入本地配置或环境变量。

建议本地配置：

```json
"feishu": {
  "event_verification_token": "replace-with-event-verification-token",
  "event_encrypt_key": "",
  "event_server_host": "0.0.0.0",
  "event_server_port": 8765
}
```

注意：

- `event_verification_token` 和 `event_encrypt_key` 属于私密配置，只能写入 `settings.local.json` 或环境变量。
- `settings.example.json` 只能保留占位符。
- MVP 暂不处理加密回调；如果飞书后台开启了加密，需要先补充解密逻辑。

## Observability 配置

Agent 结构化运行事件默认写入：

```bash
storage/workflow_events.jsonl
```

这份 JSONL 用于复盘 Agent 运行过程，默认包含工作流生命周期、路由、LLM 调用、
工具调用、Policy 判断和飞书外部 API 调用摘要。默认不会记录完整 prompt、token、
文档正文、模型完整输出或完整密钥。

常用开关：

```bash
export MEETFLOW_OBSERVABILITY_STRUCTURED_EVENTS_ENABLED="true"
export MEETFLOW_OBSERVABILITY_EVENT_PATH="storage/workflow_events.jsonl"
export MEETFLOW_OBSERVABILITY_RECORD_SENSITIVE_PAYLOAD="false"
export MEETFLOW_OBSERVABILITY_MAX_FIELD_CHARS="1000"
export MEETFLOW_OBSERVABILITY_MAX_EVENT_CHARS="16000"
```

本地排障时如需查看更详细 payload，应优先确认不包含密钥和真实用户隐私，再临时开启
`MEETFLOW_OBSERVABILITY_RECORD_SENSITIVE_PAYLOAD=true`。

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

如果模型已经下载到本机缓存，但当前环境不能访问 HuggingFace，可以显式开启离线模式，避免 `sentence-transformers` 启动时发起 HEAD 请求：

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
python3 scripts/knowledge_tools_demo.py
```

注意：离线模式只适合模型已缓存的机器；首次下载模型仍需要联网，或提前把模型缓存准备好。

切换到 OpenAI `text-embedding-3-small` 示例：

```bash
export MEETFLOW_EMBEDDING_PROVIDER="openai-compatible"
export MEETFLOW_EMBEDDING_API_BASE="https://api.openai.com/v1"
export MEETFLOW_EMBEDDING_API_KEY="你的 embedding API Key"
export MEETFLOW_EMBEDDING_MODEL="text-embedding-3-small"
export MEETFLOW_EMBEDDING_DIMENSIONS="1536"
```

索引治理规则：

- MeetFlow 会用 `provider + model + dimensions` 生成 embedding 指纹。
- ChromaDB collection 会按 embedding 指纹隔离，避免不同向量空间混检。
- SQLite 文档和 chunk metadata 会记录 embedding 指纹、知识域 namespace 和 collection 名称。
- 切换 embedding 配置后，需要重新索引相关资源；旧版缺少指纹的索引不会参与当前知识域检索。

## Reranker 配置

M3 知识检索默认关闭 reranker，避免开发阶段额外依赖和接口成本。需要验证重排链路时，可以先启用本地轻量规则 provider：

```bash
export MEETFLOW_RERANKER_ENABLED="true"
export MEETFLOW_RERANKER_PROVIDER="local-rule"
export MEETFLOW_RERANKER_TOP_K="32"
```

当前 `local-rule` 不需要模型和 API key，只根据 query 覆盖率、标题命中、问题命中等轻量信号生成 `rerank_score`。后续接入 bge-reranker、Jina 或 OpenAI-compatible rerank 时，应继续通过本配置段扩展，不要把密钥写入示例配置。

## Knowledge Search 配置

M3 混合检索默认采用 `SQLite FTS5/BM25 + ChromaDB vector + RRF`：

```bash
export MEETFLOW_KNOWLEDGE_FUSION_STRATEGY="rrf"
export MEETFLOW_KNOWLEDGE_RRF_K="60"
```

`rrf` 会按向量召回排名和 BM25 排名做 Reciprocal Rank Fusion，避免直接比较向量相似度和 BM25 原始分数。调试旧逻辑时可以临时设置 `MEETFLOW_KNOWLEDGE_FUSION_STRATEGY="weighted"`，此时仍使用 `vector_weight`、`keyword_weight` 和 freshness 权重。

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
