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
- `MEETFLOW_LLM_API_KEY`
- `MEETFLOW_LOG_LEVEL`
- `MEETFLOW_STORAGE_DB_PATH`

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
- 如果要拿到 `refresh_token`，scope 中必须包含 `offline_access`
- `*_expires_at` 建议保存为 Unix 秒级时间戳，便于脚本和客户端自动判断是否过期
- 当前项目在 `T2.1 / T2.2` 的正式实现中，主要使用 **OAuth Device Flow** 获取用户令牌，因此日常登录不依赖 `redirect_uri`
- `redirect_uri` 字段目前保留为后续扩展浏览器授权流程的预留配置，不是当前主链路的必填项
