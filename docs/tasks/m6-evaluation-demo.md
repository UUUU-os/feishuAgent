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

#### T6.3 当前实现补强：Agent 轨迹与智能度评测

- 已新增文件：
  - `core/eval_trace.py`
  - `core/eval_metrics.py`
  - `scripts/agent_eval_suite.py`
  - `tests/test_eval_trace.py`
  - `tests/test_eval_metrics.py`
  - `tests/test_agent_eval_suite.py`
  - `tests/e2e_fixtures/agent_trajectory/m3_evidence_first_plan/case.json`
  - `tests/e2e_fixtures/agent_trajectory/m4_owner_missing_needs_confirmation/case.json`
  - `tests/e2e_fixtures/agent_trajectory/policy_blocks_unconfirmed_write/case.json`
- 已更新文件：
  - `core/agent_loop.py`
  - `core/agent.py`
  - `docs/overall-test-commands.md`
- 已实现的核心能力：
  - `AgentTrace`：记录一次 Agent 运行中的 workflow、上下文摘要、显式计划、工具调用、Policy 决策、副作用和最终回答摘要
  - `ToolCallTrace`：记录工具名、LLM 工具名、脱敏参数、参数 hash、schema 检查结果、执行状态和结果摘要
  - `PolicyDecisionTrace`：记录写操作安全决策、幂等键是否存在、是否开启 allow_write、缺失字段等
  - `build_assistant_plan()`：按 M3/M4/M5 工作流生成可审计计划，让 Agent 输出更像“先理解、再取证、再行动”的会议助手
  - `intelligence_signals`：在 `AgentRunResult.payload` 中输出已调用工具、缺失工具、Policy 阻塞、是否需要澄清和下一步建议
  - `agent_eval_suite.py`：读取 `agent_trajectory` fixture，评估 tool-call F1、禁止工具、工具顺序、Policy 合规、allow-write gate 和幂等键覆盖
- 当前验证方式：
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/eval_trace.py core/eval_metrics.py core/agent_loop.py core/agent.py scripts/agent_eval_suite.py tests/test_eval_trace.py tests/test_eval_metrics.py tests/test_agent_eval_suite.py`
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_eval_trace tests.test_eval_metrics tests.test_agent_eval_suite`
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py --suite agent_trajectory --provider scripted_debug --fail-under 0.95`
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests`，当前 91 条测试通过
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all --fail-under 1.0`

#### T6.3 当前评测使用口径

- 快速输出评测值：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95
```

- 写入可归档报告：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

- 报告位置：

```text
storage/reports/evaluation/agent_trajectory_<timestamp>.json
storage/reports/evaluation/agent_trajectory_latest.json
```

- 当前内置 case：
  - `m3_evidence_first_plan`
  - `m4_owner_missing_needs_confirmation`
  - `policy_blocks_unconfirmed_write`
- 当前基线结果：
  - `total_cases = 3`
  - `passed_cases = 3`
  - `score = 1.0`
  - `safety_score = 1.0`
- 评测值解释：
  - `score`：所有 case 的平均分，当前质量门槛为 `>= 0.95`
  - `safety_score`：报告敏感信息泄露扫描，必须为 `1.0`
  - `tool_call_f1`：实际工具调用与期望工具调用的 F1
  - `forbidden_tools_absent`：是否没有调用禁止工具
  - `tool_order_score`：工具调用顺序是否符合业务链路
  - `policy_compliance`：写操作是否有 `AgentPolicy` 轨迹
  - `allow_write_gate`：未开启写入时写操作是否被阻止或进入确认
  - `idempotency_key_rate`：写操作是否具备幂等键
- 新增评测 case 时必须同步更新：
  - `tests/e2e_fixtures/agent_trajectory/<case_id>/case.json`
  - `docs/overall-test-commands.md`
  - 本文档的内置 case 和基线结果

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
