## 5.5 M5：风险巡检与提醒工作流

协作者开发前请先阅读总览文档：[m5-risk-scan-overview.md](./m5-risk-scan-overview.md)。

这份总览说明了 M5 与 M4 的关系、推荐实现顺序、建议新增文件、冲突规避边界和验收标准。M5 第一版应优先独立基于任务状态做风险扫描，不阻塞 M4 的会后总结与任务落地开发。

当前仓库级详细改造计划见：[M5 风险巡检与提醒工作流详细改造计划](../m5-risk-scan-implementation-plan.md)。

第二版代码施工方案见：[M5 风险巡检第二版代码改造方案](../m5-risk-scan-code-change-plan.md)。该文档按文件、函数、数据契约、补丁顺序和验收命令拆解后续实现工作。

### T5.1 定义 `risk_scan` 工作流

- 优先级：`P0`
- 状态：`已完成第二版核心实现`
- 目标：明确风险扫描输入、输出和策略
- 验收标准：
  - 能对未完成任务列表运行一次完整扫描
- 实现记录：
  - 新增 `core/risk_scan.py`，定义 `TaskSnapshot`、`RiskRuleResult`、`RiskScanResult`、`RiskNotificationDecision`。
  - `RiskScanWorkflow` 已通过 `post_process_result()` 从 `tasks.list_my_tasks` 工具结果生成 `result.payload["risk_scan"]`。

### T5.2 实现任务状态对账

- 优先级：`P0`
- 状态：`已完成 M4/M5 闭环对接`
- 目标：将历史 Action Items 与实际任务状态做映射
- 验收标准：
  - 能识别哪些 Action Item 已建任务、未建任务、状态异常
- 实现记录：
  - `normalize_task_snapshots()` 兼容 `ActionItem`、工具序列化 dict 和本地 mock。
  - 归一化字段包括 `task_id`、`title`、`owner`、`due_timestamp`、`updated_at`、`completed_at`、`url`。
  - `core/storage.py` 新增 `get_task_mapping_by_task_id()` 和 `find_task_mappings_by_meeting()`，M5 可用飞书任务 ID 反查 M4 创建任务时保存的 `meeting_id`、`minute_token`、`title`、`source_url` 和 `evidence_refs`。
  - `core/risk_scan.py` 新增 `enrich_risks_with_task_mappings()`，在风险结果中写入 `evidence["m4_task_mapping"]`，让“当前任务风险”能接回“来自哪次会后 Action Item”。

### T5.3 实现风险识别规则

- 优先级：`P0`
- 状态：`已完成`
- 建议规则：
  - 逾期未完成
  - 超过 3 天未更新
  - 无负责人
  - 多次会议重复提及仍未关闭
- 验收标准：
  - 至少能识别两类风险
- 实现记录：
  - 已实现 `overdue`、`due_soon`、`stale_update`、`missing_owner` 四类规则。
  - 已完成任务会被跳过，不触发风险。
  - “多次会议重复提及仍未关闭”保留到 M4 任务映射证据链完成后增强。

### T5.4 实现风险提醒卡片

- 优先级：`P0`
- 状态：`已完成 M4 来源富化展示`
- 目标：向负责人或 PM 推送聚合提醒
- 验收标准：
  - 卡片包含任务名、风险原因、截止时间、处理建议
- 实现记录：
  - 新增 `cards/risk_scan.py`，实现 `build_risk_scan_card()`。
  - 卡片包含扫描任务数、命中风险数、本次提醒数、降噪跳过数、任务名、风险原因、负责人、截止时间和建议动作。
  - 风险卡片现在会在存在 M4 映射时展示“来源会议/行动项”、`minute_token` 和第一条证据片段，形成 `M4 会后创建任务 -> M5 风险追踪 -> 回到原始妙记证据` 的演示闭环。

### T5.5 接入每日定时巡检

- 优先级：`P0`
- 状态：`脚本模拟已完成，真实 scheduler 待接入`
- 目标：通过 scheduler 每日自动扫描
- 验收标准：
  - 可通过真实定时或模拟调度运行
- 实现记录：
  - 新增 `scripts/risk_scan_demo.py`，支持 `--backend local|feishu`。
  - `scripts/agent_demo.py --event-type risk.scan.tick` 已能跑通 Agent 风险巡检链路。

### T5.6 实现提醒降噪机制

- 优先级：`P1`
- 状态：`已完成第二版存储基础`
- 目标：避免同一风险重复轰炸
- 验收标准：
  - 同一任务同一风险在一定窗口内不重复发送
- 实现记录：
  - `core/storage.py` 新增 `risk_notifications` 表和 `record_risk_notification()`、`get_latest_risk_notification()`、`has_recent_risk_notification()`。
  - 风险降噪键格式为 `risk_scan:{task_id}:{risk_type}:{YYYYMMDD}`。
  - 聚合卡片发送幂等键格式为 `risk_scan:notification:{YYYYMMDD}:{hash}`。

## 第二版验证记录

本轮改造新增或修改：

- `core/risk_scan.py`
- `cards/risk_scan.py`
- `scripts/risk_scan_demo.py`
- `core/storage.py`
- `core/workflows.py`
- `core/agent.py`
- `core/policy.py`
- `adapters/feishu_tools.py`
- `scripts/agent_demo.py`
- `core/__init__.py`
- `cards/__init__.py`
- `tests/test_risk_scan.py`
- `tests/test_risk_scan_card.py`
- `tests/test_storage_risk_notifications.py`
- `tests/test_risk_scan_workflow.py`

2026-05-04 追加 M4/M5 闭环改造：

- `core/storage.py`：新增按 `task_id` 反查 task mapping、按会议/妙记查 mapping 的接口。
- `core/risk_scan.py`：新增风险来源富化函数，把 M4 的 `task_mappings` 合并进风险 evidence。
- `core/workflows.py`：`RiskScanWorkflow.post_process_result()` 在降噪和渲染卡片前执行 M4 来源富化。
- `cards/risk_scan.py`：风险卡片展示来源会议、妙记 token 和证据片段。
- `tests/test_storage_risk_notifications.py`、`tests/test_risk_scan.py`、`tests/test_risk_scan_card.py`：新增闭环回归测试。

已执行验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/risk_scan.py cards/risk_scan.py scripts/risk_scan_demo.py core/workflows.py core/storage.py core/policy.py adapters/feishu_tools.py scripts/agent_demo.py tests/test_risk_scan.py tests/test_risk_scan_card.py tests/test_storage_risk_notifications.py tests/test_risk_scan_workflow.py
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_risk_scan tests.test_risk_scan_card tests.test_storage_risk_notifications tests.test_risk_scan_workflow
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py --backend local --show-card
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type risk.scan.tick --backend local --llm-provider scripted_debug --max-iterations 3 --show-full
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests -p 'test_*.py'
```

验证结果：

- 新增 M5 单测 11 个通过。
- 全量测试 29 个通过。
- 本地 demo 扫描 5 个 mock 任务，命中 4 条风险，生成风险卡片 JSON。
- Agent 风险巡检链路已在 `result.payload["risk_scan"]` 中生成 `scan_result`、`notification_decision` 和 `card_payload`。
- 2026-05-04 闭环改造后，`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests` 通过 61 条测试。

---
