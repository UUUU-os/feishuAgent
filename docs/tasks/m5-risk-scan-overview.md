# M5 风险巡检与提醒工作流协作说明

这份文档面向负责 M5 的协作者，目标是说明 M5 要做什么、如何一步步实现、哪些边界不要碰，以及如何与并行开发的 M4 会后总结工作流配合。

## 1. M5 的目标

M5 要实现的是 `risk_scan` 风险巡检工作流。它不是生成会议总结，也不是创建任务；它负责定期读取任务状态，识别潜在风险，并在必要时发送低噪声提醒。

一句话理解：

```text
M5 = 任务状态读取 + 风险规则判断 + 提醒降噪 + 风险卡片推送
```

首版优先支持这些风险：

- 任务已逾期但仍未完成。
- 任务临近截止但没有明显进展。
- 任务超过配置天数未更新。
- 任务缺少负责人。
- 后续增强：多次会议重复提到但仍未关闭。

## 2. M4 与 M5 的关系

M4 和 M5 有上下游关系，但可以并行开发。

M4 负责“会后生产任务”：

```text
会议纪要 / 妙记 -> ActionItem -> 飞书任务 -> task_mappings
```

M5 负责“巡检任务风险”：

```text
飞书任务 + task_mappings + 历史提醒记录 -> RiskAlert -> 风险提醒卡片
```

因此 M5 第一版不需要等待 M4 完成。M5 可以先基于 `tasks.list_my_tasks` 返回的飞书任务做风险扫描；等 M4 完成任务创建和 `task_mappings` 写入后，M5 再利用映射关系补充“这个风险来自哪次会议、哪个 Action Item、原始证据是什么”。

并行开发时的约定：

- M4 可以改 `core/post_meeting.py`、`cards/post_meeting.py`、`scripts/post_meeting_demo.py` 等会后专属文件。
- M5 优先新增 `core/risk_scan.py`、`cards/risk_scan.py`、`scripts/risk_scan_demo.py`。
- 双方尽量不要同时大改 `core/workflows.py`、`core/router.py`、`core/models.py`、`adapters/feishu_tools.py`。
- 如果必须改公共文件，先只做最小接口注册或字段补充，并在任务文档里说明。

## 3. 当前已有基础

当前代码已经有 M5 骨架，不需要从零开始：

- `WorkflowRouter` 已支持 `risk.scan.tick -> risk_scan`。
- `RiskScanWorkflow` 已存在于 `core/workflows.py`。
- `build_risk_scan_plan_draft()` 已能生成风险巡检阶段草案。
- `risk_scan` 默认允许工具：`tasks.list_my_tasks`、`calendar.list_events`、`im.send_card`。
- `AgentPolicy` 已负责写操作安全，风险提醒卡片发送必须经过 policy 和幂等/降噪规则。

现有骨架阶段：

```text
fetch_task_status
-> apply_risk_rules
-> check_recent_notifications
-> generate_risk_alert_draft
-> notify_or_skip
```

## 4. 推荐实现顺序

### Step 1：定义 M5 数据结构

建议新增文件：

- `core/risk_scan.py`

建议先定义这些 dataclass：

- `TaskSnapshot`：统一表示一条任务的当前状态。
- `RiskRuleResult`：一条规则命中的结果。
- `RiskScanResult`：一次扫描的完整结果。
- `RiskNotificationDecision`：是否提醒、为什么提醒或跳过。

注意：如果 `core/models.py` 已有可复用的 `RiskAlert`，优先复用，不要重复造一个含义相同的模型。M5 专属中间结构可以放在 `core/risk_scan.py`，避免和 M4 同时抢 `core/models.py`。

### Step 2：实现任务状态归一化

输入来源优先使用 `tasks.list_my_tasks` 的结构化返回。M5 不要直接调用飞书 API，也不要绕过 `ToolRegistry`。

要把任务统一整理成：

- 任务 ID
- 标题
- 状态
- 负责人
- 截止时间
- 更新时间
- 飞书链接
- 原始 payload

首版可以先用本地 mock 数据验证，不依赖真实飞书。

### Step 3：实现风险规则

建议先做纯函数，便于测试：

```text
scan_task_risks(task, now, settings) -> list[RiskRuleResult]
```

首版规则：

- `overdue`：截止时间早于当前时间，且任务未完成。
- `due_soon`：距离截止时间小于配置窗口，且任务未完成。
- `stale_update`：超过 N 天没有更新。
- `missing_owner`：负责人为空。

规则配置优先读取现有 `RiskRuleSettings`，不要把阈值写死在业务逻辑里。

### Step 4：实现提醒降噪

建议新增本地去重键：

```text
risk_scan:{task_id}:{risk_type}
```

首版可以复用本地 storage 的幂等能力，做到同一任务同一风险在一个窗口内不重复提醒。后续再扩展为更细的 `risk_notifications` 表也可以，但首版不要为了表设计阻塞主链路。

### Step 5：实现风险卡片

建议新增文件：

- `cards/risk_scan.py`

卡片至少包含：

- 风险标题
- 任务名
- 风险原因
- 截止时间
- 负责人
- 建议动作
- 任务链接

卡片内容要聚合，不要一个风险发一张卡。推荐一次扫描生成一张“风险巡检摘要卡”，里面按严重程度列出 top N。

### Step 6：实现本地 demo

建议新增文件：

- `scripts/risk_scan_demo.py`

首版 demo 只跑本地 mock 数据：

```bash
python3 scripts/risk_scan_demo.py --backend local
```

验证目标：

- 能扫描一组未完成任务。
- 至少命中两类风险。
- 能生成风险卡片 payload。
- 默认不真实发送。
- 加 `--allow-write` 时才允许进入真实发送路径。

### Step 7：接入 Agent 工作流

等纯规则和卡片稳定后，再接入 `RiskScanWorkflow`：

- 通过 `risk.scan.tick` 触发。
- 先调用 `tasks.list_my_tasks`。
- 对工具返回的任务做规则扫描。
- 生成卡片草案。
- 需要发送时调用 `im.send_card`，并经过 `AgentPolicy`。

验证命令可以从只读开始：

```bash
python3 scripts/agent_demo.py --event-type risk.scan.tick --backend local --llm-provider scripted_debug --max-iterations 3
```

真实读任务可以后置：

```bash
python3 scripts/tasks_live_test.py --identity user --status all
```

真实写提醒必须显式加 `--allow-write` 或同等开关，并只发测试群。

## 5. 与 M4 的对接点

M5 不要直接依赖 M4 内部实现。双方通过稳定数据边界对接：

### M4 未来提供给 M5 的信息

- `ActionItem.item_id`
- 飞书 `task_id`
- `meeting_id`
- `minute_token`
- evidence refs
- 原始会议或妙记链接

这些信息会通过 `task_mappings` 或后续扩展表保存。

### M5 使用这些信息的方式

如果存在映射，风险提醒可以补充：

- 任务来自哪次会议。
- 对应哪个 Action Item。
- 原始证据链接是什么。
- 是否多次会议重复出现。

如果映射不存在，M5 仍然可以扫描飞书任务本身：

- 是否逾期。
- 是否临近截止。
- 是否长时间未更新。
- 是否缺负责人。

这保证了 M5 第一版可以独立交付，M4 完成后再增强闭环。

## 6. 冲突规避清单

M5 协作者优先修改：

- `docs/tasks/m5-risk-scan.md`
- `docs/tasks/m5-risk-scan-overview.md`
- `core/risk_scan.py`
- `cards/risk_scan.py`
- `scripts/risk_scan_demo.py`

尽量避免修改：

- `core/post_meeting.py`
- `cards/post_meeting.py`
- `scripts/post_meeting_demo.py`
- M4 相关任务文档

谨慎修改，且需要提前沟通：

- `core/models.py`
- `core/workflows.py`
- `core/router.py`
- `core/storage.py`
- `adapters/feishu_tools.py`
- `core/policy.py`

## 7. 验收标准

M5 第一版完成时，应满足：

- 能用本地 mock 任务跑完整风险扫描。
- 至少识别 `overdue` 和 `stale_update` 两类风险。
- 能生成结构化 `RiskAlert` 或等价结果。
- 能生成风险提醒卡片 payload。
- 默认不发送真实消息。
- 真实发送必须显式 `--allow-write`，并通过 `AgentPolicy`。
- 同一任务同一风险不会在短时间内重复提醒。
- 文档记录修改文件、核心类/函数、运行逻辑、验证命令和结果。

## 8. 建议给协作者的第一批任务

1. 新增 `core/risk_scan.py`，实现任务快照、风险规则和扫描结果。
2. 新增 `scripts/risk_scan_demo.py`，用 mock 数据验证规则。
3. 新增 `cards/risk_scan.py`，生成风险提醒卡片 payload。
4. 把 demo 接到 `RiskScanWorkflow` 的本地路径。
5. 更新 `docs/tasks/m5-risk-scan.md`，记录实现和验证结果。

第一批任务不要接真实写入，也不要改 M4。这样最容易并行推进，也最不容易和会后任务落地工作流冲突。
