## 5.1 M1：项目骨架与基础设施

### T1.1 建立项目目录结构

- 优先级：`P0`
- 目标：建立统一目录结构，便于后续开发与协作
- 建议输出：
  - `config/`
  - `adapters/`
  - `workflows/`
  - `tools/`
  - `storage/`
  - `cards/`
  - `scripts/`
  - `tests/`
- 验收标准：
  - 目录结构清晰
  - README 或说明文档可解释每个目录职责

### T1.2 配置系统设计

- 优先级：`P0`
- 目标：统一管理飞书凭证、模型配置、调度参数、阈值规则
- 建议内容：
  - `app_id`
  - `app_secret`
  - API base URL
  - 调度时间配置
  - 风险规则配置
  - 日志级别
- 验收标准：
  - 支持本地配置读取
  - 敏感信息可通过环境变量覆盖

#### T1.2 当前实现细节

- 已创建文件：
  - `config/settings.example.json`
  - `config/loader.py`
  - `config/__init__.py`
  - `config/README.md`
  - `.gitignore`
- 已实现的核心类：
  - `AppSettings`：应用基础配置，如运行环境、时区、debug 开关
  - `FeishuSettings`：飞书开放平台配置，如 `app_id`、`app_secret`、`base_url`
  - `LLMSettings`：模型服务配置，如模型名、API Key、温度参数
  - `SchedulerSettings`：调度器配置，如会前提前多少分钟触发、妙记重试参数
  - `RiskRuleSettings`：风险识别规则，如多久未更新算风险、多久内临近截止
  - `LoggingSettings`：日志级别与输出格式配置
  - `StorageSettings`：数据库、项目记忆目录、审计日志路径配置
  - `Settings`：总配置对象，统一聚合上述子配置
- 已实现的核心函数：
  - `_load_json_file()`：读取 JSON 配置文件
  - `_deep_merge()`：递归合并默认配置与本地覆盖配置
  - `_apply_env_overrides()`：用环境变量覆盖配置字段
  - `_resolve_config_path()`：决定本次加载哪个配置文件
  - `_resolve_storage_paths()`：把存储路径统一转为基于项目根目录的绝对路径
  - `load_settings()`：主入口，负责按顺序加载并返回 `Settings`
- 当前已补充的飞书用户身份配置：
  - `feishu.default_identity`：默认身份模式，支持 `tenant` / `user`，当前项目主链路默认使用 `user`
  - `feishu.redirect_uri`：预留给后续浏览器授权流程的回调地址配置
  - `feishu.user_oauth_scope`：默认 OAuth scope，使用空格分隔
  - `feishu.user_access_token`：手动注入的用户访问令牌
  - `feishu.user_access_token_expires_at`：用户访问令牌过期时间
  - `feishu.user_refresh_token`：后续刷新用户令牌时使用
  - `feishu.user_refresh_token_expires_at`：用户刷新令牌过期时间
- 运行逻辑说明：
  - 第一步，先读取 `config/settings.example.json`，作为系统默认配置模板
  - 第二步，如果存在 `config/settings.local.json` 或调用时显式传入配置路径，就用它覆盖默认值
  - 第三步，再检查环境变量，如 `MEETFLOW_FEISHU_APP_ID`、`MEETFLOW_LOG_LEVEL`，并用环境变量做最高优先级覆盖
  - 第四步，把存储相关路径解析为绝对路径，避免从不同工作目录启动脚本时写错位置
  - 第五步，把最终结果转换为 `Settings` 及其子配置对象，后续代码统一通过对象属性取值，而不是手写字典 key
- 这一步对后续飞书身份的意义：
  - 当前配置系统已经不再只面向应用身份
  - 后续既可以继续使用 `tenant_access_token`
  - 也可以通过 `user_access_token` 支持用户身份 API 调用
- 当前验证方式：
  - 已通过 `python3 -c "from config import load_settings; ..."` 验证默认配置可正常读取
  - 已通过设置 `MEETFLOW_LOG_LEVEL=DEBUG`、`MEETFLOW_FEISHU_APP_ID=cli_test` 验证环境变量覆盖生效

### T1.3 日志与审计基础能力

- 优先级：`P0`
- 目标：所有工作流执行过程可追踪
- 建议实现：
  - 统一 `trace_id`
  - 工作流开始/结束日志
  - 工具调用日志
  - 错误日志
- 验收标准：
  - 每次工作流运行都能看到完整 trace
  - 错误可定位到模块级别

#### T1.3 当前实现细节

- 已创建文件：
  - `core/logging.py`
  - `core/audit.py`
  - `core/__init__.py`
  - `scripts/logging_demo.py`
  - `storage/workflow_runs.jsonl`
- 已实现的核心类：
  - `TraceIdFilter`：给每条日志自动注入 `trace_id`
  - `AuditLogger`：把结构化审计记录写入 JSONL 文件
  - `WorkflowRunRecorder`：负责记录工作流开始、成功结束、失败结束三类事件
- 已实现的核心函数：
  - `generate_trace_id()`：生成一次工作流的唯一追踪编号
  - `bind_trace_id()`：把 `trace_id` 绑定到当前执行上下文
  - `get_trace_id()`：读取当前上下文中的 `trace_id`
  - `reset_trace_id()`：在工作流结束后清空上下文，避免串号
  - `configure_logging()`：初始化全局日志系统和输出格式
  - `get_logger()`：获取模块级 logger
  - `log_workflow_event()`：统一记录 `started`、`finished`、`failed` 等关键阶段日志
- 运行逻辑说明：
  - 第一步，业务代码先调用 `configure_logging(settings.logging)` 初始化日志系统
  - 第二步，某个工作流开始执行时，通过 `WorkflowRunRecorder.start()` 生成并绑定新的 `trace_id`
  - 第三步，工作流中的普通日志通过 `logger.info(...)` 输出，因为 logger 上挂了 `TraceIdFilter`，所以每条日志都会自动带上同一个 `trace_id`
  - 第四步，`WorkflowRunRecorder.start()` 会把工作流开始事件写入 `storage/workflow_runs.jsonl`
  - 第五步，如果工作流成功结束，就调用 `WorkflowRunRecorder.success()`，写入结束日志和结果摘要
  - 第六步，如果工作流异常失败，就调用 `WorkflowRunRecorder.failure()`，记录错误类型、错误信息和上下文
  - 第七步，工作流结束后调用 `reset_trace_id()`，避免下一个流程继承上一个流程的追踪编号
- 当前演示脚本逻辑：
  - `scripts/logging_demo.py` 会先加载配置，再初始化日志
  - 然后创建一个 `WorkflowRunRecorder`，模拟一次名为 `demo_workflow` 的工作流
  - 脚本会依次输出开始日志、过程日志、结束日志
  - 同时会把结构化审计记录写入 `storage/workflow_runs.jsonl`
- 当前验证结果：
  - 已验证控制台日志中包含统一 `trace_id`
  - 已验证工作流开始和结束事件成功写入 `storage/workflow_runs.jsonl`
  - 已验证脚本可直接通过 `python3 scripts/logging_demo.py` 运行

### T1.4 本地存储设计

- 优先级：`P0`
- 目标：实现最小可用的状态与结果存储
- 建议实现：
  - `SQLite` 存工作流执行记录、幂等键、任务映射
  - `JSON/JSONL` 存项目记忆与历史摘要
- 验收标准：
  - 能保存和读取工作流结果
  - 能记录某次任务是否已经执行过

#### T1.4 当前实现细节

- 已创建文件：
  - `core/storage.py`
  - `scripts/storage_demo.py`
  - `storage/meetflow.sqlite`
  - `storage/action_items.jsonl`
  - `storage/projects/meetflow.json`
- 已实现的核心类：
  - `MeetFlowStorage`：本地存储统一入口，封装 SQLite、JSON、JSONL 三类存储操作
- 已实现的核心函数：
  - `initialize()`：初始化本地目录和 SQLite 表结构
  - `save_workflow_result()`：保存一条工作流结果到 SQLite
  - `get_workflow_result()`：按 `trace_id` 读取工作流结果
  - `record_idempotency_key()`：记录某个幂等键已经执行过
  - `is_idempotency_key_processed()`：判断幂等键是否已存在
  - `save_task_mapping()`：保存行动项与飞书任务的映射关系
  - `get_task_mapping()`：读取行动项与任务的映射关系
  - `save_project_memory()`：将项目长期记忆写入 JSON 文件
  - `load_project_memory()`：读取项目长期记忆 JSON
  - `append_action_item_snapshot()`：把行动项快照追加写入 JSONL
- 当前 SQLite 表设计：
  - `workflow_results`：存工作流结果，字段包含 `trace_id`、`workflow_name`、`status`、`summary`、`payload_json`
  - `idempotency_keys`：存幂等键，避免重复触发同一流程
  - `task_mappings`：存行动项与飞书任务之间的映射，方便后续同步和风险扫描
- 运行逻辑说明：
  - 第一步，业务代码创建 `MeetFlowStorage(settings.storage)`，把配置中的数据库路径和目录路径传进去
  - 第二步，调用 `initialize()`，创建 `storage/` 相关目录，并初始化 SQLite 表
  - 第三步，当工作流执行完成时，通过 `save_workflow_result()` 把结果写入 `workflow_results`
  - 第四步，当系统需要防止重复执行时，通过 `record_idempotency_key()` 和 `is_idempotency_key_processed()` 实现幂等控制
  - 第五步，当行动项被写入飞书任务后，通过 `save_task_mapping()` 保存本地映射关系
  - 第六步，当需要保存长期项目知识时，通过 `save_project_memory()` 写入 `storage/projects/{project_id}.json`
  - 第七步，当需要保留原始行动项样本时，通过 `append_action_item_snapshot()` 追加写入 `storage/action_items.jsonl`
- 当前演示脚本逻辑：
  - `scripts/storage_demo.py` 会先初始化存储层
  - 然后模拟保存项目记忆、工作流结果、幂等键、任务映射、行动项快照
  - 最后再把这些内容读取出来，验证整个存储闭环是否成立
- 当前验证结果：
  - 已验证 `storage/meetflow.sqlite` 成功创建
  - 已验证 `storage/projects/meetflow.json` 成功写入并可读取
  - 已验证 `storage/action_items.jsonl` 成功追加写入
  - 已验证工作流结果、幂等键、任务映射的查询都能返回正确结果

### T1.5 公共数据模型定义

- 优先级：`P0`
- 目标：统一 `Event`、`Resource`、`MeetingSummary`、`ActionItem`、`RiskAlert`
- 验收标准：
  - 各工作流共享同一套结构
  - 结构足以支撑回写和审计

#### T1.5 当前实现细节

- 已创建文件：
  - `core/models.py`
  - `core/__init__.py` 中已补充模型导出
- 已实现的核心类：
  - `BaseModel`：所有公共模型的基础类，统一提供 `to_dict()`
  - `Event`：统一事件模型，描述消息触发、会议触发、任务触发等输入
  - `Resource`：统一资源模型，抽象文档、妙记、任务、消息等对象
  - `EvidenceRef`：证据引用模型，给结论和行动项挂载来源信息
  - `ActionItem`：会后抽取出的结构化行动项
  - `MeetingSummary`：会议结构化总结
  - `RiskAlert`：风险提醒对象
  - `WorkflowResult`：工作流执行完成后的统一结果模型
- 模型之间的关系说明：
  - `MeetingSummary` 内部包含 `action_items`
  - `ActionItem` 内部可以包含多个 `evidence_refs`
  - `MeetingSummary` 自身也可以挂多个 `evidence_refs`
  - `WorkflowResult` 用于把这些业务对象作为最终产物统一落盘
- 运行逻辑说明：
  - 第一步，系统收到外部输入时，用 `Event` 表示触发源
  - 第二步，从飞书读取到的文档、妙记、任务等对象统一转换成 `Resource`
  - 第三步，知识处理层输出结构化行动项时使用 `ActionItem`
  - 第四步，会后总结阶段使用 `MeetingSummary` 聚合决策、问题、行动项和风险
  - 第五步，风险巡检阶段使用 `RiskAlert` 表示一条可推送的风险结果
  - 第六步，任何工作流执行结束后，都可以把最终结果封装为 `WorkflowResult` 再交给存储层保存
- 当前演示脚本中的使用方式：
  - `scripts/storage_demo.py` 已实际构造 `Event`、`ActionItem`、`MeetingSummary`、`RiskAlert`、`WorkflowResult`
  - 然后通过 `to_dict()` 转换为普通字典后交给存储层保存
- 当前验证结果：
  - 已验证这些模型可以被正常实例化
  - 已验证模型可通过 `to_dict()` 序列化
  - 已验证这些模型已被存储脚本实际使用，而不是只停留在定义层

---

