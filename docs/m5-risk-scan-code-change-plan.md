# M5 任务风险提醒第二版代码改造方案

本文档是 `docs/m5-risk-scan-implementation-plan.md` 的第二版施工方案，目标是把 M5 从“已有骨架和总体计划”推进到“可以按补丁顺序实现”的代码改造清单。

第二版的核心链路：

```text
飞书/本地任务列表
  -> 任务快照归一化
  -> 确定性风险规则扫描
  -> 存储层降噪判断
  -> 风险卡片渲染
  -> dry-run 预览或经过 AgentPolicy 的受控发送
  -> 结构化日志和测试验证
```

## 1. 当前代码事实

- `core/router.py` 已能把 `risk.scan.tick` 路由为 `risk_scan`。
- `core/workflows.py` 已有 `RiskScanWorkflow`，但当前只写入 `risk_scan_plan`，没有读取工具结果并生成风险扫描产物。
- `adapters/feishu_tools.py` 已注册 `tasks.list_my_tasks` 和 `im.send_card`，风险扫描不需要直接绕过工具体系。
- `adapters/feishu_client.py` 的 `list_my_tasks()` 已把飞书任务转换为 `ActionItem`，其中 `extra` 保留了 `task_id`、`guid`、`url`、`created_at`、`updated_at`、`completed_at`、`due`、`raw_payload` 等风险判断所需字段。
- `core/models.py` 已有 `ActionItem` 和 `RiskAlert`，M5 专属中间结构不建议继续塞进公共模型文件，优先放在 `core/risk_scan.py`。
- `core/storage.py` 已有 `idempotency_keys` 和 `task_mappings`，但没有风险提醒历史表。
- `core/policy.py` 已对 `risk_scan + send_message` 做特殊检查，目前只要求有幂等键。
- `scripts/agent_demo.py` 已支持 `risk.scan.tick`，但本地 mock 任务过于简单，不能触发真实风险规则。
- `config/loader.py` 已有 `RiskRuleSettings`，配置项为 `stale_update_days`、`due_soon_hours`、`max_reminders_per_day`。

## 2. 第二版目标

M5 第二版要比第一版多做三件事：

1. 不只生成风险扫描结果，还要把提醒历史落到 `risk_notifications` 表，支持后续审计和更细粒度降噪。
2. `RiskScanWorkflow` 要接入确定性 post-process，从 `tasks.list_my_tasks` 工具结果中生成风险结果，而不是只依赖 LLM 自己总结。
3. 风险提醒卡片要复用当前飞书卡片交互能力，为后续 `已知悉`、`稍后提醒`、`查看任务` 按钮预留 action。

第二版仍然不做：

- 常驻 scheduler 服务。
- 企业全量任务扫描。
- 多次会议重复提及仍未关闭的复杂证据链。
- 让 LLM 自己拼完整飞书卡片 JSON 并绕过稳定模板。

## 3. 目标架构

### 3.1 脚本直跑链路

```text
scripts/risk_scan_demo.py
  -> local mock tasks 或 FeishuClient.list_my_tasks()
  -> core.risk_scan.normalize_task_snapshots()
  -> core.risk_scan.scan_risks()
  -> core.risk_scan.decide_risk_notification()
  -> cards.risk_scan.build_risk_scan_card()
  -> dry-run 打印
  -> --allow-write 时调用 client.send_card_message()
```

这个链路用于本地开发和真实飞书联调，默认不发送消息。

### 3.2 Agent 工作流链路

```text
AgentInput(event_type=risk.scan.tick)
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> RiskScanWorkflow.prepare_context()
  -> MeetFlowAgentLoop 调用 tasks.list_my_tasks
  -> RiskScanWorkflow.post_process_result()
  -> scan_risks + decide_risk_notification + build_risk_scan_card
  -> result.payload["risk_scan"]
  -> 后续由 Agent/Runner 受控请求 im.send_card
```

这个链路保证：LLM 可以解释和选择工具，但风险识别、降噪、卡片数据结构由确定性代码控制。

## 4. 新增文件

### 4.1 `core/risk_scan.py`

职责：

- 归一化任务快照。
- 执行风险规则。
- 生成扫描结果。
- 生成降噪决策。
- 转换为 `RiskAlert`。
- 只处理业务判断，不直接调用飞书 API。

建议数据结构：

```python
@dataclass(slots=True)
class TaskSnapshot(BaseModel):
    task_id: str
    title: str
    status: str = "todo"
    owner: str = ""
    due_timestamp: int = 0
    updated_at: int = 0
    completed_at: int = 0
    url: str = ""
    source: str = "task"
    raw_payload: dict[str, Any] = field(default_factory=dict)
```

```python
@dataclass(slots=True)
class RiskRuleResult(BaseModel):
    risk_id: str
    task_id: str
    risk_type: str
    severity: str
    reason: str
    suggestion: str
    task: TaskSnapshot
    dedupe_key: str
    evidence: dict[str, Any] = field(default_factory=dict)
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
    notification_keys: list[str] = field(default_factory=list)
```

建议核心函数：

```python
def parse_task_timestamp(value: Any) -> int:
    """兼容秒、毫秒、字符串和飞书 due 对象，统一返回秒级时间戳。"""
```

```python
def is_task_completed(task: TaskSnapshot) -> bool:
    """判断任务是否已经完成，避免已完成任务继续触发风险。"""
```

```python
def task_snapshot_from_action_item(item: ActionItem) -> TaskSnapshot:
    """把飞书任务工具返回的 ActionItem 归一为风险扫描快照。"""
```

```python
def task_snapshot_from_dict(data: dict[str, Any]) -> TaskSnapshot:
    """兼容本地 mock 和工具序列化后的 dict。"""
```

```python
def normalize_task_snapshots(items: list[ActionItem | dict[str, Any]]) -> list[TaskSnapshot]:
    """把多来源任务列表统一成 TaskSnapshot。"""
```

```python
def scan_task_risks(
    task: TaskSnapshot,
    now: int,
    stale_update_days: int,
    due_soon_hours: int,
) -> list[RiskRuleResult]:
    """对单个任务运行风险规则。"""
```

```python
def scan_risks(
    tasks: list[TaskSnapshot],
    now: int,
    stale_update_days: int,
    due_soon_hours: int,
) -> RiskScanResult:
    """对任务列表运行风险扫描，并按严重程度排序。"""
```

```python
def build_risk_dedupe_key(task_id: str, risk_type: str, now: int) -> str:
    """构造同一任务同一风险当天只提醒一次的键。"""
```

```python
def decide_risk_notification(
    scan_result: RiskScanResult,
    storage: MeetFlowStorage | None,
    max_reminders_per_day: int,
    now: int,
) -> RiskNotificationDecision:
    """根据风险结果、每日上限和历史提醒记录决定是否提醒。"""
```

风险类型：

- `overdue`：任务已过截止时间且未完成。
- `due_soon`：任务将在配置窗口内截止且未完成。
- `stale_update`：任务超过配置天数未更新且未完成。
- `missing_owner`：任务没有负责人且未完成。

严重程度：

- `high`：逾期超过 24 小时、无负责人。
- `medium`：当天逾期、即将截止、长时间未更新。
- `low`：后续保留给弱提醒。

### 4.2 `cards/risk_scan.py`

职责：

- 只负责卡片 payload 组装。
- 不做风险判断。
- 不调用飞书 API。

建议函数：

```python
def build_risk_scan_card(
    decision: RiskNotificationDecision,
    scan_result: RiskScanResult,
) -> dict[str, Any]:
    """构造任务风险提醒飞书卡片。"""
```

```python
def render_risk_summary(decision: RiskNotificationDecision, scan_result: RiskScanResult) -> str:
    """生成卡片概览文本。"""
```

```python
def render_risk_item(risk: RiskRuleResult) -> dict[str, Any]:
    """把单条风险转换成卡片模块。"""
```

卡片内容必须包含：

- 扫描任务数。
- 命中风险数。
- 本次提醒风险数。
- 被降噪风险数。
- 任务标题。
- 风险原因。
- 截止时间。
- 负责人。
- 建议动作。
- 任务链接。

第二版可以预留按钮，但建议先只开放无状态按钮：

- `查看任务`：链接按钮，直接打开任务 URL。

有状态按钮放到下一步：

- `risk_acknowledge`
- `risk_snooze`
- `risk_mark_resolved`

这些动作后续接入 `core/card_actions.py`。

### 4.3 `scripts/risk_scan_demo.py`

职责：

- 提供 M5 独立演示入口。
- 支持本地 mock 和真实飞书读取。
- 默认 dry-run，只打印结果和卡片。

建议参数：

```text
--backend local|feishu
--show-card
--allow-write
--chat-id
--identity user|tenant
--completed false|true|all
--stale-update-days
--due-soon-hours
--max-reminders
```

本地 mock 至少准备 5 条任务：

1. 已逾期未完成，命中 `overdue`。
2. 三天以上未更新，命中 `stale_update`。
3. 24 小时内截止，命中 `due_soon`。
4. 无负责人，命中 `missing_owner`。
5. 已完成任务，不命中。

真实发送规则：

- `--backend feishu` 只读取任务，不发送消息。
- `--allow-write` 才能发送卡片。
- 发送目标优先使用 `--chat-id`，否则使用 `settings.feishu.default_chat_id`。
- 发送身份使用 `tenant`，因为机器人群消息一般需要应用身份。

## 5. 修改文件

### 5.1 `core/storage.py`

新增表 `risk_notifications`：

```sql
CREATE TABLE IF NOT EXISTS risk_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_key TEXT NOT NULL,
    task_id TEXT NOT NULL,
    risk_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    notified_at INTEGER NOT NULL,
    suppressed_until INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
)
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_risk_notifications_key_time
ON risk_notifications (risk_key, notified_at)
```

新增方法：

```python
def record_risk_notification(
    self,
    risk_key: str,
    task_id: str,
    risk_type: str,
    severity: str,
    status: str,
    trace_id: str,
    recipient: str,
    summary: str,
    payload: dict[str, Any],
    notified_at: int,
    suppressed_until: int,
) -> None:
    """记录一次风险提醒或降噪决策。"""
```

```python
def get_latest_risk_notification(self, risk_key: str) -> dict[str, Any] | None:
    """读取某个风险键最近一次提醒记录。"""
```

```python
def has_recent_risk_notification(self, risk_key: str, now: int) -> bool:
    """判断某个风险是否仍在降噪窗口内。"""
```

第二版仍然可以同步写 `idempotency_keys`，保持与 `AgentPolicy` 的写操作幂等一致。

### 5.2 `core/workflows.py`

给 `WorkflowRunner` 增加后处理钩子：

```python
def post_process_result(
    self,
    result: AgentRunResult,
    context: WorkflowContext,
    decision: AgentDecision,
) -> None:
    """Agent Loop 结束后的确定性业务后处理。"""
```

`WorkflowRunner.run()` 调整顺序：

```text
prepare_context
agent_loop
post_process_result
validate_output
persist_and_audit
```

`RiskScanWorkflow.post_process_result()` 负责：

1. 从 `result.loop_state.tool_results` 找到 `tool_name == "tasks.list_my_tasks"` 且 `status == "success"` 的结果。
2. 从 `tool_result.data["items"]` 取任务列表。
3. 调用 `normalize_task_snapshots()`。
4. 调用 `scan_risks()`。
5. 调用 `decide_risk_notification()`。
6. 调用 `build_risk_scan_card()`。
7. 写入：

```python
result.payload["risk_scan"] = {
    "settings": ...,
    "scan_result": scan_result.to_dict(),
    "notification_decision": decision.to_dict(),
    "card_payload": card_payload,
}
```

`RiskScanWorkflow.validate_output()` 增强：

- 如果任务工具成功但没有 `risk_scan.scan_result`，报错。
- 如果 `risk_count > 0` 但没有 `notification_decision`，报错。
- 如果 `should_notify=True` 但没有 `card_payload`，报错。

注意：`post_process_result()` 不应直接发送消息。发送仍要经过工具和 `AgentPolicy`。

### 5.3 `scripts/agent_demo.py`

改造本地 mock：

- `tasks.list_my_tasks` 返回带 `item_id`、`title`、`owner`、`due_date`、`status`、`extra.updated_at`、`extra.url` 的任务。
- `ScriptedDebugProvider` 遇到 `risk.scan.tick` 且有 `tasks_list_my_tasks` 时，优先调用任务读取工具。
- `im.send_card` 本地 mock 支持 `facts` 和 `card` 参数，方便验证卡片 payload 不丢字段。

目标命令：

```bash
python3 scripts/agent_demo.py \
  --event-type risk.scan.tick \
  --backend local \
  --llm-provider scripted_debug \
  --max-iterations 3 \
  --show-full
```

预期：

- `loop_state.tool_results` 中有 `tasks.list_my_tasks`。
- `payload.risk_scan.scan_result.risk_count >= 2`。
- `payload.risk_scan.card_payload` 存在。

### 5.4 `adapters/feishu_tools.py`

当前 `send_card_with_fallback()` 已支持 `card` 参数，但工具 schema 没有显式暴露 `card`。

建议第二版修改：

- 在 `im.send_card` 参数 schema 中增加 `card`。
- 说明 `card` 必须是完整飞书 interactive card JSON。
- 保留 `title/summary/facts` 兜底。

这样风险卡片可以走统一工具，而不是脚本私自调用客户端。

### 5.5 `core/policy.py`

增强 `_authorize_risk_reminder()`：

- 继续要求 `idempotency_key`。
- 如果参数里有 `risk_count`，必须大于 0。
- 如果参数里有 `suppressed_count` 且 `notify_count == 0`，阻止发送。
- metadata 记录 `risk_count`、`notify_count`，便于结构化日志排查。

建议不在 Policy 中重新跑风险规则。Policy 只检查安全边界和必要字段，不做业务扫描。

### 5.6 `core/__init__.py` 与 `cards/__init__.py`

导出新增能力：

- `TaskSnapshot`
- `RiskRuleResult`
- `RiskScanResult`
- `RiskNotificationDecision`
- `scan_risks`
- `build_risk_scan_card`

保持导出最小化，不要把所有内部辅助函数暴露出来。

### 5.7 `config/settings.example.json`

当前 `risk_rules` 已有三项。第二版建议暂不新增配置，避免用户配置负担。

如果确实需要更细粒度降噪，可新增：

```json
"risk_rules": {
  "stale_update_days": 3,
  "due_soon_hours": 24,
  "max_reminders_per_day": 1,
  "dedupe_window_hours": 24
}
```

但这会要求同步修改 `RiskRuleSettings` 和本地配置模板。建议放到第二轮增强，不作为 M5 第二版必需项。

## 6. 数据契约

### 6.1 任务快照输入

`tasks.list_my_tasks` 工具序列化后的结果形态：

```json
{
  "items": [
    {
      "item_id": "task_xxx",
      "title": "完成方案评审",
      "owner": "张三",
      "due_date": "1777632000",
      "status": "todo",
      "extra": {
        "task_id": "task_xxx",
        "url": "https://...",
        "updated_at": "1777200000",
        "completed_at": "",
        "due": {}
      }
    }
  ],
  "count": 1
}
```

`TaskSnapshot` 归一化规则：

- `task_id` 优先取 `extra.task_id`，其次 `item_id`，最后 `guid`。
- `title` 优先取 `title`，其次 `summary`。
- `owner` 取 `owner`，如果为空尝试从 `extra.members` 提取展示名。
- `due_timestamp` 兼容 `due_date`、`due_timestamp_ms`、`extra.due.timestamp`。
- `updated_at` 兼容秒级和毫秒级字符串。
- `url` 取 `extra.url`。

### 6.2 风险结果输出

`result.payload["risk_scan"]` 建议结构：

```json
{
  "settings": {
    "stale_update_days": 3,
    "due_soon_hours": 24,
    "max_reminders_per_day": 1
  },
  "scan_result": {
    "scanned_count": 5,
    "risk_count": 4,
    "risks": []
  },
  "notification_decision": {
    "should_notify": true,
    "notify_risks": [],
    "suppressed_risks": [],
    "idempotency_key": "risk_scan:20260502"
  },
  "card_payload": {}
}
```

### 6.3 幂等键

单条风险降噪键：

```text
risk_scan:{task_id}:{risk_type}:{YYYYMMDD}
```

卡片发送幂等键：

```text
risk_scan:notification:{YYYYMMDD}:{hash_of_notify_keys}
```

这样可以区分：

- 单条风险是否今天已经提醒。
- 聚合卡片是否已经发送。

## 7. 结构化日志

建议新增事件：

- `risk_scan_started`
- `risk_rule_matched`
- `risk_notification_decision`
- `risk_notification_suppressed`
- `risk_scan_finished`

字段建议：

- `trace_id`
- `workflow_type`
- `scanned_count`
- `risk_count`
- `risk_type`
- `severity`
- `dedupe_key`
- `should_notify`
- `notify_count`
- `suppressed_count`
- `duration_ms`

注意：

- 不记录完整 `raw_payload`。
- 不记录 access token、refresh token、app secret、API key。
- `owner`、`open_id` 如进入日志，应沿用现有观测层脱敏策略。

## 8. 测试文件

### 8.1 `tests/test_risk_scan.py`

覆盖：

- 秒级时间戳解析。
- 毫秒级时间戳解析。
- 已完成任务不命中风险。
- 逾期任务命中 `overdue`。
- 即将截止命中 `due_soon`。
- 长时间未更新命中 `stale_update`。
- 无负责人命中 `missing_owner`。
- 风险结果按 severity 排序。
- 降噪键稳定。
- 已有提醒记录会 suppress。

### 8.2 `tests/test_risk_scan_card.py`

覆盖：

- 卡片 payload 是 dict。
- 卡片标题存在。
- 风险原因、负责人、截止时间、建议动作被渲染。
- 无风险时能生成“无需提醒”的预览卡片或返回空提醒说明。

### 8.3 `tests/test_storage_risk_notifications.py`

覆盖：

- 初始化会创建 `risk_notifications` 表。
- 能记录提醒。
- 能读取最近提醒。
- `suppressed_until > now` 时判定为近期提醒。

### 8.4 `tests/test_risk_scan_workflow.py`

覆盖：

- 构造带 `tasks.list_my_tasks` 工具结果的 `AgentRunResult`。
- 调用 `RiskScanWorkflow.post_process_result()` 后，`payload.risk_scan` 存在。
- 没有任务工具结果时，validate 给出 warning 而不是崩溃。

## 9. 推荐补丁顺序

### Patch 1：规则引擎

新增：

- `core/risk_scan.py`
- `tests/test_risk_scan.py`

验证：

```bash
python3 -m py_compile core/risk_scan.py tests/test_risk_scan.py
python3 -m unittest tests.test_risk_scan
```

### Patch 2：风险卡片

新增：

- `cards/risk_scan.py`
- `tests/test_risk_scan_card.py`

修改：

- `cards/__init__.py`

验证：

```bash
python3 -m py_compile cards/risk_scan.py tests/test_risk_scan_card.py
python3 -m unittest tests.test_risk_scan_card
```

### Patch 3：存储降噪

修改：

- `core/storage.py`

新增：

- `tests/test_storage_risk_notifications.py`

验证：

```bash
python3 -m py_compile core/storage.py tests/test_storage_risk_notifications.py
python3 -m unittest tests.test_storage_risk_notifications
```

### Patch 4：本地 demo

新增：

- `scripts/risk_scan_demo.py`

验证：

```bash
python3 scripts/risk_scan_demo.py --backend local --show-card
```

预期：

- 至少扫描 5 条任务。
- 至少命中 `overdue` 和 `stale_update`。
- 输出卡片 JSON。
- 不发送飞书消息。

### Patch 5：接入 WorkflowRunner

修改：

- `core/workflows.py`
- `core/__init__.py`
- `scripts/agent_demo.py`

新增：

- `tests/test_risk_scan_workflow.py`

验证：

```bash
python3 -m unittest tests.test_risk_scan_workflow
python3 scripts/agent_demo.py \
  --event-type risk.scan.tick \
  --backend local \
  --llm-provider scripted_debug \
  --max-iterations 3 \
  --show-full
```

### Patch 6：Policy 和工具发送增强

修改：

- `adapters/feishu_tools.py`
- `core/policy.py`

验证：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/agent_policy_demo.py --scenario missing_task_fields
```

### Patch 7：真实飞书只读联调

命令：

```bash
python3 scripts/tasks_live_test.py --completed all
python3 scripts/risk_scan_demo.py --backend feishu --show-card
```

预期：

- 能读取当前用户任务。
- 能输出风险扫描结果。
- 不发送消息。

### Patch 8：真实测试群发送

前提：

- `config/settings.local.json` 已配置 `feishu.default_chat_id`。
- 机器人已进测试群。
- 权限已发布生效。

命令：

```bash
python3 scripts/risk_scan_demo.py \
  --backend feishu \
  --show-card \
  --allow-write
```

预期：

- 只向测试群发送一张聚合风险卡片。
- 第二次执行同一天同风险会被降噪。

## 10. 验收标准

M5 第二版完成后，应满足：

- `python3 -m unittest discover -s tests -p 'test_*.py'` 通过。
- `scripts/risk_scan_demo.py --backend local --show-card` 可稳定输出风险卡片。
- `scripts/agent_demo.py --event-type risk.scan.tick --backend local --llm-provider scripted_debug --show-full` 的 payload 中包含 `risk_scan`。
- 至少识别 `overdue`、`due_soon`、`stale_update`、`missing_owner` 四类风险。
- 已完成任务不会触发风险。
- 同一任务同一风险同一天不会重复提醒。
- 风险提醒卡片包含任务名、风险原因、截止时间、负责人、建议动作。
- 真实发送必须显式 `--allow-write`。
- 所有风险提醒写操作仍经过 `AgentPolicy`。
- 日志中不出现完整飞书 raw payload、token、secret、API key。

## 11. 实施注意事项

- 不要让 `core/risk_scan.py` import 飞书客户端，避免业务规则和外部 API 耦合。
- 不要把所有 M5 模型都塞进 `core/models.py`，当前更适合模块内聚。
- 不要让 LLM 决定降噪，降噪必须由 storage 和确定性代码判断。
- 不要在 `RiskScanWorkflow.post_process_result()` 里直接发送消息。
- 不要默认启用真实写操作。
- 不要提交 `config/settings.local.json`、`storage/*.db`、`storage/*.jsonl` 或本地安装包。

## 12. 文档同步

完成每个 Patch 后需要同步：

- `tasks.md`：记录完成了哪些文件、核心函数、验证命令和结果。
- `docs/tasks/m5-risk-scan.md`：勾勒当前 T5.1 到 T5.6 的完成状态。
- 如改动 Agent 流程边界，需要同步 `architecture.md`。
