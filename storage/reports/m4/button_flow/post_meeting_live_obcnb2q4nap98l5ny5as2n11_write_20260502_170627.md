# M4 会后总结真实联调报告

## 1. 妙记输入

- minute_token: `obcnb2q4nap98l5ny5as2n11`
- 标题: 飞书 AI 校园竞赛-主题分享直播-产品专场
- source_url: https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11
- source_type: `feishu_minute`
- 读取身份: `user`
- 内容来源: `minutes.get + minutes.artifacts`（AI 总结 / 待办 / 章节；不是逐字稿原文）
- raw_text_length: `2677`
- allow_write: `True`
- send_card: `True`

## 2. 工作流阶段

```text
真实妙记 -> AI 产物读取 -> PostMeetingInput -> clean_transcript -> extract_decisions/open_questions/action_items -> confidence/confirmation -> card render -> ToolRegistry + AgentPolicy 写入
```

## 3. 清洗与章节

- cleaned_line_count: `53`
- section_count: `4`
- signal_line_count: `20`

### 基础信息

- line_range: `3-6`
- signal_tags: ``

### AI 总结

- line_range: `8-40`
- signal_tags: `action_item, owner, decision, due_date, open_question`

### 待办

- line_range: `42-42`
- signal_tags: `action_item`

### 章节

- line_range: `44-53`
- signal_tags: `action_item`

## 4. Action Items

### Action Item 1

- item_id: `action_a0376dc045f8`
- title: 链接分享：将多维表格以数据表为数据源、通过 Web coding 方式生成个性化页面的产品发布会信息链接发送给大家
- owner_candidate: `吴星辉`
- due_date_candidate: `未识别`
- priority: `medium`
- confidence: `0.70`
- needs_confirm: `True`
- confirm_reason: 缺少截止时间；置信度低于阈值 0.75
- source_line: `42`
- auto_create_candidate: `False`

#### Evidence

- `obcnb2q4nap98l5ny5as2n11` feishu_minute: 1. 链接分享：将多维表格以数据表为数据源、通过 Web coding 方式生成个性化页面的产品发布会信息链接发送给大家 @吴星辉

## 5. 决策与开放问题

- decisions_count: `2`
  - `decision_138f20656f97` 相互耦合关系：PMF 不仅是产品和市场的匹配，还涉及商业模式画布中各元素的组合，产品定义、渠道选择、商业模式确定等相互耦合，且顺序会对后续环节产生限制。例如，toB 或 toC 的产品决策会影响产品功能复杂度、定价和推广方式
  - `decision_bbbaa074dfd9` 极简运营路径：吴星辉推荐参考《小而美》中的方法，从社区着手，关注用户问题和现有解决方案的不足，在产品化之前可采用人工方式做 wait list 和预购，以判断产品价值，降低 PMF 风险
- open_questions_count: `0`

## 6. 卡片产物

- summary_card: `MeetFlow 会后总结：飞书 AI 校园竞赛-主题分享直播-产品专场`，elements=`9`
- pending_card: `MeetFlow 待确认任务`，elements=`5`

## 6.1 相关背景资料

- related_knowledge_status: `hit`
- related_knowledge_query: 飞书 AI 校园竞赛-主题分享直播-产品专场 meetflow 相互耦合关系：PMF 不仅是产品和市场的匹配，还涉及商业模式画布中各元素的组合，产品定义、渠道选择、商业模式确定等相互耦合，且顺序会对后续环节产生限制。例如，toB 或 toC 的产品决策会影响产品功能复杂度、定价和推广方式 极简运营路径：吴星辉推荐参考《小而美》中的方法，从社区着手，关注用户问题和现有解决方案的不足，在产品化之前可采用人工方式做 wait list 和预购，以判断产品价值，降低 PMF 风险 链接分享：将多维表格以数据表为数据源、通过 Web coding 方式生成个性化页面的产品发布会信息链接发送给大家
- related_knowledge_hit_count: `2`
  - `kref_e4cba7610a1ea558` Trae IDE 模型配置指南 score=`0.50` url=https://bytedance.larkoffice.com/docx/KlW9dIlyzo17ccxl26Gc9TGsnig
  - `kref_fff0c1de1ed47e49` MeetFlow M3 会前知识卡片方案 score=`0.48` url=https://example.feishu.cn/docx/workflow_demo_m3_rag

## 7. 写入结果

- created_tasks: `0`
- skipped_tasks: `1`
  - `action_a0376dc045f8` reason=缺少截止时间；置信度低于阈值 0.75
- sent_cards: `2`
  - summary_card: status=`success`, message_id=`om_x100b506fa7f838b0b29aafdf40606b2`, chat_id=`oc_3e432398cc43063fda2b2d322bb6dead`
  - pending_button_card: status=`success`, message_id=`om_x100b506fa7f0b4a0b2d55d334c7054f`, chat_id=`oc_3e432398cc43063fda2b2d322bb6dead`

## 8. 结论

本次发送 2 张卡片；1 个 Action Item 进入待确认，未自动创建任务。
