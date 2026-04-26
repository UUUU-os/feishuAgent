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

## M2.8：业务侧垂直 Agent Runtime

目标：在进入具体会前、会后、巡检工作流前，先构建一个真正的业务侧垂直 Agent，统一负责事件理解、工作流路由、工具编排、状态管理、幂等控制和失败降级。

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
  - 如果你没有显式传入 `--identity`，脚本会自动使用 `feishu.default_identity`
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
- 状态：已完成
- 本次创建 / 修改的文件：
  - `adapters/feishu_client.py`
  - `scripts/docs_live_test.py`
  - `config/settings.example.json`
  - `config/settings.local.json`
  - `config/README.md`
  - `tasks.md`
- 代码结构说明：
  - `FeishuClient.extract_document_token()`：从飞书文档 URL 或裸 token 中解析 `document_id`，支持 `/docx/`、`/doc/`、`/wiki/` 三类链接
  - `FeishuClient.fetch_document()`：调用飞书 `docs_ai` 文档读取接口，保留原始响应，便于排查接口返回
  - `FeishuClient.fetch_document_resource()`：面向业务层的主入口，读取文档后直接转换成内部 `Resource`
  - `FeishuClient.to_document_resource()`：把飞书返回的 `document.content`、`revision_id` 等字段映射为统一资源模型
  - `FeishuClient._build_document_fetch_payload()`：统一构造 `docs_ai/v1/documents/{document_id}/fetch` 请求体
  - `FeishuClient._build_document_read_option()`：支持 `full`、`outline`、`range`、`keyword`、`section` 等读取范围
  - `FeishuClient._build_text_excerpt()`：把 XML/Markdown 正文压缩成适合日志和卡片展示的短摘要
  - `scripts/docs_live_test.py`：提供真实联调入口，可测试文档读取、局部读取、正文预览和完整 `Resource` JSON 输出
- 运行业务逻辑：
  - 第一步，用户传入文档 URL 或 token，例如 `--doc https://xxx.feishu.cn/docx/xxxxx`
  - 第二步，脚本读取 `config/settings.local.json`，默认使用 `feishu.default_identity`；当前默认是 `user`
  - 第三步，`FeishuClient` 自动获取或刷新 `user_access_token`
  - 第四步，客户端把 URL 解析为 `document_id`
  - 第五步，调用 `POST /open-apis/docs_ai/v1/documents/{document_id}/fetch`
  - 第六步，飞书返回 `document.content` 后，客户端转换为 `Resource(resource_type="feishu_document")`
  - 第七步，脚本打印标题、正文摘要、正文预览和可选的完整资源 JSON
- 权限与配置说明：
  - 文档读取需要用户授权 scope：`docx:document:readonly`
  - 已在 `settings.example.json` 和 `settings.local.json` 的 `user_oauth_scope` 中补充该权限
  - 因为 OAuth token 的权限来自授权时的 scope，所以修改配置后需要重新执行 `python3 scripts/oauth_device_login.py`
- 验证方式：
  - 已通过 `python3 -m py_compile adapters/feishu_client.py scripts/docs_live_test.py`
  - 已通过 `python3 scripts/docs_live_test.py --help`
  - 真实读取命令示例：
    - `python3 scripts/oauth_device_login.py`
    - `python3 scripts/docs_live_test.py --doc "你的飞书文档链接" --scope full`
    - `python3 scripts/docs_live_test.py --doc "你的飞书文档链接" --scope outline --max-depth 3`

### T2.4 实现妙记元数据与内容读取能力

- 优先级：`P0`
- 目标：支持根据妙记 token 拉取元信息与后续正文
- 验收标准：
  - 能获取妙记标题、创建时间、链接
  - 若正文接口可用，能获取内容；否则能为 Demo 留出 mock 能力
- 状态：已完成
- 本次创建 / 修改的文件：
  - `adapters/feishu_client.py`
  - `scripts/minutes_live_test.py`
  - `config/settings.example.json`
  - `config/settings.local.json`
  - `config/README.md`
  - `tasks.md`
- 代码结构说明：
  - `FeishuClient.extract_minute_token()`：从妙记 URL 或裸 token 中解析 `minute_token`
  - `FeishuClient.get_minute()`：调用 `GET /open-apis/minutes/v1/minutes/{minute_token}` 读取妙记基础信息
  - `FeishuClient.get_minute_artifacts()`：调用 `GET /open-apis/minutes/v1/minutes/{minute_token}/artifacts` 尝试读取 AI 总结、待办和章节
  - `FeishuClient.fetch_minute_resource()`：业务层主入口，先读取元数据，再尽力读取 AI 产物，最后转换为统一 `Resource`
  - `FeishuClient.to_minute_resource()`：把妙记标题、链接、创建时间、时长、所有者和 AI 产物映射到内部资源模型
  - `FeishuClient._build_minute_content()`：将元数据、summary、todos、chapters 拼成可被召回和摘要模块消费的 Markdown 文本
  - `FeishuClient._format_minute_artifact_item()`：兼容不同形态的待办 / 章节条目，优先提取 `content`、`text`、`title` 等字段
  - `scripts/minutes_live_test.py`：提供真实联调入口，可测试妙记读取、元数据退化模式和完整 `Resource` JSON 输出
- 运行业务逻辑：
  - 第一步，用户传入妙记 URL 或 token，例如 `--minute https://xxx.feishu.cn/minutes/obcn...`
  - 第二步，脚本读取配置，默认使用 `feishu.default_identity`，当前默认是 `user`
  - 第三步，`FeishuClient` 自动获取或刷新 `user_access_token`
  - 第四步，客户端解析出 `minute_token`
  - 第五步，调用 `minutes.get` 获取标题、创建时间、时长、所有者、链接等基础信息
  - 第六步，默认继续调用 `artifacts` 接口读取 AI 总结、待办和章节
  - 第七步，如果 AI 产物读取失败，不中断主流程，而是在 `source_meta.artifacts_error` 中记录原因，并返回仅包含元数据的 `Resource`
  - 第八步，脚本打印资源摘要、正文预览和可选完整 JSON
- 权限与配置说明：
  - 妙记基础信息需要用户授权 scope：`minutes:minutes:readonly`
  - 妙记 AI 产物需要用户授权 scope：`minutes:minutes.artifacts:read`
  - 已在 `settings.example.json` 和 `settings.local.json` 的 `user_oauth_scope` 中补充以上权限
  - 修改 scope 后需要重新执行 `python3 scripts/oauth_device_login.py`，让本地用户 token 带上新增权限
- 验证方式：
  - 已通过 `python3 -m py_compile adapters/feishu_client.py scripts/minutes_live_test.py scripts/docs_live_test.py`
  - 已通过 `python3 scripts/minutes_live_test.py --help`
  - 已通过本地 token 解析测试，能从 `/minutes/<token>` 链接中提取 `minute_token`
  - 真实读取命令示例：
    - `python3 scripts/oauth_device_login.py`
    - `python3 scripts/minutes_live_test.py --minute "你的飞书妙记链接"`
    - `python3 scripts/minutes_live_test.py --minute "你的飞书妙记链接" --metadata-only`

### T2.5 实现任务读取能力

- 优先级：`P0`
- 目标：获取任务列表、负责人、截止时间、状态
- 验收标准：
  - 能读取未完成任务
  - 能映射到内部任务模型
- 状态：已完成
- 本次创建 / 修改的文件：
  - `adapters/feishu_client.py`
  - `scripts/tasks_live_test.py`
  - `config/settings.example.json`
  - `config/settings.local.json`
  - `config/README.md`
  - `tasks.md`
- 代码结构说明：
  - `FeishuClient.list_my_task_items()`：调用 `GET /open-apis/task/v2/tasks`，使用 `type=my_tasks` 读取当前用户负责的任务原始 JSON
  - `FeishuClient.list_my_tasks()`：在原始任务列表基础上做模型转换，返回 `list[ActionItem]`
  - `FeishuClient.to_action_item()`：把飞书任务中的 `guid`、`summary`、`members`、`due.timestamp`、`status` 等字段映射到内部 `ActionItem`
  - `FeishuClient._extract_task_owner()`：从任务成员里提取负责人，优先取 `role=assignee`，兼容部分任务返回 `editor` 的情况
  - `scripts/tasks_live_test.py`：提供真实联调入口，可读取未完成 / 已完成 / 全部任务，并支持本地标题关键词过滤
- 运行业务逻辑：
  - 第一步，脚本读取配置，默认使用 `feishu.default_identity`
  - 第二步，任务接口强依赖用户资源，所以请求身份应为 `user`
  - 第三步，客户端自动获取或刷新 `user_access_token`
  - 第四步，调用 `GET /open-apis/task/v2/tasks`，参数包含 `type=my_tasks`、`completed`、`page_size`、`page_token`
  - 第五步，若返回 `has_more=true`，客户端继续用 `page_token` 翻页，直到达到 `page_limit` 或没有更多数据
  - 第六步，每条飞书任务转换为 `ActionItem`
  - 第七步，脚本打印任务 ID、标题、负责人、截止时间、状态、链接和可选原始 JSON
- 字段映射说明：
  - `ActionItem.item_id`：优先使用飞书任务 `guid`，没有时退回 `task_id`
  - `ActionItem.title`：来自飞书任务 `summary`
  - `ActionItem.owner`：来自 `members` 中的负责人名称或 ID
  - `ActionItem.due_date`：来自 `due.timestamp`，单位为毫秒
  - `ActionItem.status`：来自飞书任务 `status`，通常为 `todo` 或 `done`
  - `ActionItem.extra`：保留任务链接、描述、创建时间、更新时间、成员、清单和原始 payload，方便后续追踪表、风险扫描和回链
- 权限与配置说明：
  - 读取飞书任务需要用户授权 scope：`task:task:read`
  - 已在 `settings.example.json` 和 `settings.local.json` 的 `user_oauth_scope` 中补充该权限
  - 修改 scope 后需要重新执行 `python3 scripts/oauth_device_login.py`，让本地用户 token 带上新增权限
- 验证方式：
  - 已通过 `python3 -m py_compile adapters/feishu_client.py scripts/tasks_live_test.py scripts/minutes_live_test.py scripts/docs_live_test.py`
  - 已通过 `python3 scripts/tasks_live_test.py --help`
  - 已通过本地样例映射测试，能把飞书任务 JSON 转换为 `ActionItem`
  - 真实读取命令示例：
    - `python3 scripts/oauth_device_login.py`
    - `python3 scripts/tasks_live_test.py`
    - `python3 scripts/tasks_live_test.py --completed all`
    - `python3 scripts/tasks_live_test.py --query "任务关键词"`

### T2.6 实现群消息/卡片发送能力

- 优先级：`P0`
- 目标：能向群或私聊发送文本与卡片
- 验收标准：
  - 能发出一张测试卡片
  - 卡片内容支持动态填充
- 状态：已完成
- 本次创建 / 修改的文件：
  - `adapters/feishu_client.py`
  - `scripts/message_live_test.py`
  - `config/settings.example.json`
  - `config/settings.local.json`
  - `config/README.md`
  - `tasks.md`
- 代码结构说明：
  - `FeishuClient.send_message()`：封装 `POST /open-apis/im/v1/messages`，统一处理 `receive_id_type`、`msg_type`、`content` 和幂等键
  - `FeishuClient.send_text_message()`：发送纯文本消息，内部自动构造 `{"text": "..."}`
  - `FeishuClient.send_card_message()`：发送交互卡片消息，`msg_type=interactive`
  - `FeishuClient.build_meetflow_card()`：构造 MeetFlow 通知卡片模板，支持标题、摘要、要点和按钮跳转
  - `scripts/message_live_test.py`：提供真实联调入口，支持群聊 / 私聊、文本 / 卡片、dry-run 预览和显式发送
- 运行业务逻辑：
  - 第一步，用户通过 `--chat-id` 指定群聊，或通过 `--user-id` 指定私聊对象
  - 第二步，如果没有传 `--chat-id`，脚本会尝试读取配置中的 `feishu.default_chat_id`
  - 第三步，脚本根据 `--message-type` 构造文本 payload 或卡片 payload
  - 第四步，默认只打印 dry-run payload，不会真实发送
  - 第五步，只有显式传入 `--send` 时，才调用飞书消息接口发出消息
  - 第六步，发送成功后打印飞书返回的 `message_id`、`chat_id`、`create_time` 等结果
- 安全设计说明：
  - 因为消息发送会影响真实群聊和用户，脚本默认是 dry-run
  - 真实发送必须显式加 `--send`
  - 支持 `--idempotency-key`，避免调试时重复发送同一条消息
- 字段与接口说明：
  - 群聊发送使用 `receive_id_type=chat_id`
  - 私聊发送使用 `receive_id_type=open_id`
  - `receive_id_type` 必须作为 URL query 参数传递，不能只放在 body 或 dry-run 预览里
  - 文本消息使用 `msg_type=text`
  - 卡片消息使用 `msg_type=interactive`
  - 飞书要求 `content` 是 JSON 字符串，因此客户端会对 Python 字典做 `json.dumps`
- 本次排障记录：
  - 真实发送卡片时曾返回 `99992402 field validation failed`
  - 原因是 dry-run payload 中展示了 `receive_id_type`，但真实 `send_message()` 请求没有把它传给飞书接口
  - 已修复为 `POST /open-apis/im/v1/messages?receive_id_type=chat_id`
- 权限与配置说明：
  - 用户身份发送消息需要用户授权 scope：`im:message.send_as_user` 和 `im:message`
  - 机器人身份发送消息需要后台开通 `im:message:send_as_bot`，并确保机器人已经加入目标群
  - 已在 `settings.example.json` 和 `settings.local.json` 的 `user_oauth_scope` 中补充用户身份发送权限
  - 修改 scope 后需要重新执行 `python3 scripts/oauth_device_login.py`，让本地用户 token 带上新增权限
- 验证方式：
  - 已通过 `python3 -m py_compile adapters/feishu_client.py scripts/message_live_test.py scripts/tasks_live_test.py`
  - 已通过 `python3 scripts/message_live_test.py --help`
  - 已通过卡片 dry-run 测试，能够生成 `interactive` 消息 payload
  - 真实发送命令示例：
    - `python3 scripts/oauth_device_login.py`
    - `python3 scripts/message_live_test.py --chat-id "oc_xxx" --message-type text --text "MeetFlow 测试消息"`
    - `python3 scripts/message_live_test.py --chat-id "oc_xxx" --message-type card --text "会前背景卡已生成" --fact "会议：项目周会" --send`

### T2.7 实现任务创建能力

- 优先级：`P0`
- 目标：支持将结构化 Action Item 写入飞书任务
- 验收标准：
  - 输入一条 `ActionItem` 能成功生成任务
  - 返回的任务 ID 可被记录
- 状态：已完成
- 本次创建 / 修改的文件：
  - `adapters/feishu_client.py`
  - `scripts/task_create_live_test.py`
  - `config/settings.example.json`
  - `config/settings.local.json`
  - `config/README.md`
  - `tasks.md`
- 代码结构说明：
  - `FeishuClient.build_create_task_payload()`：构造 `POST /open-apis/task/v2/tasks` 的请求体，支持标题、描述、负责人、截止时间、任务清单和幂等键
  - `FeishuClient.create_task()`：调用飞书任务创建接口，并把返回的 `task` 转换为内部 `ActionItem`
  - `FeishuClient.create_task_from_action_item()`：以内部 `ActionItem` 为输入创建飞书任务，服务于后续“会议 Action Item 自动落任务”
  - `scripts/task_create_live_test.py`：提供真实联调入口，支持 dry-run、显式创建、负责人、截止时间和幂等键
- 运行业务逻辑：
  - 第一步，脚本把命令行输入转换为内部 `ActionItem`
  - 第二步，`ActionItem.title` 映射为飞书任务 `summary`
  - 第三步，`ActionItem.extra.description` 映射为飞书任务 `description`
  - 第四步，`ActionItem.due_date` 映射为飞书任务 `due.timestamp`
  - 第五步，`--assignee-open-id` 映射为 `members[].id`，角色固定为 `assignee`
  - 第六步，默认只打印 dry-run payload，不创建真实任务
  - 第七步，只有显式传入 `--create` 时，才调用飞书创建任务接口
  - 第八步，创建成功后把飞书返回的任务转换为 `ActionItem`，并打印任务 ID、标题、负责人、截止时间、状态和链接
- 安全设计说明：
  - 创建任务属于写操作，脚本默认 dry-run
  - 真实创建必须显式加 `--create`
  - 支持 `--idempotency-key`，避免调试时重复创建同一条任务
- 字段与接口说明：
  - 创建接口：`POST /open-apis/task/v2/tasks`
  - 查询参数：`user_id_type=open_id`
  - `summary` 为必填
  - `description` 最大 3000 字符，当前作为任务描述
  - `due.timestamp` 使用毫秒时间戳
  - `--due` 支持毫秒时间戳、`YYYY-MM-DD`、ISO 时间和 `+Nd` 相对天数
  - `client_token` 用于飞书侧幂等创建
- 权限与配置说明：
  - 创建飞书任务需要用户授权 scope：`task:task:write`
  - 已在 `settings.example.json` 和 `settings.local.json` 的 `user_oauth_scope` 中补充该权限
  - 修改 scope 后需要重新执行 `python3 scripts/oauth_device_login.py`，让本地用户 token 带上新增权限
- 验证方式：
  - 已通过 `python3 -m py_compile adapters/feishu_client.py scripts/task_create_live_test.py scripts/tasks_live_test.py`
  - 已通过 `python3 scripts/task_create_live_test.py --help`
  - 已通过 dry-run 创建任务 payload 测试
  - 已通过本地 payload 映射测试，能把 `ActionItem` 字段转换为飞书创建任务 JSON
  - 真实创建命令示例：
    - `python3 scripts/oauth_device_login.py`
    - `python3 scripts/task_create_live_test.py --summary "整理会议纪要" --description "根据今天的项目周会补齐行动项"`
    - `python3 scripts/task_create_live_test.py --summary "整理会议纪要" --due +2d --idempotency-key meetflow-task-001 --create`

---

## 5.2.8 M2.8：业务侧垂直 Agent Runtime

### M2.8 设计目标

M2 已经打通了飞书工具能力，但这些能力目前仍然主要以客户端方法和测试脚本存在。为了让项目成为一个业务侧垂直 Agent，而不是一组工作流脚本，需要在 M3 之前补上 Agent Runtime。

这个 Runtime 的职责是：

- 统一接收事件、定时触发和人工命令
- 识别当前业务意图和触发场景
- 构建会议 / 项目 / 妙记 / 任务上下文
- 路由到正确的业务工作流
- 封装 LLM Agent Loop，让 LLM 在受控工具集内决定下一步调用哪些工具
- 通过 Tool Registry 执行飞书工具和知识处理工具
- 管理幂等键、执行状态、失败降级和审计日志
- 控制自动化边界，例如低置信度任务不直接创建

设计上参考 nanobot 的 `ContextBuilder + LLMProvider + AgentRunner + ToolRegistry` 模式，但 MeetFlow 不做通用 Agent，而是收敛成会议知识闭环垂直 Agent。

### T2.8 定义 Agent Runtime 数据模型

- 优先级：`P0`
- 目标：定义 Agent 输入、决策、上下文、运行结果、工具调用轮次等核心数据结构
- 建议新增模型：
  - `AgentInput`：承接 event / schedule / command 三类触发
  - `AgentDecision`：描述路由到哪个工作流、为什么、需要哪些工具
  - `WorkflowContext`：承接会议、项目、参与人、资源、记忆和 trace_id
  - `AgentMessage`：记录一次 LLM loop 中的 system / user / assistant / tool 消息
  - `AgentToolCall`：记录 LLM 想调用的工具名、参数和调用 id
  - `AgentToolResult`：记录工具执行状态、结构化结果、错误和证据来源
  - `AgentLoopState`：记录当前 loop 轮数、消息列表、工具结果和停止原因
  - `AgentRunResult`：记录 Agent 执行状态、产物、副作用和下一步动作
- 验收标准：
  - M3-M5 工作流可以统一接收 `WorkflowContext`
  - 每次 Agent 执行都有统一 `trace_id`
  - 每次 LLM 工具调用都能被审计和回放
  - 结果可以保存到现有 `WorkflowResult`

#### T2.8 当前实现细节

- 已更新文件：
  - `core/models.py`
  - `core/__init__.py`
- 已创建文件：
  - `scripts/agent_models_demo.py`
- 已实现的核心类：
  - `AgentInput`：Agent 统一输入模型，承接飞书事件、定时触发和人工命令
  - `AgentDecision`：路由决策模型，记录目标工作流、置信度、原因、允许工具和幂等键
  - `WorkflowContext`：工作流上下文模型，聚合会议、日历事件、妙记、任务、项目记忆和相关资源
  - `AgentToolCall`：LLM 请求调用工具时的统一内部结构，后续由 `LLMProvider` 生成
  - `AgentToolResult`：工具执行结果模型，保留给 LLM 看的内容、结构化数据、错误信息和证据引用
  - `AgentMessage`：Agent Loop 消息模型，统一表示 system / user / assistant / tool 消息
  - `AgentLoopState`：LLM 多轮工具调用状态，记录轮数、消息列表、待执行工具、工具结果和停止原因
  - `AgentRunResult`：Agent 一次完整运行结果，记录最终回答、产物、副作用、下一步动作和 loop 状态
- 已实现的辅助方法：
  - `AgentToolResult.is_success()`：判断工具调用是否成功，便于后续 Agent Loop 做分支处理
  - `AgentLoopState.append_message()`：追加一条 loop 消息，避免调用方直接操作内部列表
  - `AgentLoopState.append_tool_result()`：追加工具结果，并自动生成对应的 `tool` 消息
  - `AgentRunResult.to_workflow_result()`：把 Agent 运行结果转换成现有 `WorkflowResult`，复用当前存储层
- 运行逻辑说明：
  - 第一步，外部触发源先被封装为 `AgentInput`
  - 第二步，后续 `WorkflowRouter` 会把 `AgentInput` 转换为 `AgentDecision`
  - 第三步，`WorkflowContextBuilder` 会基于事件和飞书资源构建 `WorkflowContext`
  - 第四步，`MeetFlowAgentLoop` 会用 `AgentMessage`、`AgentToolCall`、`AgentToolResult` 记录 LLM 多轮工具调用过程
  - 第五步，整次运行结束后封装为 `AgentRunResult`
  - 第六步，需要落盘时，`AgentRunResult.to_workflow_result()` 会转换成当前存储层已经支持的 `WorkflowResult`
- 当前演示脚本逻辑：
  - `scripts/agent_models_demo.py` 构造一条 `meeting.soon` 输入
  - 模拟路由到 `pre_meeting_brief`
  - 构造一个相关飞书文档 `Resource`
  - 模拟一次 `LLM -> docs.fetch_resource -> tool result` 的 loop 状态
  - 最后打印完整 `AgentRunResult` 和转换后的 `WorkflowResult`
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/models.py core/__init__.py scripts/agent_models_demo.py` 验证语法正确
  - 已通过 `python3 scripts/agent_models_demo.py` 验证模型可实例化、可递归序列化、可转换为 `WorkflowResult`
- 这一步对后续任务的意义：
  - T2.9 可以直接基于 `AgentToolCall` 和 `AgentMessage` 封装 LLM Provider
  - T2.10 可以直接基于 `AgentToolCall` 和 `AgentToolResult` 实现 Tool Registry
  - T2.13 可以直接基于 `AgentLoopState` 实现真正的 LLM Agent Loop

### T2.9 封装 LLM Provider 与 Tool Calling 协议

- 优先级：`P0`
- 目标：把模型调用从业务工作流中独立出来，为 Agent Loop 提供统一的 LLM 接口
- 建议实现：
  - `LLMProvider`：统一封装模型调用、温度、最大 token、超时和重试
  - `LLMResponse`：统一解析模型文本、结构化输出、tool_calls 和 finish_reason
  - `ToolCallRequest`：把不同模型返回的工具调用格式转成内部统一格式
  - `GenerationSettings`：从配置读取模型名、temperature、max_tokens、reasoning_effort 等参数
- 运行逻辑：
  - 第一步，`MeetFlowAgentLoop` 把当前消息列表和工具 schema 交给 `LLMProvider`
  - 第二步，`LLMProvider` 调用具体模型服务
  - 第三步，如果模型返回 `tool_calls`，转换成内部 `AgentToolCall`
  - 第四步，如果模型返回最终内容，转换成 Agent 的结构化结果草稿
- 验收标准：
  - 可以在不接飞书工具的情况下完成一次纯 LLM 调用
  - 可以解析模型返回的工具调用请求
  - 模型调用失败时返回可解释错误，不让工作流静默失败

#### T2.9 当前实现细节

- 已创建文件：
  - `core/llm.py`
  - `scripts/llm_provider_demo.py`
  - `scripts/deepseek_llm_live_test.py`
- 已更新文件：
  - `core/__init__.py`
  - `config/loader.py`
  - `config/settings.example.json`
  - `config/README.md`
- 已实现的核心类：
  - `GenerationSettings`：单次模型生成参数，包含模型名、temperature、max_tokens、reasoning_effort 和超时时间
  - `ToolDefinition`：提供给 LLM 的工具定义，可校验工具名并转换为 OpenAI-compatible tool schema
  - `LLMResponse`：模型响应统一结构，包含文本内容、工具调用、finish_reason、usage 和原始响应
  - `LLMProvider`：模型 Provider 抽象基类，后续 Agent Loop 只依赖这个统一接口
  - `OpenAICompatibleProvider`：基于 `/chat/completions` 协议的真实模型调用实现
  - `DryRunLLMProvider`：不访问网络的本地 provider，用于无 API Key 时验证 Agent 数据流
  - `LLMConfigError`：配置缺失或 provider 不支持时抛出的错误
  - `LLMAPIError`：HTTP、网络、JSON 解析等模型调用异常的统一错误
- 已实现的核心函数：
  - `create_llm_provider()`：根据配置创建 `OpenAICompatibleProvider` 或 `DryRunLLMProvider`
  - `settings_from_config()`：把 `LLMSettings` 转换成单次 `GenerationSettings`
  - `ToolDefinition.validate_name()`：提前校验工具名是否符合 OpenAI-compatible / DeepSeek 函数命名规则
  - `_agent_message_to_openai()`：把内部 `AgentMessage` 转成 OpenAI-compatible message
  - `_agent_tool_call_to_openai()`：把内部 `AgentToolCall` 转成 OpenAI-compatible tool call
  - `_parse_openai_response()`：解析 OpenAI-compatible 响应并生成 `LLMResponse`
  - `_parse_openai_tool_call()`：解析模型返回的单个 tool call，并转换为 `AgentToolCall`
- 配置变化：
  - `LLMSettings` 新增 `reasoning_effort`
  - `settings.example.json` 新增 `llm.reasoning_effort`
  - 环境变量新增 `MEETFLOW_LLM_REASONING_EFFORT`
  - `config/README.md` 补充了 LLM 相关环境变量
- 运行逻辑说明：
  - 第一步，业务代码调用 `create_llm_provider(settings.llm)` 创建 provider
  - 第二步，`MeetFlowAgentLoop` 后续会把 `AgentMessage[]` 和 `ToolDefinition[]` 传给 `provider.chat()`
  - 第三步，`OpenAICompatibleProvider` 会将内部消息和工具定义转换为 OpenAI-compatible 请求体
  - 第四步，模型返回后，provider 将响应统一转换为 `LLMResponse`
  - 第五步，如果 `LLMResponse.should_execute_tools` 为 true，后续 T2.10 / T2.13 会进入工具执行阶段
  - 第六步，如果没有工具调用，Agent Loop 可以直接把 `content` 当作最终文本或结构化结果草稿
- 当前演示脚本逻辑：
  - `scripts/llm_provider_demo.py --provider dry-run --mode tool` 会模拟模型请求调用 `docs.fetch_resource`
  - `scripts/llm_provider_demo.py --provider dry-run --mode text` 会模拟模型直接返回文本
  - `--provider configured` 会使用配置中的真实模型服务，但需要先配置 `MEETFLOW_LLM_API_BASE` 和 `MEETFLOW_LLM_API_KEY`
  - `scripts/deepseek_llm_live_test.py` 会真实调用 DeepSeek API，默认读取 `DEEPSEEK_API_KEY`
- 当前验证方式：
  - 已通过 `python3 -m py_compile config/loader.py core/llm.py core/__init__.py scripts/llm_provider_demo.py` 验证语法正确
  - 已通过 `python3 scripts/llm_provider_demo.py --provider dry-run --mode tool` 验证工具调用响应结构
  - 已通过 `python3 scripts/llm_provider_demo.py --provider dry-run --mode text --prompt 测试普通回复` 验证普通文本响应结构
  - 已通过本地 OpenAI-compatible 样例响应验证 `_parse_openai_response()` 能正确解析 tool call
  - 已根据 DeepSeek 真实报错修复工具名兼容性：LLM 暴露工具名必须使用 `calendar_list_events` 这类格式，不能使用 `calendar.list_events`
- 这一步对后续任务的意义：
  - T2.10 的 Tool Registry 可以直接使用 `ToolDefinition` 暴露工具 schema
  - T2.10 需要负责维护内部工具名和 LLM 工具名之间的映射，例如内部 `calendar.list_events` 映射到 LLM 可见的 `calendar_list_events`
  - T2.13 的 MeetFlowAgentLoop 可以直接调用 `LLMProvider.chat()` 完成每轮 LLM 推理
  - 真实模型和 dry-run 模型使用同一个接口，后续本地测试和线上调用不会分叉

### T2.10 实现 Tool Registry

- 优先级：`P0`
- 目标：把 M2 已完成的飞书能力注册成 Agent 可调用工具，而不是让工作流直接散落调用 `FeishuClient`
- 首批工具建议：
  - `calendar.list_events`
  - `docs.fetch_resource`
  - `minutes.fetch_resource`
  - `tasks.list_my_tasks`
  - `tasks.create_task`
  - `im.send_text`
  - `im.send_card`
- 验收标准：
  - 可以通过工具名调用具体方法
  - 可以向 LLM 暴露工具名称、描述和 JSON Schema 参数
  - 工具有统一入参、出参和错误包装
  - 工具调用可记录日志和 trace_id

#### T2.10 当前实现细节

- 已创建文件：
  - `core/tools.py`
  - `adapters/feishu_tools.py`
  - `scripts/tool_registry_demo.py`
- 已更新文件：
  - `core/__init__.py`
  - `adapters/__init__.py`
- 已实现的核心类：
  - `AgentTool`：单个 Agent 工具定义，包含内部工具名、LLM 工具名、描述、参数 schema、处理函数、是否只读和副作用类型
  - `ToolRegistry`：工具注册器，负责注册工具、查询工具、生成 LLM tool definitions、执行 `AgentToolCall`
  - `ToolRegistryError`：工具注册器通用异常
  - `ToolNotFoundError`：LLM 请求未注册工具时的异常
  - `ToolParameterError`：工具参数缺失或不合法时的异常
- 已实现的核心函数：
  - `make_llm_tool_name()`：把内部工具名转换成 DeepSeek / OpenAI-compatible 兼容工具名，例如 `calendar.list_events` -> `calendar_list_events`
  - `validate_llm_tool_name()`：校验 LLM 工具名是否只包含字母、数字、下划线和连字符
  - `serialize_tool_result()`：把工具返回的 `BaseModel`、列表、字典等转换成可 JSON 序列化的数据
  - `build_tool_result_content()`：生成喂回 LLM 的简短工具结果摘要
  - `create_feishu_tool_registry()`：创建首批飞书工具注册器
- 当前已注册的飞书工具：
  - `calendar.list_events` -> LLM 可见名 `calendar_list_events`
  - `docs.fetch_resource` -> LLM 可见名 `docs_fetch_resource`
  - `minutes.fetch_resource` -> LLM 可见名 `minutes_fetch_resource`
  - `tasks.list_my_tasks` -> LLM 可见名 `tasks_list_my_tasks`
  - `tasks.create_task` -> LLM 可见名 `tasks_create_task`
  - `im.send_text` -> LLM 可见名 `im_send_text`
  - `im.send_card` -> LLM 可见名 `im_send_card`
- 运行逻辑说明：
  - 第一步，业务启动时调用 `create_feishu_tool_registry(client, default_chat_id)`
  - 第二步，注册器把飞书客户端方法包装成 `AgentTool`
  - 第三步，`ToolRegistry.get_definitions()` 生成可传给 `LLMProvider.chat()` 的 `ToolDefinition[]`
  - 第四步，LLM 返回 `AgentToolCall` 后，`ToolRegistry.execute()` 根据 `tool_name` 找到对应工具
  - 第五步，工具先做 required 参数校验，再调用真实 handler
  - 第六步，工具结果统一包装为 `AgentToolResult`，成功时包含结构化 `data`，失败时包含 `error_message`
- 当前演示脚本逻辑：
  - `scripts/tool_registry_demo.py --mode list-feishu` 会列出所有飞书工具和暴露给 LLM 的 tool definitions，不调用飞书 API
  - `scripts/tool_registry_demo.py --mode execute-demo` 会执行本地 `demo_echo` 工具，验证 `AgentToolCall -> AgentToolResult` 链路
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/tools.py core/__init__.py adapters/feishu_tools.py adapters/__init__.py scripts/tool_registry_demo.py` 验证语法正确
  - 已通过 `python3 scripts/tool_registry_demo.py --mode execute-demo --message 测试工具注册器` 验证本地工具执行成功
  - 已通过 `python3 scripts/tool_registry_demo.py --mode list-feishu` 验证首批飞书工具 schema 可正常生成，且 LLM 工具名不含点号
- 这一步对后续任务的意义：
  - T2.11 的 `WorkflowRouter` 可以在 `AgentDecision.required_tools` 中使用内部工具名，例如 `calendar.list_events`
  - T2.13 的 `MeetFlowAgentLoop` 可以把 `ToolRegistry.get_definitions(required_tools)` 交给 LLM，再把 LLM 返回的 `AgentToolCall` 交给 `ToolRegistry.execute()`
  - T2.15 的 `AgentPolicy` 可以根据 `AgentTool.read_only` 和 `side_effect` 决定写操作是否需要确认

### T2.11 实现 Workflow Router

- 优先级：`P0`
- 目标：根据事件类型或人工命令选择业务工作流
- 路由规则：
  - `meeting.soon` -> `pre_meeting_brief`
  - `minute.ready` -> `post_meeting_followup`
  - `risk.scan.tick` -> `risk_scan`
  - `message.command` -> `manual_command`
- 验收标准：
  - 输入 `AgentInput` 能稳定输出 `AgentDecision`
  - 未知事件能返回明确的 `unsupported` 决策
  - 决策结果包含原因和幂等键
  - 决策结果包含本次业务场景允许暴露给 LLM 的工具名单

#### T2.11 当前实现细节

- 已创建文件：
  - `core/router.py`
  - `scripts/workflow_router_demo.py`
- 已更新文件：
  - `core/__init__.py`
- 已实现的核心类：
  - `RouteRule`：单条路由规则，描述事件类型、目标工作流、原因、允许工具、置信度和状态
  - `WorkflowRouter`：工作流路由器，把 `AgentInput` 转换成 `AgentDecision`
  - `WorkflowRouterError`：路由器通用异常，预留给后续复杂路由校验使用
- 已实现的核心函数：
  - `build_default_route_rules()`：构建首版默认路由规则
  - `build_idempotency_key()`：根据 workflow_type、事件 ID、会议 ID、妙记 token、任务 ID 或 payload hash 生成稳定幂等键
  - `build_agent_input()`：构造 `AgentInput`，方便脚本和后续测试复用
- 当前默认路由规则：
  - `meeting.soon` -> `pre_meeting_brief`
  - `minute.ready` -> `post_meeting_followup`
  - `risk.scan.tick` -> `risk_scan`
  - `message.command` -> `manual_qa`，也可以通过 payload 指定 `workflow_type`
- 当前工具集约束：
  - `pre_meeting_brief` 默认允许 `calendar.list_events`、`docs.fetch_resource`、`minutes.fetch_resource`、`tasks.list_my_tasks`、`im.send_card`
  - `post_meeting_followup` 默认允许 `minutes.fetch_resource`、`docs.fetch_resource`、`tasks.create_task`、`im.send_card`
  - `risk_scan` 默认允许 `tasks.list_my_tasks`、`calendar.list_events`、`im.send_card`
  - `manual_qa` 默认允许 `calendar.list_events`、`docs.fetch_resource`、`minutes.fetch_resource`、`tasks.list_my_tasks`
- 运行逻辑说明：
  - 第一步，触发源先构造 `AgentInput`
  - 第二步，`WorkflowRouter.route()` 根据 `event_type` 查找 `RouteRule`
  - 第三步，如果是 `message.command`，允许 payload 覆盖目标 `workflow_type`
  - 第四步，路由器解析本次允许暴露给 LLM 的内部工具名列表
  - 第五步，路由器生成稳定 `idempotency_key`
  - 第六步，输出 `AgentDecision`
  - 第七步，如果事件未知，不抛异常，而是返回 `workflow_type=unsupported`、`status=unsupported`
- 当前演示脚本逻辑：
  - `scripts/workflow_router_demo.py --event-type meeting.soon --meeting-id meeting_001` 模拟会前路由
  - `scripts/workflow_router_demo.py --event-type minute.ready --minute-token minute_001` 模拟会后路由
  - `scripts/workflow_router_demo.py --event-type risk.scan.tick --trigger-type schedule` 模拟定时风险巡检
  - `scripts/workflow_router_demo.py --event-type message.command --workflow-type risk_scan` 模拟人工命令指定工作流
  - `scripts/workflow_router_demo.py --event-type unknown.event` 模拟未知事件降级
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/router.py core/__init__.py scripts/workflow_router_demo.py` 验证语法正确
  - 已验证 `meeting.soon` 能路由到 `pre_meeting_brief` 并生成会前工具集
  - 已验证 `minute.ready` 能路由到 `post_meeting_followup` 并生成会后工具集
  - 已验证 `risk.scan.tick` 能路由到 `risk_scan` 并生成风险巡检工具集
  - 已验证 `message.command` 可以指定 `workflow_type=risk_scan`
  - 已验证未知事件会返回 `unsupported` 决策而不是中断程序
- 这一步对后续任务的意义：
  - T2.12 可以基于 `AgentDecision.workflow_type` 构建对应 `WorkflowContext`
  - T2.13 可以把 `AgentDecision.required_tools` 传给 `ToolRegistry.get_definitions()`，从而限制 LLM 可见工具范围
  - T2.15 可以基于 `AgentDecision.status` 和 `workflow_type` 决定是否允许继续执行写操作

### T2.12 实现 Workflow Context Builder

- 优先级：`P0`
- 目标：根据事件构建工作流上下文，避免每个工作流重复解析 payload
- 核心能力：
  - 从会议事件中解析 `meeting_id`、`calendar_event_id`、参与人和时间窗口
  - 从妙记事件中解析 `minute_token`
  - 从任务事件中解析 `task_id`
  - 从配置或项目记忆中解析 `project_id`
  - 聚合可用的飞书资源和本地记忆快照
- 验收标准：
  - M3-M5 只依赖 `WorkflowContext`，不直接依赖原始事件 payload
  - 上下文中保留原始事件，便于调试和回放
  - 上下文可以被转换成 LLM runtime context，不需要模型理解原始飞书响应体

#### T2.12 当前实现细节

- 已创建文件：
  - `core/context.py`
  - `scripts/workflow_context_demo.py`
- 已更新文件：
  - `core/__init__.py`
  - `core/router.py`
- 已实现的核心类：
  - `WorkflowContextBuilder`：工作流上下文构建器，把 `AgentInput + AgentDecision` 转换成统一 `WorkflowContext`
  - `WorkflowContextError`：上下文构建异常，预留给后续严格校验使用
- 已实现的核心函数：
  - `build_event_from_agent_input()`：把 `AgentInput` 转换成统一 `Event`
  - `extract_meeting_id()`：从 payload 中解析会议 ID
  - `extract_calendar_event_id()`：从 payload 中解析日历事件 ID
  - `extract_minute_token()`：从 payload 中解析妙记 token
  - `extract_task_id()`：从 payload 中解析任务 ID
  - `extract_project_id()`：从 payload 中解析项目 ID，没有则使用默认项目
  - `extract_participants()`：从 payload 中解析参与人列表
  - `extract_related_resources()`：从 payload 中解析已有资源线索并转换为 `Resource`
  - `resource_from_payload()`：把资源字典转换成统一 `Resource`
  - `first_string()`：按多个候选字段读取第一个非空字符串
- 当前上下文构建边界：
  - `WorkflowContextBuilder` 只解析已有 payload 和本地项目记忆
  - 不主动调用飞书 API
  - 不主动做文档、妙记或任务召回
  - 真正的资源读取留给后续 `ToolRegistry + MeetFlowAgentLoop`
- 运行逻辑说明：
  - 第一步，外部触发源构造 `AgentInput`
  - 第二步，`WorkflowRouter` 输出 `AgentDecision`
  - 第三步，`WorkflowContextBuilder.build()` 读取 payload 中的会议、日历事件、妙记、任务和项目字段
  - 第四步，构造标准 `Event`，保存在 `WorkflowContext.event`
  - 第五步，解析参与人和已有资源线索
  - 第六步，如果配置了 `MeetFlowStorage`，则读取 `storage/projects/{project_id}.json` 作为 `memory_snapshot`
  - 第七步，把 `agent_input`、`decision` 和原始 payload 放入 `raw_context`，方便调试和回放
- 当前演示脚本逻辑：
  - `scripts/workflow_context_demo.py --event-type meeting.soon --meeting-id meeting_001 --calendar-event-id event_001 --with-memory` 模拟会前上下文，并写入/读取项目记忆
  - `scripts/workflow_context_demo.py --event-type minute.ready --minute-token minute_001 --project-id meetflow` 模拟会后上下文
  - `scripts/workflow_context_demo.py --event-type risk.scan.tick --task-id task_001 --project-id meetflow` 模拟风险巡检上下文
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/router.py core/context.py core/__init__.py scripts/workflow_context_demo.py` 验证语法正确
  - 已验证会前场景可解析 `meeting_id`、`calendar_event_id`、参与人、相关资源和项目记忆
  - 已验证会后场景可解析 `minute_token`，并生成 `post_meeting_followup:minute_001` 幂等键
  - 已验证风险场景可解析 `task_id`，并生成 `risk_scan:task_001` 幂等键
- 这一步对后续任务的意义：
  - T2.13 可以直接把 `WorkflowContext` 转成 LLM runtime context
  - M3-M5 工作流不需要再解析原始 payload，只依赖 `WorkflowContext`
  - 后续事件订阅接入时，只需要把飞书事件 payload 填进 `AgentInput.payload`

### T2.13 实现 MeetFlowAgentLoop 主循环

- 优先级：`P0`
- 目标：实现真正的 Agent Loop，让 LLM 基于上下文选择工具、读取工具结果并产出最终结构化结果
- 主流程：
  - 接收 `WorkflowContext`、允许工具集和工作流目标
  - 组装 system prompt、runtime context 和历史消息
  - 调用 `LLMProvider`
  - 如果模型返回工具调用，则通过 `ToolRegistry` 执行工具
  - 将 `AgentToolResult` 追加为 tool 消息
  - 继续下一轮 LLM 调用
  - 模型输出最终结果、达到最大轮数或触发策略拦截时结束
- 验收标准：
  - 能完成至少一次“LLM -> 工具 -> LLM -> 最终结果”的循环
  - 支持最大轮数限制，避免无限循环
  - 每轮模型调用和工具调用都能落审计日志
  - 工具执行失败时，LLM 可以收到错误摘要并尝试降级

#### T2.13 当前实现细节

- 已创建文件：
  - `core/agent_loop.py`
  - `scripts/agent_loop_demo.py`
- 已更新文件：
  - `core/__init__.py`
  - `core/llm.py`
- 已实现的核心类：
  - `MeetFlowAgentLoop`：MeetFlow 垂直 Agent 的主循环，负责把上下文交给 LLM、执行模型选择的工具、再把工具结果反馈给 LLM
  - `AgentLoopError`：Agent Loop 预留异常类型，方便后续扩展策略拦截、工具异常升级等场景
- 已实现的核心函数：
  - `MeetFlowAgentLoop.run()`：执行完整 loop，直到模型给出最终答案、达到最大轮数或发生异常
  - `MeetFlowAgentLoop._build_initial_state()`：构造 `AgentLoopState`，并追加 system / user 初始消息
  - `MeetFlowAgentLoop._handle_tool_calls()`：执行 LLM 返回的工具调用，并把 `AgentToolResult` 追加为 tool 消息
  - `MeetFlowAgentLoop._build_run_result()`：把 loop 状态转换为统一 `AgentRunResult`
  - `build_system_prompt()`：生成垂直 Agent 系统提示词，约束它必须基于工具和上下文回答
  - `build_runtime_context_message()`：把 `WorkflowContext` 压缩成 LLM 可读的 JSON 上下文
  - `collect_side_effects()`：收集本次 loop 中已经执行过的写操作工具，便于后续审计和策略检查
  - `build_result_summary()`：生成 `AgentRunResult.summary`
- 已更新的 LLM dry-run 行为：
  - `DryRunLLMProvider.chat()` 如果还没有工具结果，会模拟模型请求第一个工具
  - 如果消息里已经出现 tool 结果，会模拟模型产出最终回答
  - 这样可以在没有真实模型 API Key 的情况下验证完整 “LLM -> 工具 -> LLM” 链路
- 当前 Agent Loop 运行逻辑：
  - 第一步，外部传入 `WorkflowContext`、本次允许工具列表和工作流目标
  - 第二步，`MeetFlowAgentLoop` 创建 `AgentLoopState`，写入 `trace_id`、`workflow_type`、最大轮数和初始消息
  - 第三步，通过 `ToolRegistry.get_definitions(required_tools)` 只把本次工作流允许的工具暴露给 LLM
  - 第四步，调用 `LLMProvider.chat()`，让 LLM 基于上下文决定是否调用工具
  - 第五步，如果 LLM 返回 `tool_calls`，则通过 `ToolRegistry.execute()` 执行工具
  - 第六步，工具执行结果会以 `AgentToolResult` 的形式进入 `AgentLoopState.tool_results`，同时被追加为 tool 消息
  - 第七步，下一轮 LLM 可以读取 tool 消息，继续调用工具或输出最终答案
  - 第八步，如果 LLM 输出最终文本，loop 返回 `status=success` 的 `AgentRunResult`
  - 第九步，如果超过 `max_iterations` 仍没有最终答案，loop 返回 `status=max_iterations`，避免无限循环
  - 第十步，如果中途异常，loop 返回 `status=failed`，并把错误类型与错误信息放入 payload，方便排查
- 当前日志与可观测性：
  - 每轮 loop 开始都会记录 `trace_id`、`workflow_type`、`iteration`
  - 工具调用本身沿用 T2.10 `ToolRegistry` 的工具执行日志
  - 最终结果中保留完整 `loop_state`，可以回放消息、工具调用和工具结果
- 当前演示脚本逻辑：
  - `scripts/agent_loop_demo.py` 构造一个 `meeting.soon` 事件
  - 先经过 `WorkflowRouter` 生成 `AgentDecision`
  - 再经过 `WorkflowContextBuilder` 生成 `WorkflowContext`
  - 然后创建一个本地 demo 工具 `demo.fetch_context`
  - 最后使用 `DryRunLLMProvider + ToolRegistry + MeetFlowAgentLoop` 跑完整循环
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/agent_loop.py core/llm.py core/__init__.py scripts/agent_loop_demo.py` 验证语法正确
  - 已通过 `python3 scripts/agent_loop_demo.py --event-type meeting.soon --meeting-id meeting_loop_demo` 验证完整 “LLM -> 工具 -> LLM -> 最终结果” 链路
  - 已通过 `python3 scripts/agent_loop_demo.py --event-type meeting.soon --meeting-id meeting_loop_demo --max-iterations 1` 验证最大轮数保护生效
- 这一步对后续任务的意义：
  - T2.14 可以把 `WorkflowRouter`、`WorkflowContextBuilder`、`MeetFlowAgentLoop` 串成真正的业务 Agent 主入口
  - M3 会前卡片、M4 会后任务、M5 风险巡检都可以复用同一个 Agent Loop
  - 后续只需要替换真实 LLM Provider 和真实飞书工具注册器，就能从 dry-run demo 迁移到真实业务执行

### T2.14 实现 MeetFlowAgent 主入口

- 优先级：`P0`
- 目标：实现业务侧垂直 Agent 的统一入口，把路由、上下文、LLM loop、策略和结果保存串起来
- 主流程：
  - 接收 `AgentInput`
  - 生成并绑定 `trace_id`
  - 调用 `WorkflowRouter` 生成决策
  - 通过 `WorkflowContextBuilder` 构建上下文
  - 调用 `MeetFlowAgentLoop` 执行受控工具推理
  - 调用对应工作流处理器完成卡片渲染、任务写入等业务封装
  - 保存 `AgentRunResult` 和 `WorkflowResult`
  - 对失败场景记录错误并返回可解释结果
- 验收标准：
  - 可以用脚本模拟一次 `meeting.soon` 事件并完成路由
  - 可以用脚本模拟一次 `minute.ready` 事件并完成路由
  - 失败时不会静默吞错，有明确状态和错误原因

#### T2.14 当前实现细节

- 已创建文件：
  - `core/agent.py`
  - `scripts/meetflow_agent_live_test.py`
- 已更新文件：
  - `core/__init__.py`
  - `adapters/feishu_client.py`
  - `adapters/feishu_tools.py`
  - `core/tools.py`
  - `tasks.md`
- 已实现的核心类：
  - `MeetFlowAgent`：业务侧垂直 Agent 主入口，统一串联路由、上下文、LLM Loop、工具注册器和本地存储
  - `MeetFlowAgentError`：Agent 主入口异常类型，预留给后续更严格的错误分层
  - `ScriptedCalendarProvider`：live test 脚本里的脚本化 Provider，用于不依赖真实 LLM 时稳定触发一次日历工具调用
- 已实现的核心函数：
  - `MeetFlowAgent.run()`：执行一次完整 Agent 运行，从 `AgentInput` 到 `AgentRunResult`
  - `MeetFlowAgent._filter_required_tools()`：按 `allow_write` 过滤工具，默认不把发消息、建任务等写工具暴露给 LLM
  - `MeetFlowAgent._is_duplicate()`：检查幂等键是否已处理，避免真实事件重复执行
  - `MeetFlowAgent._mark_idempotency()`：在成功或达到最大轮数时记录幂等键
  - `MeetFlowAgent._save_result()`：把 `AgentRunResult` 转成 `WorkflowResult` 并保存
  - `create_meetflow_agent()`：根据系统配置装配 `FeishuClient`、`ToolRegistry`、`LLMProvider`、`WorkflowRouter`、`WorkflowContextBuilder` 和 `MeetFlowAgentLoop`
  - `scripts/meetflow_agent_live_test.py::build_payload()`：为真实测试构造包含日历窗口、项目 ID、工具名单的 payload
  - `scripts/meetflow_agent_live_test.py::build_llm_settings()`：从 `llm_providers.local.json`、环境变量或默认配置中读取模型配置，但不会打印 API Key
  - `scripts/meetflow_agent_live_test.py::print_result()`：默认只打印摘要、最终回答和工具结果，避免输出过多敏感上下文
  - `scripts/meetflow_agent_live_test.py::save_token_bundle()`：当飞书用户 token 被自动刷新时，把新的 access_token / refresh_token 回写到本地配置
- 已补充的飞书 token 持久化能力：
  - `FeishuClient` 新增 `user_token_callback`
  - `refresh_user_access_token()` 自动刷新成功后会触发回调
  - `poll_device_token()` 登录成功后也会触发回调
  - live test 脚本通过该回调写入 `config/settings.local.json`
  - 这样可以避免飞书一次性 refresh_token 被使用后没有保存新 token，导致下一次调用报 `20064 refresh token revoked`
- 已修复的工具结果可读性问题：
  - 问题现象：真实 DeepSeek 调用了 `calendar.list_events`，飞书也返回了 1 条会议，但第二轮 LLM 只能看到“返回 1 条记录”，看不到会议标题、时间和参与人
  - 根因：`ToolRegistry` 把结构化数据保存在 `AgentToolResult.data`，但喂回 LLM 的 tool message `content` 只包含简短摘要
  - 修复：`core/tools.py::build_tool_result_content()` 现在会返回“简短摘要 + 结构化数据 JSON”
  - 效果：LLM 第二轮推理可以直接读取 `items[].summary`、`start_time`、`end_time`、`attendees` 等字段并生成准确总结
- 当前 Agent 主入口运行逻辑：
  - 第一步，调用 `bind_trace_id()` 生成并绑定本次运行的 `trace_id`
  - 第二步，`WorkflowRouter.route()` 根据 `AgentInput.event_type` 生成 `AgentDecision`
  - 第三步，如果路由结果不是 ready，则直接返回 unsupported / skipped 等终态结果
  - 第四步，如果开启幂等，先用 `MeetFlowStorage.is_idempotency_key_processed()` 判断是否重复
  - 第五步，通过 `WorkflowContextBuilder.build()` 构造统一 `WorkflowContext`
  - 第六步，按 `allow_write` 过滤工具，默认只保留只读工具
  - 第七步，调用 `MeetFlowAgentLoop.run()`，让 LLM 在受控工具集中完成“思考 - 调工具 - 观察 - 输出”
  - 第八步，把 `AgentDecision` 和最终生效工具列表写入 `AgentRunResult.payload`
  - 第九步，如果启用幂等且执行成功，记录幂等键
  - 第十步，把结果保存到本地 `workflow_results`
  - 第十一步，无论成功失败，最后调用 `reset_trace_id()` 清理上下文，避免日志串号
- 当前真实测试脚本能力：
  - 默认 `--llm-provider scripted_calendar`：不调用真实 LLM，但会走完整 Agent Loop，并真实调用飞书日历 API
  - 可切换 `--llm-provider deepseek`：使用 DeepSeek 等 OpenAI-compatible 模型进行真实 tool calling
  - 默认只开放 `calendar.list_events`
  - 可通过多个 `--tool` 显式开放更多工具
  - 默认不开放写工具
  - 只有传入 `--allow-write` 时，LLM 才能看到并调用 `im.send_card`、`tasks.create_task` 这类写工具
  - 默认不启用幂等，方便本地反复测试
  - 传入 `--enable-idempotency` 后，会记录并检查幂等键，更接近真实事件订阅模式
- 当前推荐测试命令：
  - 快速验证 Agent 主入口和真实飞书日历链路：
    `python3 scripts/meetflow_agent_live_test.py --llm-provider scripted_calendar --max-iterations 3`
  - 指定时间窗口查询日历：
    `python3 scripts/meetflow_agent_live_test.py --llm-provider scripted_calendar --start-time 1777132800 --end-time 1777219200`
  - 使用真实 DeepSeek 模型驱动工具选择：
    `DEEPSEEK_API_KEY=你的key python3 scripts/meetflow_agent_live_test.py --llm-provider deepseek --tool calendar.list_events --prompt "请查询我今天的会议安排，并总结时间、标题和参与人。"`
  - 测试写工具前需要显式开放：
    `python3 scripts/meetflow_agent_live_test.py --llm-provider deepseek --tool im.send_card --allow-write --prompt "向测试群发送一张 MeetFlow 连通性测试卡片。"`
- 当前验证结果：
  - 已通过 `python3 -m py_compile core/agent.py core/__init__.py adapters/feishu_tools.py scripts/meetflow_agent_live_test.py` 验证语法正确
  - 已通过 `python3 scripts/meetflow_agent_live_test.py --llm-provider dry_run --max-iterations 2` 验证主入口错误降级链路
  - 已通过 `python3 scripts/meetflow_agent_live_test.py --llm-provider scripted_calendar --max-iterations 3` 真实调用飞书日历 API，接口返回成功，当前时间窗返回 0 条日程
  - 在重复真实测试时发现旧 refresh_token 已失效的问题，并已补齐后续自动刷新后的 token 回写逻辑
  - 已通过本地样例验证 `build_tool_result_content()` 会把日历事件详情写入 tool message，而不是只返回记录数
- 这一步对后续任务的意义：
  - 后续 M3-M5 不再只是“工作流脚本”，而是可以挂在同一个 `MeetFlowAgent` 主入口下运行
  - 真实事件订阅、定时任务、本地 CLI 都可以统一构造 `AgentInput` 调用 `MeetFlowAgent.run()`
  - LLM 的自主工具选择被限制在 `AgentDecision.required_tools` 和 `allow_write` 双重边界内，兼顾 Agent 能力与安全控制

### T2.15 实现 Agent Policy 与自动化边界

- 优先级：`P1`
- 目标：让 Agent 不只是执行流程，还能控制“哪些动作允许自动做，哪些需要确认”
- 首批策略：
  - 低置信度 Action Item 不直接创建任务
  - 缺少负责人或截止时间的任务进入待确认卡片
  - 同一会议同一时间窗口不重复发送会前卡片
  - 同一任务同一风险当天不重复提醒
  - 写操作必须支持 dry-run 或幂等键
- 验收标准：
  - M4 自动创建任务前会检查置信度和字段完整性
  - M5 风险提醒前会检查降噪窗口
  - LLM 不能直接绕过 Policy 执行写操作

#### T2.15 当前实现细节

- 已创建文件：
  - `core/policy.py`
  - `scripts/agent_policy_demo.py`
- 已更新文件：
  - `core/agent_loop.py`
  - `core/agent.py`
  - `core/__init__.py`
  - `adapters/feishu_tools.py`
  - `tasks.md`
- 已实现的核心类：
  - `AgentPolicy`：Agent 自动化边界判断器，在工具真正执行前判断是否允许自动执行
  - `AgentPolicyConfig`：策略阈值配置，包括行动项最低置信度、是否要求负责人、是否要求截止时间、写操作是否必须带幂等键
  - `PolicyDecision`：单次策略判断结果，状态包括 `allow`、`blocked`、`needs_confirmation`
  - `AgentPolicyError`：策略层异常类型，预留给后续更严格的策略错误处理
- 已实现的核心函数：
  - `AgentPolicy.authorize_tool_call()`：工具执行前的统一策略入口
  - `AgentPolicy._authorize_create_task()`：检查创建任务是否满足自动化条件
  - `AgentPolicy._authorize_risk_reminder()`：检查风险提醒是否具备幂等键和降噪基础
  - `AgentPolicy._resolve_idempotency_key()`：从工具参数或 `WorkflowContext.raw_context.decision.idempotency_key` 派生写操作幂等键
  - `AgentPolicy._is_duplicate_side_effect()`：基于本地存储检查写操作是否重复
- 已接入 Agent Loop 的位置：
  - `MeetFlowAgentLoop` 新增 `policy`、`storage`、`allow_write`
  - 每次 LLM 返回 `tool_calls` 后，执行真实工具前先调用 `AgentPolicy.authorize_tool_call()`
  - 如果策略返回 `blocked` 或 `needs_confirmation`，不会调用真实工具 handler
  - 被拦截的结果会以 `AgentToolResult` 形式喂回 LLM，让模型能解释为什么没有执行
  - 如果策略返回 `allow`，会使用 `PolicyDecision.patched_arguments` 继续执行工具
- 当前首批策略：
  - 只读工具默认允许自动执行
  - 写工具默认必须显式开启 `allow_write`
  - 写操作必须具备幂等键；如果 LLM 没传，会从工作流幂等键派生
  - 创建任务时，低于 `min_action_item_confidence` 的行动项进入待确认
  - 创建任务时，缺少 `assignee_ids` 或 `due_timestamp_ms` 的行动项进入待确认
  - 风险提醒必须带幂等键，后续才能做同一风险当天不重复提醒
  - 如果本地存储中已经存在同一幂等键，写操作会被阻止
- 已更新的飞书工具：
  - 新增 `contact.get_current_user`：读取当前登录用户信息，让 LLM 能把“我/本人/自己”解析为当前用户 open_id
  - 新增 `contact.search_user`：按姓名、邮箱或手机号搜索飞书用户，让 LLM 能把其他人的名字解析为 open_id
  - `im.send_text` 新增 `idempotency_key` 参数，并传给飞书消息接口
  - `im.send_card` 新增 `idempotency_key` 参数，并传给飞书消息接口
  - 这样消息发送也具备幂等能力，不再只是任务创建具备幂等键
- 已补充的人员解析能力：
  - `FeishuClient.search_users()` 封装 `GET /open-apis/search/v1/user`
  - `meetflow_agent_live_test.py` 中只要开放 `tasks.create_task`，就会自动补充 `contact.get_current_user` 和 `contact.search_user`
  - live test 的工作流目标会明确提示 LLM：负责人为“我”时先调用 `contact_get_current_user`；负责人为具体姓名时先调用 `contact_search_user`
  - LLM 不应把自然语言姓名直接写入 `assignee_ids`，必须使用通讯录工具返回的 open_id
- 当前演示脚本逻辑：
  - `scripts/agent_policy_demo.py --scenario missing_task_fields`：模拟 LLM 想创建缺少负责人和截止时间的任务，Policy 返回 `needs_confirmation`
  - `scripts/agent_policy_demo.py --scenario valid_task`：模拟字段完整、置信度足够的任务创建，Policy 放行，工具 handler 执行
  - `scripts/agent_policy_demo.py --scenario write_disabled`：模拟 LLM 想发送卡片但未开启写权限，Policy 返回 `blocked`
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/policy.py core/agent_loop.py core/agent.py core/__init__.py adapters/feishu_tools.py scripts/agent_policy_demo.py` 验证语法正确
  - 已通过 `python3 scripts/agent_policy_demo.py --scenario missing_task_fields` 验证缺字段任务进入待确认，真实 handler 未执行
  - 已通过 `python3 scripts/agent_policy_demo.py --scenario valid_task` 验证字段完整任务可被自动执行，并自动补齐幂等键
  - 已通过 `python3 scripts/agent_policy_demo.py --scenario write_disabled` 验证未开启写权限时，LLM 不能绕过 Policy 发送消息
- 这一步对后续任务的意义：
  - M4 会后任务创建可以先让 LLM 抽取候选行动项，再由 `AgentPolicy` 判断自动创建还是进入确认卡
  - M5 风险巡检可以用幂等键和本地存储做降噪，避免同一风险一天内重复提醒
  - 后续 `AgentPolicyConfig` 可以从配置文件读取，让比赛 Demo 和真实使用采用不同自动化强度

### T2.16 实现 Agent 手动调试入口

- 优先级：`P0`
- 目标：提供一个命令行入口，方便本地模拟不同事件，验证 Agent 决策和上下文构建
- 建议脚本：
  - `scripts/agent_demo.py`
- 示例：
  - `python3 scripts/agent_demo.py --event-type meeting.soon --calendar-id primary`
  - `python3 scripts/agent_demo.py --event-type minute.ready --minute-token xxx`
  - `python3 scripts/agent_demo.py --event-type risk.scan.tick`
- 验收标准：
  - 能打印 `AgentDecision`
  - 能打印 `WorkflowContext`
  - 能看到 LLM loop 每一轮选择了哪些工具
  - 能选择 dry-run，不产生真实副作用

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

- `P0` MeetFlowAgent 主入口
- `P0` Agent Runtime 数据模型
- `P0` 工作流路由器
- `P0` 工具注册器
- `P0` 工作流上下文构建器
- `P1` Agent Policy 与自动化边界
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
3. `T2.8 - T2.16` 完成后，系统才具备真正的业务侧垂直 Agent Runtime
4. `T3.x` 完成后，才有第一段可演示主动链路
5. `T4.x` 完成后，主闭环才成立
6. `T5.x` 完成后，项目才真正体现“主动跟踪价值”

### 可并行任务

- 卡片模板设计可以和飞书客户端封装并行
- 评估数据准备可以和会后工作流开发并行
- 风险规则梳理可以和任务写入模块并行

---

## 8. 建议开发顺序

建议按如下顺序推进：

1. 完成项目骨架、配置、日志、存储
2. 打通飞书读取与卡片发送
3. 补齐 MeetFlowAgent Runtime、工具注册器、路由器和上下文构建器
4. 实现会前卡片工作流
5. 实现会后总结与任务创建
6. 实现风险巡检与提醒
7. 最后补指标、评估与答辩材料

原因很简单：

- 会前卡片最容易先演示价值
- 会后任务创建最能体现闭环
- 风险巡检是加分项，但依赖前面结果
- Agent Runtime 是垂直 Agent 的“大脑”和“状态中枢”，应在具体工作流前补齐

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
