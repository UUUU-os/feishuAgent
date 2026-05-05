# M4 会后总结真实联调报告

## 1. 妙记输入

- minute_token: `obcnf14z4qh9i2o846jy56ae`
- 标题: 测试会议
- source_url: https://jcneyh7qlo8i.feishu.cn/minutes/obcnf14z4qh9i2o846jy56ae
- source_type: `feishu_minute`
- 读取身份: `user`
- 内容来源: `minutes.get + minutes.artifacts`（AI 总结 / 待办 / 章节；不是逐字稿原文）
- raw_text_length: `219`
- allow_write: `True`
- send_card: `True`

## 2. 工作流阶段

```text
真实妙记 -> AI 产物读取 -> PostMeetingInput -> clean_transcript -> extract_decisions/open_questions/action_items -> confidence/confirmation -> card render -> ToolRegistry + AgentPolicy 写入
```

## 3. 清洗与章节

- cleaned_line_count: `8`
- section_count: `2`
- signal_line_count: `2`

### 基础信息

- line_range: `3-6`
- signal_tags: ``

### 待办

- line_range: `8-8`
- signal_tags: `action_item, due_date`

## 4. Action Items

### Action Item 1

- item_id: `action_a82e0db1b8ec`
- title: 测试报告整理：整理 meet flow 的 M4 测试报告，于明天下午 6 点前完成
- owner_candidate: `张三`
- due_date_candidate: `明天下午 6 点前`
- priority: `high`
- confidence: `0.95`
- needs_confirm: `False`
- confirm_reason: 无
- source_line: `8`
- auto_create_candidate: `True`

#### Evidence

- `obcnf14z4qh9i2o846jy56ae` feishu_minute: 1. 测试报告整理：整理 meet flow 的 M4 测试报告，于明天下午 6 点前完成 @张三

## 5. 决策与开放问题

- decisions_count: `0`
- open_questions_count: `0`

## 6. 卡片产物

- summary_card: `MeetFlow 会后总结：测试会议`，elements=`7`
- pending_card: `MeetFlow 待确认任务`，elements=`6`

## 6.1 相关背景资料

- related_knowledge_status: `empty`
- related_knowledge_query: 测试会议 meetflow flow meet 测试报告 点前完成 于明天下午 测试报告整理 m4 整理
- related_knowledge_hit_count: `0`

## 7. 写入结果

- created_tasks: `0`
- skipped_tasks: `1`
  - `action_a82e0db1b8ec` reason=
- sent_cards: `2`
  - summary_card: status=`success`, message_id=`om_x100b50ae3f4210a4c2dcef51e553713`, chat_id=`oc_d3e31969e4b527ee929db9cfb1493bb6`
  - pending_button_card: status=`success`, message_id=`om_x100b50ae3f55c0bcc3dac144172ca28`, chat_id=`oc_d3e31969e4b527ee929db9cfb1493bb6`

## 8. 结论

本次发送 2 张卡片；1 个 Action Item 进入待确认，未自动创建任务。
