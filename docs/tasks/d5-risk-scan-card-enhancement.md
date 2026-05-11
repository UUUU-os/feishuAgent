# D5：风险巡检卡片扩充落地记录

## 1. 任务定位

D5 面向 OpenClaw / 答辩演示中的“会后持续推进”环节，目标是把 M5 风险巡检从任务提醒升级为
可解释、可追溯、可行动的风险诊断卡：

```text
M4 任务落地 / 飞书任务
  -> M5 风险规则扫描
  -> 生成风险等级、来源证据、影响范围和 Agent 分析
  -> 聚合为风险诊断卡
  -> dry-run 预览或显式 allow-write 后发送到飞书测试群
```

D5 不新增独立工作流，而是在现有 M5 `risk_scan` 主链路上增强风险类型、诊断字段和卡片展示。

## 2. 当前代码基线

| 能力 | 当前实现 | D5 判断 |
|---|---|---|
| 任务归一化 | `core/risk_scan.py::normalize_task_snapshots()` | 已兼容飞书任务、ActionItem 和本地 mock |
| 风险扫描 | `scan_risks()` / `scan_task_risks()` | 已具备逾期、临期、长期未更新、缺负责人 |
| 来源证据 | `enrich_risks_with_task_mappings()` | 已能从 M4 `task_mappings` 反查会议、妙记和证据片段 |
| 风险卡片 | `cards/risk_scan.py::build_risk_scan_card()` | 已有聚合卡，但视觉层级和诊断字段不足 |
| 降噪机制 | `decide_risk_notification()` + `risk_notifications` | 已能按风险 key 和每日上限抑制重复提醒 |
| 演示入口 | `scripts/risk_scan_demo.py` | 已支持 local / feishu 和 `--show-card` |

## 3. 本轮完成内容

### 3.1 扩展 D5 风险类型

`core/risk_scan.py::scan_task_risks()` 新增两类规则：

- `missing_due_date`：任务缺少明确截止时间时生成中风险，避免系统无法继续做逾期、临期和提醒优先级判断。
- `recurring_issue`：从任务 `raw_payload.extra.repeated_mentions`、`recurrence_count`、`recurring_count`
  和 `recurring_evidence` 中识别同类问题反复出现；重复 3 次及以上为高风险，2 次为中风险。

现有规则继续保留：

- `overdue`
- `due_soon`
- `stale_update`
- `missing_owner`

### 3.2 增加风险诊断字段

`RiskRuleResult` 新增：

- `impact_scope`：说明风险影响哪个负责人、任务闭环或会议推进环节。
- `agent_analysis`：解释 Agent 为什么认为这是风险，而不是只展示规则名。

`build_risk_result()` 会集中生成上述字段；`enrich_risk_with_mapping()` 在补充 M4 来源证据时保留这些诊断字段。

### 3.3 优化风险巡检卡片

`cards/risk_scan.py` 完成 D5 卡片层级增强：

- 顶部概览展示高 / 中 / 低风险数量。
- 风险清单按严重程度分组展示。
- 每条风险展示风险类型、等级、原因、Agent 分析、影响范围、负责人、截止时间、建议动作。
- 卡片展示时合并 `notify_risks`、`suppressed_risks` 和 `scan_result.risks`，确保即使降噪策略只提醒少数风险，诊断卡仍能看到完整风险面。
- 已有 M4 来源展示继续保留：来源会议、妙记 token 和第一条证据片段。

### 3.4 准备 D5 本地演示样例

`scripts/risk_scan_demo.py::build_local_risk_demo_tasks()` 新增两条演示任务：

- 缺截止时间任务：`补充 OpenClaw 演示兜底截图`
- 反复出现任务：`修复任务卡回调链路不稳定问题`，带两条模拟妙记证据

本地 demo 现在能覆盖逾期、临期、长期未更新、缺负责人、缺截止时间、反复出现等风险类型。

## 4. 涉及文件

| 文件 | 改动 |
|---|---|
| `core/risk_scan.py` | 新增 D5 风险类型、`impact_scope`、`agent_analysis`、风险概览低风险统计 |
| `cards/risk_scan.py` | 风险卡按等级分组，展示概览、Agent 分析、影响范围，并合并降噪风险用于诊断展示 |
| `scripts/risk_scan_demo.py` | 本地 mock 增加缺截止时间和反复出现风险样例 |
| `tests/test_risk_scan.py` | 覆盖 D5 新风险类型、重复出现证据和诊断字段 |
| `tests/test_risk_scan_card.py` | 覆盖风险概览、等级分组、降噪风险仍可见 |
| `docs/tasks/d5-risk-scan-card-enhancement.md` | 新增 D5 里程碑记录 |
| `tasks.md` | 增加 D5 里程碑入口与精简完成摘要 |

## 5. 验证结果

已通过：

```bash
python3 -m py_compile core/risk_scan.py cards/risk_scan.py scripts/risk_scan_demo.py tests/test_risk_scan.py tests/test_risk_scan_card.py
python3 -m unittest tests.test_risk_scan tests.test_risk_scan_card tests.test_storage_risk_notifications tests.test_risk_scan_workflow
python3 scripts/risk_scan_demo.py --backend local --show-card
```

验证结果：

- D5/M5 相关单测共 16 个通过。
- 本地风险 demo 扫描 7 个 mock 任务，跳过 1 个已完成任务，命中 6 类风险；卡片 JSON 顶部展示高 / 中 / 低风险数量，并在风险清单中展示 Agent 分析、影响范围和建议动作。
- 本轮未执行真实飞书发卡；真实发送仍必须使用 `--backend feishu --allow-write`，且仅面向测试群。

## 6. 真实飞书测试命令

### 6.1 前置登录

如果当前用户身份未登录，先执行 OAuth Device Flow。登录成功后输出里会包含当前用户 `open_id`：

```bash
python3 scripts/oauth_device_login.py
```

输出示例：

```text
- open_id: ou_xxx
- name: 测试用户
```

### 6.2 创建 D5 逾期风险任务

今天是 2026-05-11；为制造稳定的 `overdue` 风险，创建一个截止日期为 2026-05-10 的未完成任务。
将命令中的 `ou_xxx` 替换为上一步输出的当前用户 `open_id`：

```bash
python3 scripts/task_create_live_test.py \
  --summary "D5测试-逾期风险-完成客户方案评审" \
  --description "用于 MeetFlow D5 风险巡检真实飞书测试，可测试 overdue 风险。" \
  --assignee-open-id "ou_xxx" \
  --due 2026-05-10 \
  --identity user \
  --idempotency-key "d5-risk-overdue-20260511-001" \
  --create
```

### 6.3 创建 D5 缺截止时间风险任务

为制造 `missing_due_date` 风险，创建任务时不传 `--due`：

```bash
python3 scripts/task_create_live_test.py \
  --summary "D5测试-缺截止时间-补充演示兜底截图" \
  --description "用于 MeetFlow D5 风险巡检测试 missing_due_date。" \
  --assignee-open-id "ou_xxx" \
  --identity user \
  --idempotency-key "d5-risk-missing-due-20260511-001" \
  --create
```

### 6.4 确认测试任务可被读取

创建后先用任务读取脚本确认当前用户能看到测试任务：

```bash
python3 scripts/tasks_live_test.py \
  --identity user \
  --completed false \
  --query "D5测试" \
  --show-raw
```

### 6.5 真实读取飞书任务并预览风险卡

该命令只读取飞书任务并打印风险卡 JSON，不发送群消息：

```bash
python3 scripts/risk_scan_demo.py \
  --backend feishu \
  --identity user \
  --completed false \
  --show-card
```

### 6.6 真实发送风险巡检卡到测试群

确认 `config/settings.local.json` 中 `feishu.default_chat_id` 指向测试群，且机器人已入群后，再执行：

```bash
python3 scripts/risk_scan_demo.py \
  --backend feishu \
  --identity user \
  --send-identity tenant \
  --completed false \
  --show-card \
  --allow-write
```

如需显式指定测试群：

```bash
python3 scripts/risk_scan_demo.py \
  --backend feishu \
  --identity user \
  --send-identity tenant \
  --chat-id "你的测试群 chat_id" \
  --completed false \
  --show-card \
  --allow-write
```

注意：

- `task_create_live_test.py --create` 会真实创建飞书任务，只用于测试账号或测试任务。
- 真实发卡必须显式加 `--allow-write`，并只发送到测试群。
- 如果风险卡没有展示刚创建的任务，先用 `tasks_live_test.py --query "D5测试"` 确认任务是否属于当前登录用户、是否仍为未完成状态。

## 7. 剩余风险

- `recurring_issue` 当前依赖任务扩展字段中的重复次数和证据，尚未自动从历史妙记 / RAG 中聚合生成。
- 卡片操作按钮“标记已处理 / 忽略 / 再次提醒”尚未接入回调和 `AgentPolicy`，本轮只做诊断展示，不伪造未实现动作。
- 真实飞书任务的更新时间、成员结构和自定义字段可能存在租户差异，真实联调时需继续观察 `raw_payload` 并补充归一化规则。
