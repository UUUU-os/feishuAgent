# MeetFlow 开发任务拆解

## 1. 文档目标

本文档用于将 `MeetFlow - 飞书会议知识闭环 Agent` 的 PRD 和架构方案拆解为可执行的开发任务清单，方便团队按阶段推进开发、联调、验证和答辩准备。

本文档强调四件事：

- 先做什么，后做什么
- 每个模块需要完成哪些任务
- 每项任务完成的验收标准是什么
- 哪些任务是 Demo 必做，哪些是增强项

---

## 2. 开发原则

- 优先跑通主链路，不先追求大而全
- 优先实现“会前 - 会后 - 巡检”闭环
- 优先保证结构化输出和证据链
- 优先保证任务可演示、可验收、可回放

---

## 3. 里程碑规划

## M1：项目骨架与基础设施

目标：把项目目录、配置、日志、存储、基础客户端搭起来，形成可持续开发的底座。

## M2：飞书接入与数据读取

目标：能够稳定读取会议、文档、妙记、任务等飞书资源。

## M3：会前知识卡片工作流

目标：在会前自动生成背景知识卡片并推送。

## M4：会后总结与任务落地工作流

目标：在妙记就绪后自动抽取 Action Items，并创建或待确认创建任务。

## M5：风险巡检与提醒工作流

目标：能够定时扫描任务状态并主动提醒风险。

## M6：评估、答辩材料与演示脚本

目标：形成可验证成果，包括指标、样例、演示数据和答辩材料。

---

## 4. 优先级说明

- `P0`：必须完成，缺失会导致 Demo 主链路无法成立
- `P1`：重要增强，影响稳定性、可解释性和答辩效果
- `P2`：可选增强，适合有余力时补充

---

## 5. 任务总览

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
  - `feishu.default_identity`：默认身份模式，支持 `tenant` / `user`
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

## 5.2 M2：飞书接入与数据读取

### T2.1 实现飞书 API 客户端

- 优先级：`P0`
- 目标：提供统一飞书调用入口
- 覆盖能力：
  - 鉴权
  - GET/POST 请求封装
  - 错误处理
  - 限流重试
- 验收标准：
  - 能成功调用至少一个飞书读取接口和一个写入接口

#### T2.1 当前实现细节

- 已创建文件：
  - `adapters/feishu_client.py`
  - `adapters/__init__.py`
  - `scripts/feishu_client_demo.py`
  - `scripts/oauth_device_login.py`
  - `config/settings.example.json` 中已补充飞书客户端超时与重试配置
  - `config/loader.py` 中已补充飞书客户端配置字段与环境变量映射
  - `config/README.md` 中已补充相关环境变量说明
- 已实现的核心类：
  - `FeishuAPIError`：飞书接口通用异常，用于封装 HTTP 或业务错误
  - `FeishuAuthError`：飞书鉴权异常
  - `TokenCache`：访问令牌缓存对象，统一处理 tenant/user token 的有效期判断
  - `FeishuClient`：飞书开放平台客户端，负责鉴权、请求发送、重试、OAuth Device Flow 与错误处理
  - `OAuthTokenBundle`：统一承接用户身份 token 与 refresh token 的刷新结果
  - `DeviceAuthorizationBundle`：统一承接 Device Flow 的 device_code、user_code 与验证链接
- 已实现的核心函数：
  - `get_access_token()`：按身份模式统一获取访问令牌
  - `_build_url()`：把接口路径拼成完整飞书 API URL
  - `_build_headers()`：构建请求头，并按 `tenant` / `user` 自动注入正确的 `Authorization`
  - `get_tenant_access_token()`：调用飞书鉴权接口获取并缓存 `tenant_access_token`
  - `get_user_access_token()`：优先读取本地用户 token，并在需要时自动触发 refresh token 刷新
  - `refresh_user_access_token()`：用 `refresh_token` 刷新用户令牌
  - `request_device_authorization()`：发起 Device Flow，获取 device_code 与验证链接
  - `poll_device_token()`：轮询 token 接口，等待用户扫码或确认完成
  - `get_current_user_info()`：使用用户 token 获取当前登录用户的 open_id 与 name
  - `_parse_oauth_token_bundle()`：把 OAuth token 响应转换为统一结构
  - `_parse_response_payload()`：统一解析 Device Flow 与 user_info 这类原始 HTTP 响应
  - `_apply_user_oauth_bundle()`：把最新 token 结果应用到客户端缓存
  - `get()`：统一封装 GET 请求
  - `post()`：统一封装 POST 请求
  - `_request()`：底层请求入口，统一处理重试、超时、状态码检查和业务 code 检查
- 当前新增配置项：
  - `feishu.request_timeout_seconds`：单次请求超时时间
  - `feishu.max_retries`：网络异常、限流和部分 5xx 状态码下的最大重试次数
  - `feishu.default_identity`：默认请求身份模式
  - `feishu.user_oauth_scope`：默认 OAuth 授权 scope
  - `feishu.user_access_token`：用户身份访问令牌
  - `feishu.user_access_token_expires_at`：用户身份访问令牌过期时间
  - `feishu.user_refresh_token`：用户身份刷新令牌
  - `feishu.user_refresh_token_expires_at`：用户刷新令牌过期时间
  - `feishu.redirect_uri`：预留给未来浏览器授权流程的回调地址
- 运行逻辑说明：
  - 第一步，业务代码通过 `load_settings()` 读取飞书配置，再创建 `FeishuClient(settings.feishu)`
  - 第二步，当需要访问普通飞书接口时，调用 `get()` 或 `post()`，并可显式传入 `identity`
  - 第三步，客户端会先通过 `_build_url()` 拼出完整接口地址
  - 第四步，如果当前请求需要鉴权，客户端会根据 `identity` 决定取哪一种 token：
    - `tenant`：调用 `get_tenant_access_token()`
    - `user`：调用 `get_user_access_token()`
  - 第五步，`user` 身份下如果本地 access token 已过期，但 refresh token 仍有效，则自动调用 `refresh_user_access_token()` 刷新
  - 第六步，请求发送后，客户端会统一检查 HTTP 状态码；如果命中 `429` 或部分 `5xx`，会按重试次数自动重试
  - 第七步，如果接口返回 JSON 中的 `code` 不为 `0`，会抛出 `FeishuAPIError`
  - 第八步，成功时返回解析后的 JSON 字典，供后续文档读取、任务读取、消息发送等能力复用
  - 第九步，如果用户还没有登录过，可以执行 `scripts/oauth_device_login.py`：
    - 客户端先调用 `request_device_authorization()` 申请 `device_code`
    - 脚本打印 `verification_uri_complete`
    - 用户扫码或确认授权后，客户端通过 `poll_device_token()` 自动轮询拿到 token
    - 最后调用 `get_current_user_info()` 校验用户身份，并把 token 写入本地配置
- 当前演示脚本逻辑：
  - `scripts/feishu_client_demo.py` 会先加载配置并初始化日志
  - 然后创建 `FeishuClient`
  - 脚本不会发真实请求，而是展示客户端初始化结果、鉴权接口 URL 和示例业务接口 URL
  - `scripts/oauth_device_login.py` 会发起 Device Flow，打印验证链接，等待用户扫码或授权完成后自动写回用户令牌
- 当前验证结果：
  - 已验证 `FeishuClient` 可以正常初始化
  - 已验证 `_build_url()` 能正确拼接飞书接口地址
  - 已验证 `MEETFLOW_FEISHU_REQUEST_TIMEOUT_SECONDS` 和 `MEETFLOW_FEISHU_MAX_RETRIES` 的环境变量覆盖生效
  - 已验证 `python3 scripts/feishu_client_demo.py` 可直接运行
  - 已验证 `python3 scripts/oauth_device_login.py` 可直接完成用户扫码登录并写回本地 token
- 当前双身份模式说明：
  - 当前已经支持 `tenant` / `user` 两种身份模式
  - 其中 `tenant` 模式可直接走应用身份鉴权
  - `user` 模式的正式登录方案已经确定为纯 Python Device Flow：
    - 申请 `device_code`
    - 打印验证链接
    - 自动轮询 token 接口
    - 获取当前用户信息并写回本地配置
  - Device Flow 轮询逻辑已针对飞书协议做兼容：
    - 当 token 接口返回 `HTTP 400 + authorization_pending` 时，不会当作真正错误退出
    - 当返回 `slow_down` 时，会自动放慢轮询间隔
    - 只有 `access_denied`、`expired_token` 等真正失败状态才会抛出异常

### T2.2 实现会议/日历读取能力

- 优先级：`P0`
- 目标：读取即将开始的会议信息
- 输出：
  - 会议标题
  - 开始时间
  - 参与人
  - 会议描述
- 验收标准：
  - 能拿到一条真实或模拟会议数据

#### T2.2 当前实现细节

- 已创建文件：
  - `scripts/calendar_demo.py`
  - `scripts/calendar_live_test.py`
- 已更新文件：
  - `adapters/feishu_client.py`
  - `core/models.py`
  - `core/__init__.py`
- 已新增的核心类：
  - `CalendarAttendee`：统一描述会议参与人
  - `CalendarEvent`：统一描述会议/日历事件
- 已实现的核心函数：
  - `FeishuClient.get_primary_calendars()`：调用获取主日历接口，拿到真实日历信息列表
  - `FeishuClient.resolve_calendar_id()`：当传入 `primary` 时，先解析出真实 `calendar_id`
  - `FeishuClient.list_calendar_event_instances()`：调用飞书日历 `instance_view` 接口读取指定时间窗口内的日程
  - `FeishuClient.to_calendar_event()`：把飞书原始日程对象转换为统一 `CalendarEvent`
  - `FeishuClient.to_calendar_info()`：把“获取主日历”接口返回的原始对象转换为统一 `CalendarInfo`
  - `FeishuClient._extract_event_time()`：统一提取飞书时间对象中的 `timestamp` 或 `date`
  - `build_lark_cli_calendar_command()`：构造 `lark-cli calendar events instance_view` 调试命令
  - `build_demo_calendar_event()`：使用模拟数据演示日历事件标准化过程
- 运行逻辑说明：
  - 第一步，业务代码创建 `FeishuClient(settings.feishu)`
  - 第二步，当需要拉取会议数据时，调用 `list_calendar_event_instances(calendar_id, start_time, end_time)`
  - 第三步，如果业务层传入的是 `primary`，客户端不会直接拿它查事件，而是先调用 `get_primary_calendars()`
  - 第四步，客户端会从主日历返回结果里解析出真实的 `calendar_id`
  - 第五步，再使用这个真实 `calendar_id` 请求飞书日历接口 `calendar/v4/calendars/{calendar_id}/events/instance_view`
  - 第六步，接口返回的每个原始事件对象，会通过 `to_calendar_event()` 转换为统一的 `CalendarEvent`
  - 第七步，在转换过程中，参与人列表会被进一步转换为 `CalendarAttendee`
  - 第八步，最终业务层拿到的是统一结构的 `CalendarEvent[]`，而不是飞书原始 JSON，便于后续会前卡片直接使用
- 当前 CLI 接入方式：
  - 已确认可用命令为 `lark-cli calendar events instance_view`
  - `scripts/calendar_demo.py` 中已经实现 `build_lark_cli_calendar_command()`，用于生成真实 CLI 调试命令
  - 当前脚本默认使用 `--dry-run`，避免误调用真实飞书接口，同时方便理解请求结构
- 当前演示脚本逻辑：
  - 脚本先用模拟日程数据演示 `CalendarEvent` 的标准化过程
  - 然后构造 `lark-cli calendar events instance_view` 的 dry-run 命令
  - 最后输出 dry-run 结果，验证我们对飞书 CLI 参数的理解是正确的
- 当前真实测试脚本逻辑：
  - `scripts/calendar_live_test.py` 会真实调用 Python 版 `FeishuClient`
  - 脚本默认查询“当前时间起未来 24 小时”的日历事件
  - 如果你传入 `--calendar-id`、`--start-time`、`--end-time`，则按指定区间查询
  - 如果你传入 `--identity user`，则会改用通过 Device Flow 获取并缓存的用户 token 调用同一套飞书日历接口
  - 脚本会先鉴权，再调用飞书日历 `instance_view` 接口，最后把结果格式化打印出来
  - 如果鉴权失败、接口失败或查询为空，脚本会给出明确提示，帮助定位问题
- 当前验证结果：
  - 已验证 `CalendarEvent` 和 `CalendarAttendee` 可正常实例化
  - 已验证 `FeishuClient.to_calendar_event()` 能把原始日历数据转换为统一模型
  - 已验证 `python3 scripts/calendar_demo.py` 可直接运行
  - 已验证 `lark-cli calendar events instance_view --dry-run` 输出的请求路径为：
    - `GET /open-apis/calendar/v4/calendars/primary/events/instance_view?...`
  - 已验证 `python3 scripts/calendar_live_test.py --identity user --calendar-id primary --debug-calendar` 能真实返回用户主日历与会议事件
  - 说明当前 Python 客户端已经可以独立完成用户身份日历读取，不再依赖临时桥接方案

#### T2.1 / T2.2 排障总结

- 之前失败时主要做了这些排查与修正：
  - 发现最初使用的是 `tenant_access_token`，导致看到的是应用视角日历，而不是用户自己的主日历
  - 发现 `calendar_id` 一度被重复放进 URL path 和 query 参数里，导致 `400 Bad Request`
  - 发现不能直接把 `primary` 当作最终日历 ID，必须先调用主日历接口，再解析出真实 `calendar_id`
  - 发现最初尝试的浏览器回调授权链路在本地开发环境中体验较差，拿 `code` 容易卡在回调地址处理上
  - 发现 Device Flow 轮询时，`authorization_pending` 虽然返回 `HTTP 400`，但其实是协议中的正常状态，需要特殊兼容
- 现在成功后最终保留的方案是：
  - `T2.1`：`FeishuClient` 同时支持 `tenant` / `user` 两种身份
  - `user` 登录统一使用 `scripts/oauth_device_login.py` 走 Device Flow
  - 用户 token、refresh token 和过期时间写回本地配置，后续脚本自动复用
  - `T2.2`：`calendar_live_test.py` 统一走 Python HTTP 客户端，不再依赖临时 CLI 桥接
  - 日历查询链路固定为：
    - 获取主日历
    - 解析真实 `calendar_id`
    - 调用 `events/instance_view`
    - 转换为统一的 `CalendarEvent`

### T2.3 实现飞书文档读取能力

- 优先级：`P0`
- 目标：读取文档标题、正文摘要、链接
- 验收标准：
  - 能读取指定文档内容
  - 能转换为内部 `Resource` 结构

### T2.4 实现妙记元数据与内容读取能力

- 优先级：`P0`
- 目标：支持根据妙记 token 拉取元信息与后续正文
- 验收标准：
  - 能获取妙记标题、创建时间、链接
  - 若正文接口可用，能获取内容；否则能为 Demo 留出 mock 能力

### T2.5 实现任务读取能力

- 优先级：`P0`
- 目标：获取任务列表、负责人、截止时间、状态
- 验收标准：
  - 能读取未完成任务
  - 能映射到内部任务模型

### T2.6 实现群消息/卡片发送能力

- 优先级：`P0`
- 目标：能向群或私聊发送文本与卡片
- 验收标准：
  - 能发出一张测试卡片
  - 卡片内容支持动态填充

### T2.7 实现任务创建能力

- 优先级：`P0`
- 目标：支持将结构化 Action Item 写入飞书任务
- 验收标准：
  - 输入一条 `ActionItem` 能成功生成任务
  - 返回的任务 ID 可被记录

---

## 5.3 M3：会前知识卡片工作流

### T3.1 定义 `pre_meeting_brief` 工作流输入输出

- 优先级：`P0`
- 目标：明确会前工作流的输入、输出和中间结构
- 验收标准：
  - 有统一函数签名或接口定义
  - 输出可直接给卡片渲染层使用

### T3.2 实现会议主题识别

- 优先级：`P0`
- 目标：根据会议标题、参与人、上下文识别项目或议题
- 验收标准：
  - 对至少 3 条样例会议能正确归类

### T3.3 实现关联资源召回

- 优先级：`P0`
- 目标：召回最近相关文档、妙记和未完成任务
- 验收标准：
  - 能返回去重后的相关资源列表
  - 至少包含标题、摘要、链接

### T3.4 实现证据排序与摘要生成

- 优先级：`P0`
- 目标：从召回结果中提炼“最小知识集”
- 输出建议：
  - 上次结论
  - 当前问题
  - 待读资料
  - 风险点
- 验收标准：
  - 输出内容简洁
  - 每一条结论都带来源

### T3.5 实现会前卡片模板

- 优先级：`P0`
- 目标：设计一张适合答辩演示的会前卡片
- 验收标准：
  - 卡片字段完整
  - 支持替换不同会议数据

### T3.6 接入会前定时触发

- 优先级：`P0`
- 目标：在会议开始前固定时间自动执行
- 验收标准：
  - 能通过定时或模拟触发运行整个工作流
  - 不重复发送相同卡片

### T3.7 增加手动兜底入口

- 优先级：`P1`
- 目标：支持命令式触发
- 示例：
  - “生成项目 A 今日会前卡片”
- 验收标准：
  - 自动触发失败时仍可演示主能力

---

## 5.4 M4：会后总结与任务落地工作流

### T4.1 定义 `post_meeting_followup` 工作流

- 优先级：`P0`
- 目标：明确会后流程边界
- 验收标准：
  - 输入为妙记或会议信息
  - 输出为结构化总结、Action Items 和回写结果

### T4.2 实现纪要清洗

- 优先级：`P0`
- 目标：对妙记文本做去噪、切片和结构整理
- 验收标准：
  - 对口语化纪要能产出更清晰的输入文本

### T4.3 实现 Action Item 抽取

- 优先级：`P0`
- 目标：抽取事项、负责人、截止时间、优先级、背景依据
- 验收标准：
  - 至少在 3 份样例纪要中抽出结构化任务列表
  - 能识别字段缺失情况

### T4.4 实现决策与待确认问题抽取

- 优先级：`P1`
- 目标：从纪要中提炼结论与开放问题
- 验收标准：
  - 输出的决策与 Action Items 不混淆

### T4.5 实现低置信度标记策略

- 优先级：`P0`
- 目标：对负责人缺失、时间缺失、语义模糊的任务打 `needs_confirm`
- 验收标准：
  - 模糊任务不会直接自动落地为正式任务

### T4.6 实现会后总结卡片

- 优先级：`P0`
- 目标：生成包含结论、待办、风险、原始链接的卡片
- 验收标准：
  - 卡片清晰展示会议产出
  - 支持快速跳转原始资料

### T4.7 实现任务自动创建

- 优先级：`P0`
- 目标：对高置信度任务直接写入飞书任务
- 验收标准：
  - 至少一条样例任务成功创建
  - 本地记录任务映射关系

### T4.8 实现待确认任务卡片

- 优先级：`P1`
- 目标：将低置信度任务展示为待确认，而不是直接写入
- 验收标准：
  - 卡片能展示缺失字段和待确认原因

### T4.9 接入妙记完成触发

- 优先级：`P0`
- 目标：妙记 ready 后自动启动会后流程
- 验收标准：
  - 可通过事件或模拟事件触发
  - 对未 ready 状态支持重试

---

## 5.5 M5：风险巡检与提醒工作流

### T5.1 定义 `risk_scan` 工作流

- 优先级：`P0`
- 目标：明确风险扫描输入、输出和策略
- 验收标准：
  - 能对未完成任务列表运行一次完整扫描

### T5.2 实现任务状态对账

- 优先级：`P0`
- 目标：将历史 Action Items 与实际任务状态做映射
- 验收标准：
  - 能识别哪些 Action Item 已建任务、未建任务、状态异常

### T5.3 实现风险识别规则

- 优先级：`P0`
- 建议规则：
  - 逾期未完成
  - 超过 3 天未更新
  - 无负责人
  - 多次会议重复提及仍未关闭
- 验收标准：
  - 至少能识别两类风险

### T5.4 实现风险提醒卡片

- 优先级：`P0`
- 目标：向负责人或 PM 推送聚合提醒
- 验收标准：
  - 卡片包含任务名、风险原因、截止时间、处理建议

### T5.5 接入每日定时巡检

- 优先级：`P0`
- 目标：通过 scheduler 每日自动扫描
- 验收标准：
  - 可通过真实定时或模拟调度运行

### T5.6 实现提醒降噪机制

- 优先级：`P1`
- 目标：避免同一风险重复轰炸
- 验收标准：
  - 同一任务同一风险在一定窗口内不重复发送

---

## 5.6 M6：评估、答辩材料与演示脚本

### T6.1 构建样例数据集

- 优先级：`P0`
- 目标：准备至少一组完整演示数据
- 建议包含：
  - 一场会议
  - 一份关联文档
  - 一份妙记样本
  - 若干任务状态
- 验收标准：
  - 可在本地完整复现 Demo

### T6.2 构建评估样例

- 优先级：`P1`
- 目标：设计 5-10 条人工标注样本
- 评估点：
  - Action Item 抽取准确率
  - 负责人识别准确率
  - 截止时间识别准确率
- 验收标准：
  - 有一份可复核的评测表

### T6.3 实现指标采集

- 优先级：`P1`
- 目标：采集生成次数、任务数、提醒数、用户修正数等指标
- 验收标准：
  - 每次工作流运行后有埋点记录

### T6.4 编写 Demo 演示脚本

- 优先级：`P0`
- 目标：把演示过程标准化
- 建议脚本：
  1. 会前自动推送卡片
  2. 会后自动生成总结和任务
  3. 风险扫描后主动提醒
- 验收标准：
  - 任何团队成员都能按脚本完成演示

### T6.5 准备答辩材料

- 优先级：`P1`
- 内容建议：
  - 背景痛点
  - 架构图
  - 工作流图
  - 评估指标
  - Demo 截图
- 验收标准：
  - 可以直接进入 PPT 制作阶段

---

## 6. 技术任务拆分

## 6.1 后端基础任务

- `P0` 搭建 Python 项目入口
- `P0` 配置依赖管理
- `P0` 封装日志模块
- `P0` 封装数据库初始化
- `P0` 封装统一错误处理

## 6.2 飞书集成任务

- `P0` 鉴权与 token 获取
- `P0` 文档读取
- `P0` 妙记元数据读取
- `P0` 群消息/卡片发送
- `P0` 任务读取与创建
- `P1` 事件订阅适配

## 6.3 Agent 与工作流任务

- `P0` 工作流路由器
- `P0` 工具注册器
- `P0` 会前工作流
- `P0` 会后工作流
- `P0` 风险巡检工作流
- `P1` 手动问答入口

## 6.4 数据与评估任务

- `P0` 数据模型定义
- `P0` 审计日志落盘
- `P1` 指标采集
- `P1` 评测样例整理
- `P2` 反馈学习机制

---

## 7. 依赖关系

### 主链路依赖

1. `T1.1 - T1.5` 完成后，才能稳定进入业务开发
2. `T2.1 - T2.7` 完成后，才能跑会前和会后工作流
3. `T3.x` 完成后，才有第一段可演示主动链路
4. `T4.x` 完成后，主闭环才成立
5. `T5.x` 完成后，项目才真正体现“主动跟踪价值”

### 可并行任务

- 卡片模板设计可以和飞书客户端封装并行
- 评估数据准备可以和会后工作流开发并行
- 风险规则梳理可以和任务写入模块并行

---

## 8. 建议开发顺序

建议按如下顺序推进：

1. 完成项目骨架、配置、日志、存储
2. 打通飞书读取与卡片发送
3. 实现会前卡片工作流
4. 实现会后总结与任务创建
5. 实现风险巡检与提醒
6. 最后补指标、评估与答辩材料

原因很简单：

- 会前卡片最容易先演示价值
- 会后任务创建最能体现闭环
- 风险巡检是加分项，但依赖前面结果

---

## 9. 首版 Demo 必做清单

以下任务建议定义为首版必须完成：

- `T1.1`
- `T1.2`
- `T1.3`
- `T1.4`
- `T1.5`
- `T2.1`
- `T2.2`
- `T2.3`
- `T2.4`
- `T2.5`
- `T2.6`
- `T2.7`
- `T3.1`
- `T3.2`
- `T3.3`
- `T3.4`
- `T3.5`
- `T3.6`
- `T4.1`
- `T4.2`
- `T4.3`
- `T4.5`
- `T4.6`
- `T4.7`
- `T4.9`
- `T5.1`
- `T5.2`
- `T5.3`
- `T5.4`
- `T5.5`
- `T6.1`
- `T6.4`

---

## 10. 增强项清单

以下任务适合作为增强项：

- `T3.7` 手动兜底入口
- `T4.4` 决策与开放问题抽取
- `T4.8` 待确认任务卡片
- `T5.6` 提醒降噪机制
- `T6.2` 标准评估样例
- `T6.3` 指标采集
- `T6.5` 答辩材料补强

---

## 11. 每周推进建议

如果团队按一周一个阶段推进，可参考：

### 第 1 周

- 完成 M1
- 完成飞书基础接入
- 产出第一张测试卡片

### 第 2 周

- 完成会前卡片工作流
- 完成会后总结与任务抽取

### 第 3 周

- 完成任务写入与风险巡检
- 形成完整 Demo

### 第 4 周

- 补评估数据
- 打磨答辩材料
- 录制演示视频或整理现场脚本

---

## 12. 验收标准总表

项目可以用以下标准判断是否达到“可提交 Demo”状态：

- 能自动读取一场会议的上下文数据
- 能在会前自动生成并发送背景卡片
- 能在会后基于妙记生成结构化总结
- 能把高置信度 Action Item 写入飞书任务
- 能对异常任务进行定时风险提醒
- 所有结论可回链到文档或妙记
- 至少有一套可复现的样例数据和演示脚本

---

## 13. 结论

MeetFlow 的任务拆解应坚持一个原则：

**先做闭环，再做增强；先做可运行 Demo，再做复杂能力。**

因此最合理的推进方式是：

- 先完成底座和飞书接入
- 再跑通会前与会后主链路
- 最后补风险巡检、评估和答辩包装

只要把这三段主动工作流做扎实，项目就已经具备较强的创新性、实用性和可展示性。
