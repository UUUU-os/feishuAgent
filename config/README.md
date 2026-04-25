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
