# M4 会后总结真实联调报告

## 1. 妙记输入

- minute_token: `obcn7xk3bg1olx8lb811fq4i`
- 标题: 飞书 AI 校园挑战赛-开赛仪式（线上直播）
- source_url: https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i
- source_type: `feishu_minute`
- 读取身份: `user`
- 内容来源: `minutes.get + minutes.artifacts`（AI 总结 / 待办 / 章节；不是逐字稿原文）
- raw_text_length: `5113`
- allow_write: `False`
- send_card: `False`

## 2. 工作流阶段

```text
真实妙记 -> AI 产物读取 -> PostMeetingInput -> clean_transcript -> extract_decisions/open_questions/action_items -> confidence/confirmation -> card render -> ToolRegistry + AgentPolicy 写入
```

## 3. 清洗与章节

- cleaned_line_count: `99`
- section_count: `4`
- signal_line_count: `31`

### 基础信息

- line_range: `3-6`
- signal_tags: ``

### AI 总结

- line_range: `8-78`
- signal_tags: `action_item, due_date, owner, open_question`

### 待办

- line_range: `80-82`
- signal_tags: `due_date, action_item`

### 章节

- line_range: `84-99`
- signal_tags: `action_item, open_question, due_date`

## 4. Action Items

### Action Item 1

- item_id: `action_9742539104e5`
- title: 仓库创建填写：以组为单位创建 GitHub 代码仓库，将项目设置为 public，并于今天或最晚明天将仓库地址填写到问卷中（来自王恂）
- owner_candidate: `所有参赛同学`
- due_date_candidate: `今天或最晚明天`
- priority: `high`
- confidence: `0.80`
- needs_confirm: `True`
- confirm_reason: 缺少可解析负责人
- source_line: `80`
- auto_create_candidate: `False`

#### Evidence

- `obcn7xk3bg1olx8lb811fq4i` feishu_minute: 1. 仓库创建填写：以组为单位创建 GitHub 代码仓库，将项目设置为 public，并于今天或最晚明天将仓库地址填写到问卷中（来自王恂） @所有参赛同学

### Action Item 2

- item_id: `action_c4ca5322928a`
- title: 文档创建提交：按照模板创建个人阶段成果小结的飞书文档，命名为姓名 + 个人阶段成果小结，于今天到明天将文档链接填写到问卷中（来自王恂）
- owner_candidate: `所有参赛同学`
- due_date_candidate: `今天到明天`
- priority: `high`
- confidence: `0.80`
- needs_confirm: `True`
- confirm_reason: 缺少可解析负责人
- source_line: `81`
- auto_create_candidate: `False`

#### Evidence

- `obcn7xk3bg1olx8lb811fq4i` feishu_minute: 2. 文档创建提交：按照模板创建个人阶段成果小结的飞书文档，命名为姓名 + 个人阶段成果小结，于今天到明天将文档链接填写到问卷中（来自王恂） @所有参赛同学

### Action Item 3

- item_id: `action_62d05507716e`
- title: 文档发送：将个人阶段成果小结的飞书文档模板发送到群里，供成员按模板创建个人文档并记录开发心路历程
- owner_candidate: `王恂`
- due_date_candidate: `未识别`
- priority: `medium`
- confidence: `0.70`
- needs_confirm: `True`
- confirm_reason: 缺少截止时间；置信度低于阈值 0.75
- source_line: `82`
- auto_create_candidate: `False`

#### Evidence

- `obcn7xk3bg1olx8lb811fq4i` feishu_minute: 3. 文档发送：将个人阶段成果小结的飞书文档模板发送到群里，供成员按模板创建个人文档并记录开发心路历程 @王恂

## 5. 决策与开放问题

- decisions_count: `0`
- open_questions_count: `1`
  - `question_cb1f98b68013` 存在全量预加载代价高的问题，定义和数据进入 context 会导致 context 空间膨胀，复杂接口参数和工具数增长也会使数据处理困难，且过程数据不能落盘和本地处理

## 6. 卡片产物

- summary_card: `MeetFlow 会后总结：飞书 AI 校园挑战赛-开赛仪式（线上直播）`，elements=`9`
- pending_card: `MeetFlow 待确认任务`，elements=`4`

## 7. 写入结果

- created_tasks: `0`
- skipped_tasks: `0`
- sent_cards: `0`
- write_skipped_reason: 未开启 --allow-write 或指定了 --read-only，本次不创建任务、不发送卡片。

## 8. 结论

本次发送 0 张卡片；3 个 Action Item 进入待确认，未自动创建任务。
