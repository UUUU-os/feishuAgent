# MeetFlow 代码仓库融合方案

## 1. 背景与目标

当前需要把协作者仓库：

```text
/home/tanyd/ye/workhard/coworker/feishuAgent-main
```

融合进当前主仓库：

```text
/home/tanyd/ye/workhard/feishuAgent-main
```

当前主仓库主要承载 M5 任务风险提醒、会前卡片回调 MVP、结构化观测和近期 M3/M4 回归修复；协作者仓库主要承载 M3/M4 的会后总结、任务待确认、卡片按钮回调、后台 daemon 和真实飞书联调脚本。

融合目标不是把两个目录简单覆盖，而是把当前目录整理成一个完整、连续、可测试、可恢复的 MeetFlow 仓库：

```text
AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> WorkflowRunner
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

所有 M3/M4/M5 写操作仍必须经过 `ToolRegistry` 和 `AgentPolicy`，不能让会后脚本、卡片回调或 daemon 绕过安全边界。

## 2. 阅读结论

### 当前主仓库保留价值

当前主仓库已经完成并应作为融合 base 的能力：

- `core/risk_scan.py`、`cards/risk_scan.py`、`scripts/risk_scan_demo.py` 和对应测试，构成 M5 风险扫描主实现。
- `core/workflows.py` 中的 `RiskScanWorkflow.post_process_result()`，会把 `tasks.list_my_tasks` 工具结果转成 `risk_scan`、`notification_decision` 和 `card_payload`。
- `core/storage.py` 中的 `risk_notifications` 表，以及 `record_risk_notification()` / `has_recent_risk_notification()` 等降噪能力。
- `core/policy.py` 中针对 `risk_scan + send_message` 的风险提醒降噪检查，能阻止空风险或全部被降噪后的消息发送。
- `core/observability.py`、`core/agent.py`、`core/agent_loop.py`、`core/tools.py` 中的结构化日志和安全错误脱敏链路。
- `core/card_actions.py`、`adapters/feishu_event_handler.py`、`scripts/feishu_event_server.py` 和对应测试，构成当前会前卡片刷新回调 MVP。
- 当前 `WorkflowRunner.run()` 已支持 `storage` 和单次 `allow_write` 透传，避免把写权限挂在共享 loop 实例上。

### 协作者仓库应引入价值

协作者仓库已经完成并应融合进主仓库的能力：

- `core/post_meeting.py`：M4 会后核心业务模型与纯函数，包括纪要清洗、Action Item 抽取、决策/开放问题抽取、待确认原因、任务创建参数、task mapping payload 和 M4 RAG query plan。
- `core/post_meeting_tools.py`：把 M4 产物构建、相关知识增强、任务参数准备、总结卡发送、pending registry 保存暴露成受控工具。
- `cards/post_meeting.py` 和 `cards/layout.py`：会后总结卡、待确认任务卡、单条按钮卡、自动创建回告卡等模板。
- `core/confirmation_commands.py`：pending action registry、群消息确认口令、watcher 状态读写和消息绑定。
- `core/card_callback.py`：M4 待确认任务卡片按钮回调，确认创建仍会解析负责人、调用 ToolRegistry、执行 AgentPolicy、写入 task_mappings。
- `tests/test_post_meeting_card_callback.py`、`tests/test_post_meeting_rag_query.py`：覆盖 M4 按钮卡状态机、重复点击拦截、截止日期归一、RAG query 去噪。
- `scripts/post_meeting_demo.py`、`scripts/post_meeting_live_test.py`、`scripts/post_meeting_agent_live_test.py`、`scripts/post_meeting_button_flow_live_test.py` 等 M4 本地和真实联调入口。
- `scripts/meetflow_daemon.py`、`scripts/post_meeting_confirmation_watcher.py`、`scripts/post_meeting_card_callback_server.py` / `ws.py`：会前、会后、RAG 刷新的后台调度和回调接入探索。其中 `post_meeting_card_callback_ws.py` 使用飞书 Python SDK `lark_oapi` 的 WebSocket 长连接接收 `card.action.trigger`，它和当前主仓库的公网 HTTPS 回调方案需要统一成双通道接入。
- `docs/tasks/m4-post-meeting.md` 与 `docs/tasks/m4-post-meeting-handoff.md`：M4 实现记录和交接说明。

## 3. 融合原则

1. **当前主仓库作为 base**  
   当前仓库已有 M5、观测、会前卡片回调和 allow_write 修复。公共文件不能用协作者版本整文件覆盖。

2. **协作者 M4 文件优先按模块引入**  
   新文件可以整体引入，再做 import 和接口适配。公共文件必须人工合并。

3. **M4 与 M5 通过数据契约对接**  
   M4 生产 `ActionItem`、`task_mappings`、`meeting_id`、`minute_token`、`evidence_refs`；M5 消费任务状态、映射和提醒历史。M5 不应理解 M4 的纪要抽取细节。

4. **任务创建默认走人工确认**  
   协作者版本的 `AgentPolicy.require_human_confirmation_for_tasks=True` 更安全，应合入。但 M5 风险提醒的降噪检查也必须保留。

5. **后台 daemon 只负责发现和调度**  
   `meetflow_daemon.py` 可以引入，但必须明确它不能直接绕过 Agent 主链路执行写副作用。

6. **官方 SDK/长连接优先，公网 HTTPS 兜底**  
   M4 卡片按钮和后续飞书事件接入优先采用飞书官方 Python SDK `lark_oapi` 的 WebSocket 长连接，降低本地公网隧道、URL 验证、企业网关和 HTTPS 证书带来的不稳定性。当前主仓库的 `scripts/feishu_event_server.py` 公网 HTTPS 方式仍保留，作为 fallback、验收、排障和无法使用长连接环境下的鲁棒性实现。

7. **运行数据不作为代码融合对象**  
   `storage/reports/`、`storage/post_meeting_pending_actions.json`、`storage/meetflow_daemon_state.json`、本地 sqlite 和真实联调产物只作为参考，不直接纳入提交。

## 4. 文件处理矩阵

### 4.1 可直接引入的新文件

这些文件当前主仓库没有同名实现，建议先整体引入，再跑编译和单测：

```text
core/post_meeting.py
core/post_meeting_tools.py
core/card_callback.py
core/confirmation_commands.py
adapters/feishu_callback_payloads.py
core/feishu_callback_dispatcher.py
cards/layout.py
cards/post_meeting.py
tests/test_post_meeting_card_callback.py
tests/test_post_meeting_rag_query.py
tests/test_feishu_callback_dispatcher.py
docs/tasks/m4-post-meeting-handoff.md
scripts/post_meeting_demo.py
scripts/post_meeting_live_test.py
scripts/post_meeting_agent_live_test.py
scripts/post_meeting_button_flow_live_test.py
scripts/post_meeting_card_callback_server.py
scripts/post_meeting_card_callback_ws.py
scripts/feishu_event_sdk_server.py
scripts/post_meeting_confirmation_watcher.py
scripts/post_meeting_confirmation_event_watcher.py
scripts/meetflow_daemon.py
scripts/setup_lark_oapi_venv.py
scripts/setup_card_action_trigger_event.py
```

引入后要检查这些文件是否依赖协作者版本中的公共 API。例如 `core/card_callback.py` 依赖 `cards.build_pending_action_item_callback_card`、`core.confirmation_commands`、`MeetFlowStorage.save_task_mapping()` 扩展字段和 `AgentPolicy` 的人工确认标记。

### 4.2 必须三方合并的公共文件

这些文件两个仓库都改过，禁止整文件覆盖：

```text
core/workflows.py
core/agent.py
core/router.py
core/policy.py
core/storage.py
core/__init__.py
cards/__init__.py
adapters/feishu_tools.py
adapters/feishu_client.py
adapters/feishu_event_handler.py
config/loader.py
config/settings.example.json
architecture.md
prd.md
tasks.md
docs/tasks/m3-pre-meeting.md
docs/tasks/m4-post-meeting.md
docs/tasks/m5-risk-scan.md
scripts/agent_demo.py
scripts/pre_meeting_live_test.py
scripts/feishu_event_server.py
```

### 4.3 不建议纳入或需清理后再纳入

这些文件更像临时探针、真实联调残留或本地命令误生成文件：

```text
--fact
--message-type
--chat-id
--text
-d
-H
-X
cloudflared-linux-amd64.deb
storage/reports/**
storage/*.json
storage/*.sqlite
scripts/test_messages.py
scripts/test_messages2.py
scripts/test_messages3.py
scripts/test_logs.py
scripts/test_status.py
scripts/test_parser.py
scripts/test_search_logs.py
```

这些内容可以保留在本地排查，但不应作为融合提交的一部分。若确实需要某个 probe 脚本，应改名为有业务含义的 `scripts/*_probe.py`，并补充不会打印密钥的说明。

## 5. 飞书回调双通道改造方案

### 5.1 当前两套接入方式

当前主仓库实现的是公网 HTTPS 回调：

```text
飞书开放平台 HTTP callback
  -> 公网 HTTPS / cloudflared / ngrok
  -> scripts/feishu_event_server.py
  -> adapters.feishu_event_handler.FeishuEventHandler
  -> core.card_actions.CardActionRouter
  -> AgentInput(card.refresh_pre_meeting)
```

优点是协议清晰、便于用 curl、飞书 URL verification 和公网隧道调试；缺点是依赖公网地址、HTTPS 证书、隧道稳定性和飞书后台回调 URL 配置。

协作者 M4 实现的是飞书官方 SDK WebSocket 长连接：

```text
飞书开放平台长连接
  -> lark_oapi.lark.ws.Client
  -> EventDispatcherHandler.register_p2_card_action_trigger(...)
  -> scripts/post_meeting_card_callback_ws.py
  -> core.card_callback.handle_post_meeting_card_callback(...)
```

优点是不需要公网隧道，更适合本地长期联调和真实测试；缺点是引入 `lark-oapi` 依赖，且 SDK 的事件对象结构需要归一化后才能复用现有业务处理器。

融合后的目标是：

```text
                 +------------------------------+
HTTP callback -> | FeishuCallbackPayloadAdapter | --+
                 +------------------------------+   |
                                                    v
                 +------------------------------+   +-----------------------------+
SDK websocket -> | FeishuSdkPayloadAdapter      | -> | FeishuCallbackDispatcher   |
                 +------------------------------+   +-------------+---------------+
                                                                  |
                                                                  v
                                         +------------------------+------------------------+
                                         |                                                 |
                                         v                                                 v
                              M3 CardActionRouter                              M4 card_callback handler
                        card.refresh_pre_meeting                         confirm/edit/reject pending task
```

业务侧只能看到统一后的 callback payload / action envelope，不关心事件来自公网 HTTPS 还是官方 SDK 长连接。

### 5.2 新增统一回调 payload adapter

建议新增 `adapters/feishu_callback_payloads.py`，只处理协议归一化，不做业务动作。

核心结构：

```python
@dataclass(slots=True)
class FeishuCallbackEnvelope:
    """飞书回调统一信封。"""

    source: str  # "http" | "sdk_ws" | "lark_cli"
    event_type: str
    event_id: str
    action: str
    action_value: dict[str, Any]
    operator_open_id: str = ""
    chat_id: str = ""
    message_id: str = ""
    open_message_id: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
```

核心函数：

```python
def normalize_http_callback_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """处理 HTTP 回调 payload，保留 challenge/token/encrypt 字段。"""


def normalize_sdk_card_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """处理 lark_oapi marshal 后的 card.action.trigger payload。"""


def build_callback_envelope(payload: dict[str, Any], source: str) -> FeishuCallbackEnvelope:
    """从统一 payload 中提取 action、operator、message context 和 action.value。"""
```

协作者 `post_meeting_card_callback_ws.py` 中的这些函数应迁移到该 adapter：

- `callback_payload_to_dict()`
- `normalize_card_action_payload()`
- `find_first_action_value()`

当前 `adapters/feishu_event_handler.py` 中的字段提取函数也应复用该 adapter，避免 HTTP 和 SDK 各自维护一套宽松解析逻辑。

### 5.3 新增统一业务分发器

建议新增 `core/feishu_callback_dispatcher.py`，只负责在 M3/M4 业务 handler 之间分发。

核心职责：

- 识别 URL verification challenge，仅 HTTP 通道需要。
- 识别 `card.action.trigger`。
- 按 `action_value["action"]`、`source_card`、`workflow_type` 分发到 M3 或 M4。
- 统一返回飞书 toast/card 响应。
- 对需要异步执行 Agent 的 M3 卡片刷新，返回 `agent_input` 给入口脚本后台执行。

分发规则：

```text
action in {
  confirm_create_task,
  reject_create_task,
  edit_task_fields
}
或 source_card/post_meeting/pending_action 标记存在
  -> core.card_callback.handle_post_meeting_card_callback()

action in {
  refresh_pre_meeting_brief,
  create_task_draft,
  send_to_me
}
或 workflow_type == pre_meeting_brief
  -> adapters.feishu_event_handler.FeishuEventHandler.parse_card_action()
  -> core.card_actions.CardActionRouter.route()

未知 action
  -> 返回 info/error toast，并落结构化事件
```

推荐接口：

```python
@dataclass(slots=True)
class FeishuCallbackResponse:
    """统一回调响应。"""

    status: str
    body: dict[str, Any]
    agent_input: AgentInput | None = None


class FeishuCallbackDispatcher:
    """统一处理飞书卡片与事件回调。"""

    def __init__(
        self,
        settings: Settings,
        storage: MeetFlowStorage,
        feishu_client: FeishuClient,
        policy: AgentPolicy | None = None,
        card_action_router: CardActionRouter | None = None,
    ) -> None:
        ...

    def dispatch_card_action(
        self,
        payload: dict[str, Any],
        source: str,
    ) -> FeishuCallbackResponse:
        ...
```

### 5.4 官方 SDK 长连接入口

建议新增通用入口 `scripts/feishu_event_sdk_server.py`，并让协作者的 `scripts/post_meeting_card_callback_ws.py` 后续退化为兼容 wrapper 或示例脚本。

入口职责：

- 启动 `lark_oapi` WebSocket 长连接。
- 注册 `card.action.trigger` 处理器。
- 把 SDK 对象通过 `lark.JSON.marshal(data)` 转成 dict。
- 调用 `normalize_sdk_card_action_payload()`。
- 交给 `FeishuCallbackDispatcher.dispatch_card_action(source="sdk_ws")`。
- 把 `FeishuCallbackResponse.body` 包装成 `P2CardActionTriggerResponse`。
- 如 `response.agent_input` 存在，后台异步执行 Agent，并使用单次 `allow_write` 参数。

命令设计：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --dry-run --log-level debug
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --execute-agent --agent-provider dry-run
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --execute-agent --agent-provider configured --allow-write
```

注意：

- `lark-oapi` 依赖建议继续放在 `.venv-lark-oapi`，避免污染主环境中的 protobuf、chromadb、sentence-transformers。
- SDK 入口需要 `settings.feishu.app_id` 和 `settings.feishu.app_secret`，但日志只能打印字段是否存在，不能打印真实值。
- 飞书后台需要选择“使用长连接接收回调”，并添加 `card.action.trigger` 事件。
- `--dry-run` 只打印已脱敏 payload 和 toast，不创建任务、不发卡。

### 5.5 公网 HTTPS fallback 入口

保留并改造当前 `scripts/feishu_event_server.py`，使它也走同一个 dispatcher：

```text
HTTP POST
  -> read_json
  -> FeishuEventHandler.handle_verification()
  -> normalize_http_callback_payload()
  -> FeishuCallbackDispatcher.dispatch_card_action(source="http")
  -> write_json(response.body)
  -> optional background Agent
```

保留的能力：

- `/healthz`
- `/feishu/events`
- `/feishu/card/actions`
- URL verification challenge
- verification token 校验
- `--execute-agent`
- `--allow-write`
- `--agent-provider configured|dry-run`

新增要求：

- HTTP 入口不能只支持 M3，会后 `confirm_create_task` / `edit_task_fields` / `reject_create_task` 也必须能走公网 fallback。
- HTTP 入口对 `encrypt` 仍可先明确报“未实现解密”，不要假装成功。
- 当 SDK 通道不可用、企业后台临时切回公网回调时，业务逻辑不需要修改。

### 5.6 `lark-cli` 观察台定位

协作者 `scripts/live_environment_watch.py` 使用 `lark-cli event +subscribe`，它不应成为正式业务入口，而应定位为真实环境观察台：

- 用于观察 `calendar.calendar.event.changed_v4`、`drive.file.*` 等事件是否真实投递。
- 用于触发 M3/M4/RAG 的兜底扫描验证。
- 用于排查 app_id、订阅关系、权限和事件类型配置。

正式服务入口优先使用：

```text
scripts/feishu_event_sdk_server.py
```

观察和排障使用：

```text
scripts/live_environment_watch.py
scripts/setup_card_action_trigger_event.py
lark-cli event +subscribe ...
```

### 5.7 配置改造

`config/loader.py` 和 `config/settings.example.json` 建议增加：

```json
{
  "feishu": {
    "event_receive_mode": "sdk_ws",
    "event_sdk_log_level": "info",
    "event_http_enabled": true,
    "event_http_paths": ["/feishu/events", "/feishu/card/actions", "/feishu/card/callback"]
  }
}
```

说明：

- `event_receive_mode`: `sdk_ws | http | dual`，默认建议 `sdk_ws`。
- `event_http_enabled`: 是否启动公网 HTTP fallback。
- `event_http_paths`: 兼容当前主仓库和协作者 M4 HTTP server 的路径。
- 不把 app secret、verification token、encrypt key 写进示例配置真实值。

### 5.8 测试改造

新增 `tests/test_feishu_callback_dispatcher.py`：

覆盖场景：

- HTTP challenge 返回 `{"challenge": ...}`。
- HTTP M3 `refresh_pre_meeting` 回调可生成 `AgentInput(event_type="card.refresh_pre_meeting")`。
- SDK M4 `confirm_create_task` payload 可分发到 `handle_post_meeting_card_callback()`。
- SDK payload 中 action/value 被包在 `operator.value`、`action.value`、顶层 `value` 时都能归一化。
- 未知 action 返回可读 toast，不抛到入口层。
- token 不匹配时 HTTP 通道拒绝，但不打印真实 token。

扩展现有测试：

- `tests/test_card_actions.py` 保持 M3 回调路由。
- `tests/test_post_meeting_card_callback.py` 保持 M4 状态机。
- 新 dispatcher 测试只 mock 业务 handler，不重复测试 M3/M4 内部逻辑。

### 5.9 双通道验收命令

本地无 SDK 依赖时：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_feishu_event_handler tests.test_card_actions
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_card_callback tests.test_feishu_callback_dispatcher
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_action_demo.py
```

SDK 隔离环境：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --dry-run --log-level debug
```

公网 fallback：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/feishu_event_server.py --host 0.0.0.0 --port 8765 --agent-provider dry-run
```

真实写入只允许在 SDK 或 HTTP 入口显式加：

```bash
--execute-agent --allow-write --agent-provider configured
```

并且 M4 创建任务仍必须来自人工确认卡片或确认 watcher。

## 6. 公共文件合并细节

### 6.1 `core/workflows.py`

以当前主仓库为 base，保留：

- `WorkflowRunner.run(..., storage=None, allow_write=False)` 签名。
- `loop.run(..., allow_write=allow_write)` 的单次写权限透传。
- `post_process_result()` 钩子和 `RiskScanWorkflow.post_process_result()`。
- `RiskScanWorkflow` 的 M5 风险产物生成逻辑。

从协作者仓库合入：

- `from core.post_meeting import build_post_meeting_artifacts`
- `PostMeetingFollowupWorkflow.prepare_context()` 里生成 `post_meeting_artifacts`、`post_meeting_input`、`cleaned_transcript`、`meeting_summary_draft`、`post_meeting_card_payloads`、`pending_action_items`、`auto_create_candidates`、`human_review_candidates`、`related_knowledge`。
- `post_meeting_followup` 的 allowed tools，加入 `knowledge.search`、`knowledge.fetch_chunk`、`post_meeting.*` 工具。
- 会后 workflow goal 中“主链路不自动建任务，人工确认后仍走 Policy”的约束。

融合后阶段列表应包含：

```text
prepare_context
build_plan_or_query
agent_loop
post_process_result
validate_output
persist_and_audit
```

### 6.2 `core/agent.py`

以当前主仓库为 base，保留：

- 结构化事件：`workflow_started`、`route_decision`、`workflow_finished`、`workflow_failed`。
- `safe_error_message()` 脱敏。
- `build_group_id()`。
- 不再写 `self.loop.allow_write = allow_write`，继续通过 `runner.run(... allow_write=allow_write)` 传递。

从协作者仓库合入：

- `from core.post_meeting_tools import register_post_meeting_tools`
- 在默认工具注册时调用 `register_post_meeting_tools(...)`。

推荐装配顺序：

```text
create_feishu_tool_registry()
-> register_knowledge_tools()
-> register_post_meeting_tools()
-> MeetFlowAgentLoop(...)
```

### 6.3 `core/router.py`

以当前主仓库为 base，保留：

- `card.refresh_pre_meeting -> pre_meeting_brief` 路由。
- `risk.scan.tick -> risk_scan` 路由。
- 当前 `build_idempotency_key()` 对显式幂等键的直接复用逻辑。

从协作者仓库合入：

- `minute.ready` 的 reason 改为发送待人工确认任务卡。
- `minute.ready` 和 `MANUAL_WORKFLOW_TOOLS["post_meeting_followup"]` 加入：

```text
knowledge.search
knowledge.fetch_chunk
post_meeting.build_artifacts
post_meeting.enrich_related_knowledge
post_meeting.prepare_task
post_meeting.send_summary_card
post_meeting.save_pending_actions
contact.get_current_user
contact.search_user
im.send_card
```

任务创建工具 `tasks.create_task` 不建议继续暴露给会后主链路 LLM；确认创建应由卡片回调或 watcher 入口单独触发。

### 6.4 `core/policy.py`

需要把两边安全策略合并，而不是二选一。

保留当前主仓库：

- 风险提醒必须有幂等键。
- `risk_count <= 0` 时阻止发送。
- `notify_count <= 0` 时阻止发送。
- metadata 中保留 `risk_count`、`notify_count`、`suppressed_count`。

从协作者仓库合入：

- `AgentPolicyConfig.require_human_confirmation_for_tasks = True`。
- `_authorize_create_task(context=...)`。
- `_has_human_task_confirmation()`。
- 任务创建未带 `raw_context["human_confirmation"] = {"confirmed": True, "action": "confirm_create_task"}` 时返回 `needs_confirmation`。

融合后的规则应是：

```text
只读工具：allow
写工具未开启 allow_write：blocked
写工具缺幂等键：needs_confirmation
重复幂等键：blocked
create_task：必须人工确认 + 负责人 + 截止时间 + 置信度
risk_scan/send_message：必须有风险且本次有需要提醒的风险
其他写工具：allow，但仍带幂等键
```

### 6.5 `core/storage.py`

需要合并两套表结构：

- 当前主仓库的 `risk_notifications` 表和相关读写函数必须保留。
- 协作者仓库扩展后的 `task_mappings` 字段必须合入。
- 当前主仓库的 `find_latest_workflow_context_payload()` 必须保留，它服务会前卡片刷新补上下文。
- 协作者仓库的 `_ensure_task_mapping_columns()` 必须合入，兼容旧 sqlite。

融合后 `task_mappings` 字段至少包含：

```text
item_id
task_id
meeting_id
minute_token
title
owner
due_date
status
evidence_refs_json
source_url
updated_at
```

`save_task_mapping()` 要兼容旧调用：`meeting_id`、`minute_token`、`title`、`evidence_refs`、`source_url` 都设置默认值。

### 6.6 `adapters/feishu_tools.py`

以当前主仓库为 base，保留：

- `im.send_card` 支持完整 `card` 参数。
- M5 风险字段 `risk_count`、`notify_count`、`suppressed_count`。
- `send_card_with_fallback()` 对完整卡失败后的 fallback。

从协作者仓库合入：

- `tasks.create_task` schema 中的 `confidence`、`evidence_refs` 字段。
- `send_card_with_fallback()` 返回值补充 `card_delivery` 和 `fallback_reason`，方便真实联调排查。
- 文案改为“任务创建需先检查人工确认、负责人、截止时间和幂等键”。

### 6.7 `core/agent_loop.py` 与 `core/tools.py`

这两个文件都被改过，需要以当前主仓库为 base 先看差异。融合目标：

- 保留当前结构化观测事件和工具结果内容完整性。
- 保留 `allow_write` 作为 `run()` 参数，不恢复共享实例状态。
- 保证 `post_meeting.*` 内部工具名映射成 DeepSeek/OpenAI 兼容名，例如 `post_meeting_build_artifacts`。
- 工具返回给 LLM 的 `ToolResult.content` 必须包含结构化 JSON，避免模型声称“工具没有返回详情”。

### 6.8 `adapters/feishu_client.py`

两个仓库都有改动，应以当前主仓库为 base 做 API 能力补齐。重点检查：

- `update_card_message()` 是否存在；M4 `core/card_callback.py` 需要它刷新卡片状态。
- `send_card_message()`、`build_meetflow_card()`、`create_task()` 的参数是否与 M4 工具一致。
- OAuth token 刷新后是否仍会持久化新 refresh token。
- 异常信息是否继续隐藏 token、secret、API key。

### 6.9 `config/loader.py` 与 `config/settings.example.json`

当前主仓库包含 observability、risk rule 等设置；协作者仓库可能包含 daemon、M4 watcher、card callback 相关配置。融合时应：

- 保留 `ObservabilitySettings`、`RiskRuleSettings`、`KnowledgeSearchSettings`。
- 增加或确认 M3/M4 daemon 需要的 scheduler 字段，例如 `m3_minutes_before`、`m4_delay_minutes`、扫描间隔、默认 chat_id。
- 增加 `event_receive_mode`、`event_http_enabled`、`event_http_paths` 等事件接入配置，默认推荐 SDK 长连接，HTTP fallback 保持可用。
- 示例配置只写占位符，不写真实 app secret、token 或群 ID。

### 6.10 `adapters/feishu_event_handler.py` 与回调脚本

当前主仓库的 `adapters/feishu_event_handler.py` 继续保留 HTTP challenge、token 校验和 M3 卡片解析能力，但字段归一化逻辑应下沉到 `adapters/feishu_callback_payloads.py`。

`scripts/feishu_event_server.py` 改造成 HTTP fallback，不再只绑定 `CardActionRouter`，而是绑定 `FeishuCallbackDispatcher`。

协作者的 `scripts/post_meeting_card_callback_ws.py` 应升级为通用 `scripts/feishu_event_sdk_server.py`：

- 支持 M3 和 M4，不只支持 M4。
- 支持 `--dry-run`、`--execute-agent`、`--allow-write`、`--agent-provider`。
- SDK payload 归一化后交给同一个 dispatcher。

## 7. 推荐实施顺序

### Step 0：建立融合前基线

执行并记录：

```bash
git status --short
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/*.py adapters/*.py scripts/*.py
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests -p 'test_*.py'
```

如果当前基线已有失败，要先记录失败原因，避免后续把原有问题误判为融合引入。

### Step 1：引入 M4 新模块，不动公共骨架

先新增：

```text
core/post_meeting.py
core/post_meeting_tools.py
cards/layout.py
cards/post_meeting.py
tests/test_post_meeting_rag_query.py
scripts/post_meeting_demo.py
```

然后只跑：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/post_meeting.py core/post_meeting_tools.py cards/post_meeting.py cards/layout.py scripts/post_meeting_demo.py
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_rag_query
```

### Step 2：合并统一回调适配层

新增：

```text
adapters/feishu_callback_payloads.py
core/feishu_callback_dispatcher.py
tests/test_feishu_callback_dispatcher.py
```

先不接真实 SDK 和 HTTP server，只用单测验证两类 payload 都能归一化并分发：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_feishu_callback_dispatcher
```

### Step 3：合并导出和工具注册

修改：

```text
core/__init__.py
cards/__init__.py
core/agent.py
core/router.py
core/workflows.py
```

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_demo.py --backend local
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type minute.ready --backend local --llm-provider scripted_debug --max-iterations 6
```

预期：`minute.ready` 能看到 M4 artifacts、pending action items、M4 工具和相关知识字段；未开启 `--allow-write` 时不产生写副作用。

### Step 4：合并 storage 和 policy

修改：

```text
core/storage.py
core/policy.py
adapters/feishu_tools.py
```

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_policy_demo.py --scenario missing_task_fields
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_storage_risk_notifications tests.test_risk_scan_workflow
```

预期：

- 未人工确认的任务创建进入 `needs_confirmation`。
- 风险提醒空风险、全降噪仍会被拦截。
- `task_mappings` 旧表能自动补列。
- M5 `risk_notifications` 不受 M4 storage 扩展影响。

### Step 5：引入 M4 卡片回调和 pending registry

新增：

```text
core/confirmation_commands.py
core/card_callback.py
tests/test_post_meeting_card_callback.py
scripts/post_meeting_card_callback_server.py
scripts/post_meeting_card_callback_ws.py
scripts/post_meeting_confirmation_watcher.py
scripts/post_meeting_confirmation_event_watcher.py
```

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_card_callback
```

预期：

- 待确认卡包含输入框和按钮。
- 修改字段会写回 pending registry。
- 确认创建会设置 human confirmation、走 ToolRegistry、走 AgentPolicy、写 task_mappings。
- 重复点击会被状态机拦截。

### Step 6：改造 SDK 长连接入口与 HTTP fallback

新增或修改：

```text
scripts/feishu_event_sdk_server.py
scripts/feishu_event_server.py
scripts/setup_lark_oapi_venv.py
scripts/setup_card_action_trigger_event.py
```

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile adapters/feishu_callback_payloads.py core/feishu_callback_dispatcher.py scripts/feishu_event_server.py
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --dry-run --log-level debug
```

### Step 7：合并 M5 与 M4 的端到端回归

执行：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_rag_query tests.test_post_meeting_card_callback
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_risk_scan tests.test_risk_scan_card tests.test_storage_risk_notifications tests.test_risk_scan_workflow
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type minute.ready --backend local --llm-provider scripted_debug --max-iterations 8
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type risk.scan.tick --backend local --llm-provider scripted_debug --max-iterations 3 --show-full
```

### Step 8：引入 daemon 和真实联调脚本

最后引入：

```text
scripts/meetflow_daemon.py
scripts/feishu_event_sdk_server.py
scripts/post_meeting_live_test.py
scripts/post_meeting_agent_live_test.py
scripts/post_meeting_button_flow_live_test.py
scripts/card_preview_demo.py
scripts/card_send_live.py
scripts/live_card_update_probe.py
scripts/live_environment_watch.py
scripts/rag_add_document_live.py
scripts/setup_card_action_trigger_event.py
scripts/setup_lark_oapi_venv.py
scripts/sync_lark_cli_config.py
```

这些脚本接入真实飞书能力，必须逐个检查：

- 是否默认只读。
- 真实写入是否要求 `--allow-write`。
- 是否只打印配置存在性、模型名、过期时间等非敏感信息。
- 是否会默认发送到测试群，而非生产群。
- 是否明确区分正式 SDK 长连接入口、HTTP fallback 和观察台脚本。

## 8. 风险点与处理策略

### 风险 1：公共文件整文件覆盖导致 M5 丢失

表现：`RiskScanWorkflow.post_process_result()`、`risk_notifications` 或风险 policy 消失。

处理：所有公共文件按 6.x 节人工合并；每合并一个公共文件，立即运行对应 M5 单测。

### 风险 2：任务创建策略过松或过严

表现：主链路自动建任务，或卡片确认后仍被 policy 拦截。

处理：采用“主链路必须待确认，确认入口设置 human_confirmation”的策略。卡片回调和 watcher 构造 `WorkflowContext` 时必须写入：

```python
raw_context={
    "human_confirmation": {
        "confirmed": True,
        "action": "confirm_create_task",
    }
}
```

### 风险 3：`im.send_card` schema 回退

表现：M5 风险卡片或 M4 完整卡片无法直接发送，只能 fallback 成普通卡。

处理：保留当前主仓库的 `card` 参数和风险统计字段，同时引入协作者的 `card_delivery` / `fallback_reason` 回传。

### 风险 4：pending registry 成为敏感数据聚集点

表现：`storage/post_meeting_pending_actions.json` 保存过多原始纪要或人员信息。

处理：pending registry 只保存待确认任务必要字段、证据片段和消息绑定 ID；不保存完整 token、secret、API key 或完整妙记正文。

### 风险 5：daemon 与 Agent 主链路边界不清

表现：daemon 直接创建任务或发消息，绕过 policy。

处理：daemon 只生成 `AgentInput` 或调用已有脚本入口；真实写副作用仍通过 `MeetFlowAgent`、`ToolRegistry`、`AgentPolicy`。

### 风险 6：M3 文档和代码版本错位

表现：协作者文档声称 M3 完成了后台 daemon 或 RAG 事件刷新，但当前主仓库的实际实现不同。

处理：M3 相关文档按当前代码能力校准。文档只能写“已合入并验证”的能力，未合入的 daemon/event subscription 写入后续计划。

### 风险 7：SDK 长连接和 HTTP 回调各自走不同业务逻辑

表现：SDK 点击会后确认按钮能创建任务，但 HTTP fallback 不行；或 HTTP 会前刷新能触发 Agent，但 SDK 不行。

处理：两种入口都必须调用 `FeishuCallbackDispatcher`。入口层只负责收包、验签/建连、序列化响应，不包含 M3/M4 业务判断。

### 风险 8：`lark-oapi` 依赖污染主环境

表现：安装 SDK 后影响 ChromaDB、protobuf、sentence-transformers 或现有测试。

处理：保留 `scripts/setup_lark_oapi_venv.py`，用 `.venv-lark-oapi` 专门运行 SDK 长连接。主环境只需要能编译普通业务代码，不强制安装 `lark-oapi`。

### 风险 9：飞书后台事件接收方式配置不一致

表现：代码启动正常，但收不到 `card.action.trigger`。

处理：`scripts/setup_card_action_trigger_event.py` 保留为配置辅助；文档明确需要在飞书开放平台选择“长连接 / WebSocket”，添加 `card.action.trigger`，发布应用配置。HTTP fallback 则要求配置公网 HTTPS URL。

## 9. 最终验收命令

完整融合后至少执行：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests -p 'test_*.py'
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_demo.py --backend local
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug --max-iterations 3
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type minute.ready --backend local --llm-provider scripted_debug --max-iterations 8
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type risk.scan.tick --backend local --llm-provider scripted_debug --max-iterations 3 --show-full
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_policy_demo.py --scenario missing_task_fields
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_feishu_callback_dispatcher
```

真实飞书写入只在本地链路通过后执行，并且必须显式增加 `--allow-write` 或同等开关。

SDK 长连接额外验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --dry-run --log-level debug
```

HTTP fallback 额外验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/feishu_event_server.py --host 0.0.0.0 --port 8765 --agent-provider dry-run
```

## 10. 推荐提交拆分

为降低审查风险，建议拆成 7 个提交或 7 个 patch 阶段：

1. `docs: add codebase fusion plan`
2. `feat(callback): add unified feishu callback dispatcher`
3. `feat(m4): add post-meeting domain models and cards`
4. `feat(agent): wire post-meeting tools into router and workflow runner`
5. `feat(policy): merge human-confirmed task creation with risk reminder guard`
6. `feat(m4): add card callback and pending action confirmation flow`
7. `feat(feishu): add sdk websocket receiver with http fallback`

每个阶段都要更新对应 `docs/tasks/*.md` 的实现记录，写明修改文件、核心类/函数、验证命令和结果。
