# M5 风险巡检与提醒工作流详细改造计划

本文档基于 `docs/tasks/m5-risk-scan.md`、`docs/tasks/m5-risk-scan-overview.md` 和当前代码实现，给出 M5 风险巡检工作流的详细落地计划。

当前目标不是一次性做成复杂的项目管理系统，而是先把“读取任务 -> 识别风险 -> 降噪 -> 生成卡片 -> 受控提醒”这条链路跑通，并且保持与 M4 会后任务落地工作流可并行、低冲突。

## 1. 当前项目状态判断

M5 不是从零开始。当前仓库已经具备以下基础：

- `core/router.py`：已支持 `risk.scan.tick -> risk_scan`，默认工具包含 `tasks.list_my_tasks`、`calendar.list_events`、`im.send_card`。
- `core/workflows.py`：已存在 `RiskScanWorkflow` 和 `build_risk_scan_plan_draft()`，当前只生成骨架计划。
- `adapters/feishu_tools.py`：已注册 `tasks.list_my_tasks` 和 `im.send_card`，写工具已带 `idempotency_key`。
- `adapters/feishu_client.py`：`list_my_tasks()` 已能读取飞书任务并转换为 `ActionItem`，`ActionItem.extra` 保留 `url`、`created_at`、`updated_at`、`due`、`raw_payload` 等字段。
- `core/policy.py`：风险提醒发送会进入 `AgentPolicy._authorize_risk_reminder()`；写操作必须显式 `allow_write`，且必须具备幂等键。
- `core/storage.py`：已有 `idempotency_keys` 表，可用于首版提醒降噪；已有 `task_mappings` 表，可在 M4 完成后补充 ActionItem 与飞书任务关系。
- `config/settings.example.json`：已有 `risk_rules.stale_update_days`、`risk_rules.due_soon_hours`、`risk_rules.max_reminders_per_day`。

当前缺口：

- 没有 `core/risk_scan.py`。
- 没有风险规则纯函数。
- 没有任务状态归一化模型。
- 没有风险卡片模板。
- 没有 M5 本地 demo。
- 没有风险提醒记录或细粒度降噪表。
- `RiskScanWorkflow` 尚未接入确定性风险扫描产物。

## 2. 第一版目标

M5 第一版要实现：

```text
本地/真实任务列表
  -> 任务状态归一化
  -> 风险规则扫描
  -> 降噪判断
  -> 风险提醒卡片 payload
  -> dry-run 预览或 allow-write 发送
```

第一版必须满足：

- 能用 mock 任务跑完整扫描。
- 至少识别两类风险：`overdue`、`stale_update`。
- 推荐同时实现：`due_soon`、`missing_owner`。
- 能生成结构化风险结果。
- 能生成飞书卡片 payload。
- 默认不发送真实消息。
- 真实发送必须显式 `--allow-write`，并通过 `AgentPolicy`。
- 同一任务同一风险在降噪窗口内不重复提醒。

第一版不强求：

- 多次会议重复提及仍未关闭。
- 复杂项目维度聚合。
- 任务评论/动态读取。
- 后台 scheduler 常驻进程。
- 与 M4 的 ActionItem 证据链完整关联。

## 3. 建议新增文件

第一批新增：

```text
core/risk_scan.py
cards/risk_scan.py
scripts/risk_scan_demo.py
tests/test_risk_scan.py
```

第二批可选新增：

```text
tests/test_risk_scan_card.py
tests/test_risk_scan_workflow.py
```

第三批增强时再考虑：

```text
scripts/risk_scan_live_test.py
```

## 4. 建议修改文件

第一批最小修改：

```text
core/__init__.py
core/workflows.py
cards/__init__.py
docs/tasks/m5-risk-scan.md
docs/tasks/m5-risk-scan-overview.md
tasks.md
```

第二批接入真实发送时可能修改：

```text
adapters/feishu_tools.py
core/storage.py
core/policy.py
```

注意：

- 不建议第一批大改 `core/models.py`。
- M5 专属结构先放 `core/risk_scan.py`。
- `core/models.py` 中已有 `RiskAlert`，可以作为最终告警模型复用，不要重复造含义相同的公共模型。

## 5. core/risk_scan.py 设计

### 5.1 职责

`core/risk_scan.py` 负责确定性风险扫描逻辑：

- 把 `ActionItem` 或飞书任务 raw payload 归一为 `TaskSnapshot`。
- 按配置执行风险规则。
- 生成 `RiskRuleResult`。
- 聚合为 `RiskScanResult`。
- 做首版提醒降噪判断。
- 生成可传给卡片层的摘要结构。

它不负责：

- 直接调用飞书 API。
- 直接发送消息。
- 直接绕过 `AgentPolicy`。
- 做 LLM 推理。

### 5.2 建议模型

```python
@dataclass(slots=True)
class TaskSnapshot(BaseModel):
    task_id: str
    title: str
    status: str = "todo"
    owner: str = ""
    due_timestamp_ms: str = ""
    updated_at: str = ""
    completed_at: str = ""
    url: str = ""
    source: str = "feishu_task"
    raw_payload: dict[str, Any] = field(default_factory=dict)
```

```python
@dataclass(slots=True)
class RiskRuleResult(BaseModel):
    risk_type: str
    severity: str
    reason: str
    suggestion: str
    task: TaskSnapshot
    dedupe_key: str
    evidence: dict[str, Any] = field(default_factory=dict)
```

建议 `risk_type`：

```text
overdue
due_soon
stale_update
missing_owner
```

建议 `severity`：

```text
high
medium
low
```

```python
@dataclass(slots=True)
class RiskScanResult(BaseModel):
    scanned_count: int
    risk_count: int
    risks: list[RiskRuleResult] = field(default_factory=list)
    skipped_count: int = 0
    generated_at: int = 0
    summary: str = ""
```

```python
@dataclass(slots=True)
class RiskNotificationDecision(BaseModel):
    should_notify: bool
    reason: str
    notify_risks: list[RiskRuleResult] = field(default_factory=list)
    suppressed_risks: list[RiskRuleResult] = field(default_factory=list)
    idempotency_key: str = ""
```

### 5.3 建议核心函数

```python
def task_snapshot_from_action_item(item: ActionItem) -> TaskSnapshot:
    """把当前项目已有 ActionItem 转成风险扫描任务快照。"""
```

```python
def normalize_task_snapshots(items: list[ActionItem | dict[str, Any]]) -> list[TaskSnapshot]:
    """兼容 ActionItem 和 raw dict，统一生成任务快照。"""
```

```python
def scan_task_risks(
    task: TaskSnapshot,
    now: int,
    stale_update_days: int,
    due_soon_hours: int,
) -> list[RiskRuleResult]:
    """对单个任务执行风险规则。"""
```

```python
def scan_risks(
    tasks: list[TaskSnapshot],
    now: int,
    stale_update_days: int,
    due_soon_hours: int,
) -> RiskScanResult:
    """对任务列表执行风险扫描。"""
```

```python
def build_risk_dedupe_key(task: TaskSnapshot, risk_type: str, now: int) -> str:
    """构造同一任务同一风险的提醒降噪键。"""
```

第一版建议格式：

```text
risk_scan:{task_id}:{risk_type}:{YYYYMMDD}
```

这样可以复用现有 `idempotency_keys` 表，做到同一天不重复提醒。

```python
def decide_risk_notification(
    scan_result: RiskScanResult,
    storage: MeetFlowStorage | None,
    max_reminders_per_day: int,
) -> RiskNotificationDecision:
    """根据幂等记录和每日上限决定是否提醒。"""
```

第一版可以简单做：

- 按 severity 排序。
- 取前 N 条风险。
- 如果某个 `dedupe_key` 已存在，则 suppress。
- 如果无可提醒风险，则 `should_notify=False`。

## 6. 风险规则细节

### 6.1 completed 判断

建议函数：

```python
def is_task_completed(task: TaskSnapshot) -> bool:
```

可识别：

- `status in {"done", "completed", "complete"}`
- `completed_at` 非空
- raw payload 中明确完成状态

### 6.2 overdue

条件：

```text
due_timestamp_ms < now
and task not completed
```

severity：

- overdue 超过 24 小时：`high`
- overdue 未超过 24 小时：`medium`

### 6.3 due_soon

条件：

```text
0 <= due_timestamp_ms - now <= due_soon_hours
and task not completed
```

severity：

```text
medium
```

### 6.4 stale_update

条件：

```text
now - updated_at >= stale_update_days
and task not completed
```

注意：

- 飞书 `updated_at` 可能是秒，也可能是毫秒字符串，需要兼容解析。
- 如果没有 `updated_at`，第一版不要命中 stale_update，避免误报。

### 6.5 missing_owner

条件：

```text
owner 为空
and task not completed
```

severity：

```text
high
```

## 7. cards/risk_scan.py 设计

### 7.1 职责

专门生成风险巡检卡片，不复用通用通知卡片。

风险卡片应该聚合展示，不要一个风险一张卡，避免噪声。

### 7.2 建议函数

```python
def build_risk_scan_card(decision: RiskNotificationDecision) -> dict[str, Any]:
    """构造飞书风险巡检 interactive card。"""
```

### 7.3 卡片内容

卡片标题：

```text
MeetFlow 风险巡检提醒
```

卡片结构：

```text
概览：
- 扫描任务数
- 命中风险数
- 本次提醒数
- 被降噪跳过数

高风险：
1. 任务名
   风险原因
   截止时间 / 负责人 / 建议动作 / 链接

中风险：
...
```

每条风险至少包含：

- 任务名
- 风险类型
- 风险原因
- 截止时间
- 负责人
- 建议动作
- 任务链接

### 7.4 卡片按钮

第一版可先不做按钮。

第二版可以加：

- `查看任务`
- `稍后提醒`
- `标记已知`

这些按钮会引入新的卡片回调动作，应与当前 `core/card_actions.py` 对齐。

## 8. scripts/risk_scan_demo.py 设计

### 8.1 目标

提供一个本地可复现的 M5 演示入口。

命令：

```bash
python3 scripts/risk_scan_demo.py --backend local --show-card
```

预期输出：

- mock 任务列表。
- 风险扫描结果。
- 降噪决策。
- 风险卡片 JSON。
- 默认不发送飞书消息。

### 8.2 参数建议

```text
--backend local|feishu
--allow-write
--chat-id
--identity user|tenant
--completed false|true|all
--stale-update-days
--due-soon-hours
--max-reminders
--show-card
```

第一版建议只做：

```text
--backend local
--allow-write
--show-card
```

### 8.3 local mock 数据

至少准备 5 条任务：

1. 已逾期未完成：命中 `overdue`。
2. 3 天未更新：命中 `stale_update`。
3. 24 小时内截止：命中 `due_soon`。
4. 无负责人：命中 `missing_owner`。
5. 已完成任务：不命中。

## 9. RiskScanWorkflow 接入计划

### 9.1 第一阶段：只写入确定性上下文

修改 `RiskScanWorkflow.prepare_context()`：

```text
context.raw_context["risk_scan_plan"]
context.raw_context["risk_rule_settings"]
```

如果输入 payload 已带 mock 或上游任务：

```text
context.raw_context["risk_scan_result"]
context.raw_context["risk_notification_decision"]
context.raw_context["risk_card_payload"]
```

第一阶段不要强依赖 LLM 工具结果。

### 9.2 第二阶段：从工具结果做确定性 post-process

当前 Agent 工具链是：

```text
tasks.list_my_tasks -> LLM -> im.send_card
```

问题是：LLM 工具调用返回后，确定性 `RiskScanWorkflow` 不容易截获工具结果再运行规则。

因此建议后续给 `WorkflowRunner` 增加钩子：

```python
def post_process_result(self, result: AgentRunResult, context: WorkflowContext) -> None:
```

在 `loop.run()` 后调用它。这样 M5 能从 `result.loop_state.tool_results` 中读取 `tasks.list_my_tasks` 结果，再用确定性规则生成风险扫描结果。

### 9.3 第三阶段：Agent 发送风险卡片

当 `risk_notification_decision.should_notify=True`：

- 由确定性代码生成风险卡片 payload。
- Agent 或 Runner 请求 `im.send_card`。
- 必须包含 `idempotency_key`。
- 必须 `allow_write=True`。
- 必须经过 `AgentPolicy`。

第一版建议先不要让 LLM 自己拼风险卡片 JSON，而是传：

```text
title
summary
facts
idempotency_key
```

或后续扩展 `im.send_card` 支持 `card` 直传稳定模板。

## 10. 降噪与存储计划

### 10.1 第一版：复用 idempotency_keys

降噪键：

```text
risk_scan:{task_id}:{risk_type}:{YYYYMMDD}
```

优点：

- 不需要改表。
- 已有 `storage.is_idempotency_key_processed()`。
- 已有 `storage.record_idempotency_key()`。
- 与 `AgentPolicy` 写工具幂等逻辑一致。

限制：

- 只能粗略做到当天不重复。
- 不方便统计历史提醒次数和状态。

### 10.2 第二版：新增 risk_notifications 表

建议字段：

```text
id
risk_key
task_id
risk_type
severity
status
trace_id
notified_at
suppressed_until
recipient
summary
payload_json
created_at
updated_at
```

第二版再做，不阻塞第一版。

## 11. 与 M4 的衔接计划

第一版 M5 不依赖 M4。

M4 完成后，M5 再增强：

- 读取 `task_mappings`。
- 从 `item_id` 找到原始 ActionItem。
- 在风险卡片中补充会议来源。
- 在风险原因中标注“来自哪次会议/妙记”。
- 支持“多次会议重复提及仍未关闭”。

当前 `core/storage.py` 已有：

```python
save_task_mapping(...)
get_task_mapping(...)
```

但它现在只能按 `item_id` 查。M5 后续可能需要新增：

```python
get_task_mapping_by_task_id(task_id: str)
```

这一步放到 M4 与 M5 对接阶段。

## 12. 与当前卡片按钮交互的衔接

当前已实现飞书卡片按钮回调 MVP：

- `core/card_actions.py`
- `scripts/feishu_event_server.py`
- `CardActionRouter`

M5 第二版风险卡片可以复用这套机制，新增动作：

```text
risk_acknowledge
risk_snooze
risk_view_task
```

但第一版风险卡片建议先只展示，不加按钮，避免同时引入过多交互状态。

## 13. 结构化日志计划

建议新增事件：

```text
risk_scan_started
risk_scan_finished
risk_rule_matched
risk_notification_decision
risk_notification_sent
risk_notification_suppressed
```

关键字段：

- `trace_id`
- `project_id`
- `task_id`
- `risk_type`
- `severity`
- `dedupe_key`
- `should_notify`
- `reason`
- `duration_ms`

注意：

- `task_id`、`owner`、`open_id` 需要经过现有 observability 脱敏。
- 不记录完整飞书 raw payload。

## 14. 测试计划

### 14.1 单元测试

新增：

```text
tests/test_risk_scan.py
```

覆盖：

- 逾期未完成命中 `overdue`。
- 临近截止命中 `due_soon`。
- 超过 N 天未更新命中 `stale_update`。
- 无负责人命中 `missing_owner`。
- 已完成任务不命中。
- 秒/毫秒时间戳都能解析。
- 降噪键稳定。
- 已处理幂等键会 suppress。

### 14.2 Demo 测试

命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py --backend local --show-card
```

预期：

- 打印扫描任务数。
- 打印风险数。
- 至少出现 `overdue` 和 `stale_update`。
- 打印风险卡片 JSON。
- 不发送真实飞书消息。

### 14.3 Agent 链路测试

只读：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py \
  --event-type risk.scan.tick \
  --backend local \
  --llm-provider scripted_debug \
  --max-iterations 3
```

真实读取任务：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/tasks_live_test.py --completed all
```

真实写提醒必须后置，并且只发测试群：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py \
  --event-type risk.scan.tick \
  --backend feishu \
  --llm-provider scripted_debug \
  --allow-write \
  --max-iterations 3
```

## 15. 分阶段实施计划

### 阶段 A：纯规则引擎

新增：

```text
core/risk_scan.py
tests/test_risk_scan.py
```

完成：

- `TaskSnapshot`
- `RiskRuleResult`
- `RiskScanResult`
- `RiskNotificationDecision`
- `normalize_task_snapshots`
- `scan_task_risks`
- `scan_risks`
- `build_risk_dedupe_key`

### 阶段 B：风险卡片模板

新增：

```text
cards/risk_scan.py
```

修改：

```text
cards/__init__.py
```

完成：

- `build_risk_scan_card`
- `render_risk_summary_markdown`
- `render_risk_items_markdown`

### 阶段 C：本地 demo

新增：

```text
scripts/risk_scan_demo.py
```

完成：

- mock 任务。
- 扫描。
- 降噪。
- 卡片预览。

### 阶段 D：接入 RiskScanWorkflow

修改：

```text
core/workflows.py
core/__init__.py
```

完成：

- `RiskScanWorkflow.prepare_context()` 写入风险扫描 settings。
- 如 payload 带 tasks，则直接生成 `risk_scan_result`。
- 后续增加 result post-process 钩子，从 `tasks.list_my_tasks` 工具结果生成确定性风险结果。

### 阶段 E：降噪增强

第一版：

- 复用 `idempotency_keys`。

第二版：

- 新增 `risk_notifications` 表。

### 阶段 F：真实飞书联调

步骤：

1. 真实读取任务：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/tasks_live_test.py --completed all
```

2. 用真实任务构造 `TaskSnapshot`。
3. dry-run 打印风险卡片。
4. 最后显式 `--allow-write` 发测试群。

## 16. 推荐优先级

第一天优先：

1. `core/risk_scan.py`
2. `tests/test_risk_scan.py`
3. `cards/risk_scan.py`
4. `scripts/risk_scan_demo.py`

第二天再做：

1. `RiskScanWorkflow` 接入。
2. Agent Demo 链路。
3. 真实飞书任务读取联调。
4. 降噪增强。

不要一开始就做 scheduler 常驻进程。先用脚本模拟定时：

```bash
python3 scripts/risk_scan_demo.py --backend local
```

或：

```bash
python3 scripts/agent_demo.py --event-type risk.scan.tick
```

## 17. 风险与注意事项

- 不要让风险巡检直接绕过 `AgentPolicy` 发消息。
- 不要让 LLM 自己决定是否重复提醒，降噪必须由确定性代码或 storage 判断。
- 不要把飞书任务 raw payload 完整写进结构化日志。
- 不要默认扫描全部企业任务，第一版只扫描当前用户任务或指定测试任务。
- 不要和 M4 同时大改 `core/models.py`，避免冲突。
- 如果真实飞书任务字段不稳定，优先在 `TaskSnapshot` 层做兼容，不要把兼容逻辑散落在规则函数里。

## 18. 第一版完成后的验收清单

- `python -m unittest discover -s tests -p 'test_*.py'` 通过。
- `scripts/risk_scan_demo.py --backend local --show-card` 能稳定输出风险卡片。
- mock 数据至少命中 `overdue` 和 `stale_update`。
- 风险卡片包含任务名、风险原因、截止时间、负责人、建议动作。
- 默认不会真实发飞书消息。
- 真实发送必须显式 `--allow-write`。
- 风险提醒带稳定幂等键。
- `tasks.md` 和 `docs/tasks/m5-risk-scan.md` 已同步实现记录。
