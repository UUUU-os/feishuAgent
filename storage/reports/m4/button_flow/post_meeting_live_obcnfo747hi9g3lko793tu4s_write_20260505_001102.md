# M4 会后总结真实联调报告

## 1. 妙记输入

- minute_token: `obcnfo747hi9g3lko793tu4s`
- 标题: 测试会议
- source_url: https://jcneyh7qlo8i.feishu.cn/minutes/obcnfo747hi9g3lko793tu4s
- source_type: `feishu_minute`
- 读取身份: `user`
- 内容来源: `minutes.get + minutes.artifacts`（AI 总结 / 待办 / 章节；不是逐字稿原文）
- raw_text_length: `194`
- allow_write: `True`
- send_card: `True`

## 2. 工作流阶段

```text
真实妙记 -> AI 产物读取 -> PostMeetingInput -> clean_transcript -> extract_decisions/open_questions/action_items -> confidence/confirmation -> card render -> ToolRegistry + AgentPolicy 写入
```

## 3. 清洗与章节

- cleaned_line_count: `8`
- section_count: `2`
- signal_line_count: `1`

### 基础信息

- line_range: `3-6`
- signal_tags: ``

### AI 产物状态

- line_range: `8-8`
- signal_tags: `action_item, due_date`

## 4. Action Items

暂无 Action Items。

## 5. 决策与开放问题

- decisions_count: `0`
- open_questions_count: `0`

## 6. 卡片产物

- summary_card: `MeetFlow 会后总结：测试会议`，elements=`7`
- pending_card: 未发送候选（没有待确认任务）

## 6.1 相关背景资料

- related_knowledge_status: `empty`
- related_knowledge_query: 测试会议 meetflow
- related_knowledge_hit_count: `0`

## 7. 写入结果

- created_tasks: `0`
- skipped_tasks: `0`
- sent_cards: `1`
  - summary_card: status=`success`, message_id=`om_x100b50b81fa6bca4b36018f35527d67`, chat_id=`oc_d3e31969e4b527ee929db9cfb1493bb6`

## 8. 结论

本次发送 1 张卡片；未抽取到可落地 Action Item。
