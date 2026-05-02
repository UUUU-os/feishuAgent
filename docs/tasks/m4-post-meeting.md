## 5.4 M4：会后总结与任务落地工作流

### T4.1 定义 `post_meeting_followup` 工作流

- 优先级：`P0`
- 目标：明确会后流程边界
- 验收标准：
  - 输入为妙记或会议信息
  - 输出为结构化总结、Action Items 和回写结果

#### T4.1 当前实现补强：联系人解析工具边界

- 已更新文件：
  - `core/router.py`
  - `core/workflows.py`
  - `tests/test_router.py`
  - `tasks.md`
- 已实现的核心能力：
  - `minute.ready` 路由现在会显式暴露 `contact.get_current_user`
  - `minute.ready` 路由现在会显式暴露 `contact.search_user`
  - `MANUAL_WORKFLOW_TOOLS["post_meeting_followup"]` 已同步加入这两个工具，确保手动 `message.command -> post_meeting_followup` 和自动事件路由保持一致
  - `PostMeetingFollowupWorkflow` 的工具边界与仓库安全规范重新对齐：当负责人是“我”或具体姓名时，后续 Agent 可以先解析 open_id，而不是编造负责人
- 当前验证方式：
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_router` 验证 `minute.ready` 和手动 `post_meeting_followup` 两条路由都包含联系人解析工具
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type minute.ready --backend local --llm-provider scripted_debug --max-iterations 3` 验证本地会后链路仍能进入 `post_meeting_followup`

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
