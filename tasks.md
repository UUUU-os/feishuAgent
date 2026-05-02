# MeetFlow 开发任务索引

本文档是 MeetFlow 任务拆解的入口索引。详细任务、实现记录和验证结果已按里程碑拆分到 `docs/tasks/`，避免单个 `tasks.md` 过长难以维护。

## 文档目标

这些任务文档用于将 `MeetFlow - 飞书会议知识闭环 Agent` 的 PRD 和架构方案拆解为可执行的开发任务清单，方便团队按阶段推进开发、联调、验证和答辩准备。

任务文档强调四件事：

- 先做什么，后做什么
- 每个模块需要完成哪些任务
- 每项任务完成的验收标准是什么
- 哪些任务是 Demo 必做，哪些是增强项

## 开发原则

- 优先跑通主链路，不先追求大而全
- 优先实现“会前 - 会后 - 巡检”闭环
- 优先保证结构化输出和证据链
- 优先保证任务可演示、可验收、可回放

## 优先级说明

- `P0`：必须完成，缺失会导致 Demo 主链路无法成立
- `P1`：重要增强，影响稳定性、可解释性和答辩效果
- `P2`：可选增强，适合有余力时补充

## 里程碑文档

- [M1：项目骨架与基础设施](docs/tasks/m1-foundation.md)
- [M2：飞书接入与数据读取](docs/tasks/m2-feishu-integration.md)
- [M2.8：业务侧垂直 Agent Runtime](docs/tasks/m2_8-agent-runtime.md)
- [M3：会前知识卡片工作流](docs/tasks/m3-pre-meeting.md)
- [M4：会后总结与任务落地工作流](docs/tasks/m4-post-meeting.md)
- [M5：风险巡检与提醒工作流](docs/tasks/m5-risk-scan.md)
- [M6：评估、答辩材料与演示脚本](docs/tasks/m6-evaluation-demo.md)
- [技术拆分、依赖关系、开发顺序与验收总表](docs/tasks/planning-and-acceptance.md)

## 当前重点

当前开发重点已切到 [M4：会后总结与任务落地工作流](docs/tasks/m4-post-meeting.md) 的 Agent 化收口。

M4 的当前核心边界是让 `minute.ready` 回到 MeetFlow 主 Agent 链路，而不是由会后脚本直接串联所有逻辑：

```text
AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

当前 M4 Agent 化重点：

- `PostMeetingFollowupWorkflow.prepare_context()` 暴露 M4 结构化上下文
- 注册 `post_meeting.*` 工具给 Agent Loop 使用
- 用 `scripted_debug` 验证读妙记、构造 artifacts、RAG、人员解析、任务参数准备、发卡和待确认 registry 保存
- 所有写操作继续经过 `AgentPolicy`

最近进展：

- 2026-05-02：修复 M4 待确认卡片按钮重复/交叉点击问题。修改 `core/confirmation_commands.py`，新增 `claim_pending_action_status()`；修改 `core/card_callback.py`，确认创建前进入 `creating`、拒绝前进入 `rejecting`，并由 `guard_pending_action_transition()` 拦截 `created` / `reject_create_task` / `creating` / `rejecting` 状态下的旧按钮点击。补充 `tests/test_post_meeting_card_callback.py` 用例，验证创建处理中再次点击拒绝不会改写状态，且回写卡片不再包含拒绝按钮。同步更新 [M4 任务文档](docs/tasks/m4-post-meeting.md) 和 [架构说明](architecture.md)。验证通过：`python3 -m py_compile core/card_callback.py core/confirmation_commands.py tests/test_post_meeting_card_callback.py`；`python3 -m unittest tests.test_post_meeting_card_callback`（11 个用例通过）。

M3 的核心边界是“轻量 RAG + 结构化元数据 + 增量更新”，并继续作为 M4 相关背景资料召回能力复用：

RAGFlow 代码阅读中可借鉴的 RAG 设计已整理到 [RAGFlow 代码阅读笔记](docs/ragflow-design-notes.md)，作为后续增强 M3 检索、chunk 元数据、rerank 和索引任务的参考。

- T3.1：定义 `pre_meeting_brief` 工作流输入输出
- T3.2：实现会议主题识别
- T3.3：实现关联资源召回
- T3.4：实现轻量知识索引与文档清洗
- T3.5：实现证据排序与摘要生成
- T3.6：实现知识检索 Agent 工具
- T3.7：实现会前卡片模板
- T3.8：接入会前定时触发
- T3.9：增加手动兜底入口
- T3.10：预留知识变更更新机制
- T3.11：知识域与 embedding 模型一致性治理
- T3.12：扩展 chunk schema 与结构化位置元数据
- T3.13：实现可配置混合检索和可解释分数
- T3.14：接入可选 reranker 阶段
- T3.15：支持 TOC 增强与父子 chunk 展开
- T3.16：实现 evidence pack token budget 与稳定引用格式

关于 T3.10 的关键设计结论已经记录在 M3 文档中：`updated_at + checksum` 只能判断“检查后是否需要重建”，不能让系统第一时间知道文档变化；实时变化感知需要飞书事件订阅、Webhook 或 WebSocket，将变更写入 `index_jobs` 后由后台 worker 异步刷新索引。

## 维护约定

- 完成某个任务后，更新对应里程碑文档中的任务条目。
- 如果新增、删除或调整里程碑文档，更新本索引。
- 如果实现改变架构边界、Agent 流程或安全策略，同步更新 `architecture.md`。
- 如果实现改变用户场景、验收方式或产品目标，同步更新 `prd.md`。
