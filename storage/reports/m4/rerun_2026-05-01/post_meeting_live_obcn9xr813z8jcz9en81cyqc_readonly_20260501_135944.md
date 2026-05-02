# M4 会后总结真实联调报告

## 1. 妙记输入

- minute_token: `obcn9xr813z8jcz9en81cyqc`
- 标题: 妙计测试2
- source_url: https://jcneyh7qlo8i.feishu.cn/minutes/obcn9xr813z8jcz9en81cyqc
- source_type: `feishu_minute`
- 读取身份: `user`
- 内容来源: `minutes.get + minutes.artifacts`（AI 总结 / 待办 / 章节；不是逐字稿原文）
- raw_text_length: `195`
- allow_write: `False`
- send_card: `False`

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

- summary_card: `MeetFlow 会后总结：妙计测试2`，elements=`7`
- pending_card: 未发送候选（没有待确认任务）

## 7. 写入结果

- created_tasks: `0`
- skipped_tasks: `0`
- sent_cards: `0`
- write_skipped_reason: 未开启 --allow-write 或指定了 --read-only，本次不创建任务、不发送卡片。

## 8. 结论

本次发送 0 张卡片；未抽取到可落地 Action Item。
