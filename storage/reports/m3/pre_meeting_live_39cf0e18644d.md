# M3 会前知识卡片真实联调报告

## 1. 会议输入

- event_id: `b9c6ca7b-c1dd-4f1a-b995-edf71f3faa7c_0`
- 标题: 飞书 AI 校园竞赛-主题分享直播-产品专场
- 开始时间: `1777456800`
- 结束时间: `1777460400`
- 参会人数: `1`
- allow_write: `False`

## 2. 工作流阶段

```text
真实日历会议 -> 真实文档读取 -> 文档清洗与 chunk -> 向量/关键词索引 -> meeting.soon -> PreMeetingBriefWorkflow -> knowledge.search -> 会前卡片草案
```

## 3. 检索 Query

```json
{
  "meeting_id": "b9c6ca7b-c1dd-4f1a-b995-edf71f3faa7c_0",
  "calendar_event_id": "b9c6ca7b-c1dd-4f1a-b995-edf71f3faa7c_0",
  "project_id": "meetflow",
  "meeting_title": "飞书 AI 校园竞赛-主题分享直播-产品专场",
  "meeting_description": "",
  "entities": [
    "飞书",
    "AI",
    "校园竞赛-主题分享直播-产品专场",
    "校园挑战赛-线上开赛仪式",
    "Trae",
    "IDE",
    "模型配置指南"
  ],
  "attendee_names": [
    "F39-08🎦[应急会议室](14) Shenzhen Bay I&T Center B(深圳湾创新科技中心B座)"
  ],
  "attachment_titles": [
    "飞书 AI 校园挑战赛-线上开赛仪式",
    "Trae IDE 模型配置指南"
  ],
  "related_resource_titles": [
    "飞书 AI 校园挑战赛-线上开赛仪式",
    "Trae IDE 模型配置指南"
  ],
  "resource_types": [
    "doc",
    "sheet",
    "minute",
    "task"
  ],
  "time_window": "recent_90_days",
  "search_queries": [
    "飞书 AI 校园竞赛-主题分享直播-产品专场",
    "meetflow",
    "飞书",
    "AI",
    "校园竞赛-主题分享直播-产品专场",
    "校园挑战赛-线上开赛仪式",
    "Trae",
    "IDE",
    "模型配置指南",
    "飞书 AI 校园挑战赛-线上开赛仪式",
    "Trae IDE 模型配置指南",
    "飞书 AI 校园竞赛-主题分享直播-产品专场 校园挑战赛-线上开赛仪式 Trae IDE 模型配置指南",
    "飞书 AI 校园挑战赛-线上开赛仪式 Trae IDE 模型配置指南",
    "F39-08🎦[应急会议室](14) Shenzhen Bay I&T Center B(深圳湾创新科技中心B座)"
  ],
  "confidence": 0.95,
  "missing_context": [],
  "extra": {
    "identified_topic": "飞书 AI 校园竞赛-主题分享直播-产品专场",
    "topic_signal": {
      "topic": "飞书 AI 校园竞赛-主题分享直播-产品专场",
      "candidate_projects": [
        {
          "project_id": "meetflow",
          "name": "meetflow",
          "score": 0.1,
          "matched_signals": [
            "project_id:meetflow"
          ],
          "source": "memory"
        }
      ],
      "business_entities": [
        "飞书",
        "AI",
        "校园竞赛-主题分享直播-产品专场",
        "校园挑战赛-线上开赛仪式",
        "Trae",
        "IDE",
        "模型配置指南"
      ],
      "attendee_signals": [
        "F39-08🎦[应急会议室](14) Shenzhen Bay I&T Center B(深圳湾创新科技中心B座)"
      ],
      "confidence": 0.9099999999999999,
      "missing_context": [],
      "query_hints": [
        "飞书 AI 校园竞赛-主题分享直播-产品专场",
        "meetflow",
        "飞书",
        "AI",
        "校园竞赛-主题分享直播-产品专场",
        "校园挑战赛-线上开赛仪式",
        "Trae",
        "IDE",
        "模型配置指南",
        "飞书 AI 校园挑战赛-线上开赛仪式",
        "Trae IDE 模型配置指南"
      ],
      "needs_confirmation": false,
      "reason": "候选项目 meetflow 命中 project_id:meetflow；识别到实体 飞书, AI, 校园竞赛-主题分享直播-产品专场, 校园挑战赛-线上开赛仪式, Trae"
    },
    "start_time": "1777456800",
    "end_time": "1777460400",
    "timezone": "",
    "organizer": ""
  }
}
```

## 4. 索引资源与 Chunk

### 飞书 AI 校园挑战赛-线上开赛仪式

- resource_id: `Eq0ywVPwdirCLakfBeucCwKWnoh`
- resource_type: `feishu_document`
- source_url: https://bytedance.larkoffice.com/wiki/Eq0ywVPwdirCLakfBeucCwKWnoh
- chunk_count: `13`（可检索子 chunk `13`，父级上下文 chunk `0`）

#### 可检索子 Chunk

##### child `1`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_1_cd6826a2fa4e`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `132`
- source_locator: `doc:chunk:1`
- toc_path: `['开赛仪式流程总览']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '开赛仪式流程总览', '飞书介绍', '6–8min', '飞书是什么？飞书', '相关产品介绍', '赛事介绍', '参赛收获、赛程安排、赛事支持', '技术嘉宾分享', '25min']`

```text
开赛仪式流程总览
飞书介绍（6–8min） ：飞书是什么？飞书 AI 相关产品介绍
赛事介绍（6–8min） ：参赛收获、赛程安排、赛事支持
技术嘉宾分享（约 25min） ：《飞书 AI-friendly 分享》飞书技术专家@黄同学
资源与环境配置（10min） ：资源领取方式、开发环境配置、个人阶段成果小结/提交流程
Q&A（5–10min） ：集中答疑 + 会后渠道说明
```

##### child `2`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_2_691b68029dc7`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `149`
- source_locator: `doc:chunk:2`
- toc_path: `['飞书： 字节跳动旗下 AI 工作平台']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '字节跳动旗下', '工作平台', '飞书是', '时代先进生产力平台', '飞书是字节跳动旗下', '提供一站式协同办公、组织管理、业务提效工具和深入企业场景的', '能力', '真能用、真落地', '从互联网、高科技、消费零售']`

```text
飞书： 字节跳动旗下 AI 工作平台
飞书是 AI 时代先进生产力平台
飞书是字节跳动旗下 AI 工作平台，提供一站式协同办公、组织管理、业务提效工具和深入企业场景的 AI 能力，让 AI 真能用、真落地。
从互联网、高科技、消费零售，到制造、金融、医疗健康等，各行各业先进企业都在选择飞书，与飞书共创行业最佳实践。先进团队，先用飞书。
```

##### child `3`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_3_50e65505cb1e`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `497`
- source_locator: `doc:chunk:3`
- toc_path: `['🚀 飞书，让每个人都拥有自己的 AI 智能伙伴']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '让每个人都拥有自己的', '智能伙伴', '时代', '我们正在重新定义「办公」。以下是飞书最新释放的', '能力', '也是这次挑战赛你们可以尽情探索的"武器库"👇', '🧠ai', '原生体验', '飞书已就绪']`

```text
🚀 飞书，让每个人都拥有自己的 AI 智能伙伴
在 AI 时代，我们正在重新定义「办公」。以下是飞书最新释放的 AI 能力，也是这次挑战赛你们可以尽情探索的"武器库"👇
🧠AI 原生体验，飞书已就绪
1. 飞书知识问答 —— 企业的"AI 大脑"，一问即答👉 了解详情
2. 飞书智能会议纪要 全新升级 —— 纪要图文并茂，图表画龙点睛👉 了解详情
3. 多维表格 · AI 系统搭建 —— 懂业务、会执行、能落地，为每个想法搭好一套系统👉 了解详情
🛠️ 飞书开发套件 —— 从"用 AI"到"造 AI"
飞书开发套件正式发布！包含三大核心产品，总览请看 👉 飞书开发套件详情
4. 飞书 aily —— 每个人的智能伙伴，好上手、超能干、更放心👉 立即访问 或在飞书搜索「aily」
5. 飞书 aily 专业版 —— 复杂任务的专业伙伴，创作可视化，更强更可控👉 立即访问
6. 飞书妙搭 —— 懂开发的智能伙伴，业务系统"当天想、当天用"👉 立即访问 或在 aily 专业版中点击「开发应用」
💻 工程师最爱 · OpenClaw 插件
7. OpenClaw 飞书官方插件 —— 工程师首选...
```

##### child `4`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_4_4afac6ed53b3`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `203`
- source_locator: `doc:chunk:4`
- toc_path: `['「飞书 AI 校园挑战赛」-赛事介绍']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '「飞书', '校园挑战赛」-赛事介绍', '飞书打造的', '实战挑战赛', '面向全国高校学生开放', '立足真实', '办公业务场景', '搭建实战平台', '大赛聚焦']`

```text
「飞书 AI 校园挑战赛」-赛事介绍
飞书打造的 AI 实战挑战赛，面向全国高校学生开放，立足真实 AI 办公业务场景，搭建实战平台。
大赛聚焦 AI 的场景化应用落地，设置多元赛道：既深耕飞书生态内的办公协同、业务提效实践，也鼓励面向全域场景的 AI 创新探索。
在 AI 能力快速迭代、产业深度融合的背景下，本次挑战赛旨在助力参赛者完成从创意构想到项目落地的全流程实践，打造可运行、可验证的 AI 实战成果，让 AI 切实解决真实问题、创造可持续的产业价值。
```

##### child `5`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_5_3171c11358a3`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `149`
- source_locator: `doc:chunk:5`
- toc_path: `['「飞书 AI 校园挑战赛」-赛事介绍', '参加本次大赛，你能获得什么？']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '参加本次大赛', '你能获得什么？', '同学', '优秀选手可获得校招实习', '校招正式', 'offer', '机会', '赛事全程提供免费开发资源', '火山方舟']`

```text
参加本次大赛，你能获得什么？
同学：
优秀选手可获得校招实习 / 校招正式 Offer 机会
赛事全程提供免费开发资源（火山方舟 Coding 豪华套餐 + 飞书 API 无限调用额度）
获奖可瓜分 8 万元总现金奖池，赢取字节 AI 全家桶会员 （一等奖可获得 2 万元现金；字节 Al 全家桶涵盖火山引擎 ArkClaw、即梦 AI、剪映、扣子、飞书 AI、即创，全场景 智能能力一站集齐）
```

##### child `6`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_6_d0a24cf039b1`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `72`
- source_locator: `doc:chunk:6`
- toc_path: `['「飞书 AI 校园挑战赛」-赛事介绍', '赛事整体的安排是什么样的？']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '赛事整体的安排是什么样的？', '校园挑战赛时间', '22', '-5', '14', '*以上时间为预计时间', '若有调整', '项目组会及时与同学们在飞书赛事', '初赛']`

```text
赛事整体的安排是什么样的？
飞书 AI 校园挑战赛时间： 4 月 22 日 -5 月 14 日
*以上时间为预计时间，若有调整，项目组会及时与同学们在飞书赛事（初赛）总群同步。
```

##### child `7`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_7_540bb67f37e1`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `103`
- source_locator: `doc:chunk:7`
- toc_path: `['「飞书 AI 校园挑战赛」-赛事介绍', '你需要做什么 & 我们为你提供什么支持', '你需要做到：']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '你需要做到', '你需要做什么', '我们为你提供什么支持', '全情投入', '把赛事当作', '真实项目实践', '不敷衍、不应付', '主动学习、动手实践', '高标准完成课题开发']`

```text
你需要做什么 & 我们为你提供什么支持
你需要做到：
全情投入，把赛事当作 真实项目实践 ，不敷衍、不应付。
主动学习、动手实践，高标准完成课题开发。
积极参与群内讨论、直播分享、个人阶段成果小结填写，充分展示自己的能力。
```

##### child `8`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_8_9fb3922cd82c`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `91`
- source_locator: `doc:chunk:8`
- toc_path: `['「飞书 AI 校园挑战赛」-赛事介绍', '你需要做什么 & 我们为你提供什么支持', '我们为你提供：']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '我们为你提供', '技术专家全程担任项目观察员', '群内实时答疑、初赛进度观察、复赛中期验收', '专业', 'hr', '全程陪伴', '为同学提供字节跳动', '飞书校招投递咨询', '覆盖']`

```text
我们为你提供：
技术专家全程担任项目观察员，群内实时答疑、初赛进度观察、复赛中期验收
专业 HR 全程陪伴：为同学提供字节跳动 & 飞书校招投递咨询，覆盖 投递/流程答疑、关键节点提醒 与常见问题解答
```

##### child `9`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_9_22216437d483`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `85`
- source_locator: `doc:chunk:9`
- toc_path: `['「飞书 AI 校园挑战赛」-赛事介绍', '你需要做什么 & 我们为你提供什么支持', '重要提醒：请勿中途退赛']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '重要提醒', '请勿中途退赛', '中途退赛会影响团队进度与整体项目产出', '请提前规划好未来', '个月的时间', '保证充足精力投入', '无特殊情况随意退赛', '无法参与后续飞书任何赛事', '训练营类项目']`

```text
重要提醒：请勿中途退赛
中途退赛会影响团队进度与整体项目产出。
请提前规划好未来 1 个月的时间，保证充足精力投入。
无特殊情况随意退赛，将 无法参与后续飞书任何赛事 / 训练营类项目 。
```

##### child `10`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_10_66114798cbc6`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `288`
- source_locator: `doc:chunk:10`
- toc_path: `['飞书技术嘉宾主题分享——《飞书 AI-friendly 分享》（嘉宾：黄梦轩）']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '飞书技术嘉宾主题分享——《飞书', 'ai-friendly', '分享》', '嘉宾', '黄梦轩', '在进入实战赛道之前', '我们先用一段', '技术嘉宾分享', '帮助大家建立对“飞书为什么是']`

```text
飞书技术嘉宾主题分享——《飞书 AI-friendly 分享》（嘉宾：黄梦轩）
在进入实战赛道之前，我们先用一段 技术嘉宾分享 ，帮助大家建立对“飞书为什么是 AI-friendly”的整体认知：
AI 时代做一个真正有价值的应用，不只是“多一个能回答问题的入口”，更关键是 能调用平台能力、参与协作、形成闭环 。
在飞书的协作与业务场景里，哪些能力最适合与 Agent / MCP / 工具调用结合？
从“想法”到“可运行 demo”，如何更高效地推进？
嘉宾介绍｜黄梦轩
飞书研发工程师（Lark App-Core Services）
大三开始在飞书实习，校招加入飞书至今约 6 年
当前主要负责：飞书面向 AI 的开放性与友好能力建设（包含飞书 MCP / CLI 等方向的实践）
嘉宾 PPT（演示入口）
嘉宾 PPT： https://bytedance.larkoffice.com/wiki/SuPrw0FRhi1Ctmkh2IUcA1fxnQc
```

##### child `11`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_11_8f7f9baacf81`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `528`
- source_locator: `doc:chunk:11`
- toc_path: `['赛事资源 & 开发环境配置']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '赛事资源', '开发环境配置', '我们提供哪些', '开发资源', '统一', '环境', '需要同学侧做什么？', '相关文档链接', '大模型']`

```text
赛事资源 & 开发环境配置
我们提供哪些 开发资源/ 统一 环境 ？
需要同学侧做什么？
相关文档链接
大模型 Token
版本：Doubao 1.6
额度：单人 TPM 1w
1、自助认领 EP
2、输入 EP、模型 ID（Doubao 1.6）以及 API Key 后，完成 Trae IDE 模型配置（当天内完成）。
图片：image.png（src: KXIlb0ct7o65mJxDChXcKmXCnad）
认领入口：
丰富 的飞书 AI 资源：
1、飞书 API 调用额度（不限）
2、飞书妙搭（AI Coding 工具）
官网链接： miaoda.feishu.cn
介绍文档：
3、飞书 OpenClaw 一键部署
官网链接： openclaw.feishu.cn
介绍文档：
加入飞书商业版租户后即可免费享用；各团队根据情况自由取需。
过程中如果额度不够，可联系项目组同学。
GitHub 代码仓库
1、各组为一个单位，创建自己的 GitHub 代码仓库（当天内完成）。
2、 Github 的项目可见性需要设置成public。
3、将仓库链接填写到信息收集问卷中。
问卷链接🔗：h...
```

##### child `12`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_12_4ab0dac2fcd2`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `560`
- source_locator: `doc:chunk:12`
- toc_path: `['常见问题答疑：']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '常见问题答疑', '问题', '大赛最终的', '校招', '实习', '校招正式', 'offer', '机会是怎么评估的？', '回答']`

```text
常见问题答疑：
问题 1： 大赛最终的 校招 实习/ 校招正式 offer 机会是怎么评估的？
回答：这个问题确实是大家比较关心提及次数较多的，先给大家吃个定心丸：Offer 机会 不与决赛排名强绑定 。而是综合评估大家在整个赛事过程中的表现、最终作品成果，每周提交的 ，结合赛事过程中由飞书专家成员组成的-观察员的综合评价，只要足够优秀，就能获得实习/校招正式offer 机会～
问题 2 ：如果有实习机会，会是产品岗位还是技术岗位呀？
回答：本次大赛全程会有观察员跟进大家的表现并提供指导。后续若获得实习机会，具体岗位方向（技术/产品/设计等），我们会结合你在赛事中的 实际表现、个人优势与对应岗位需求 综合确定，目前暂无法提前锁定。建议大家先在赛事里全力投入、充分展示自己就好～如果自己有明确的职位方向诉求，也可以在过程中与观察员、跟进的HR 同学进行随时的反馈，我们将为同学做好信息登记。
问题 3：请问决赛的时间有确定吗，会改动吗？
回答：决赛时间目前定在 5 月 14 日（星期四），形式是线上路演。如果后续有任何特殊情况需要调整，我们一定会第一时间提前在赛事群里通知大家，绝对给足大家准...
```

##### child `13`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_13_4f65c53cb635`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `374`
- source_locator: `doc:chunk:13`
- toc_path: `['抽奖环节']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '抽奖环节', '开赛福利抽奖来啦！', '本次我们为同学们准备了三款超实用的字节文创周边', '快把好运刷起来！', '请直播间的同学们', '在评论区统一刷出我们的赛事名称', '需要确保文字无误', '否则将视为无效弹幕', '顺位至第二位截图的同学']`

```text
抽奖环节
🎁 开赛福利抽奖来啦！
本次我们为同学们准备了三款超实用的字节文创周边，快把好运刷起来！
请直播间的同学们，在评论区统一刷出我们的赛事名称（需要确保文字无误，否则将视为无效弹幕，顺位至第二位截图的同学）：飞书 AI 校园挑战赛
稍后我会倒数3个数，数到1的时候，主持人会现场随机截屏抽奖，中奖的同学记得第一时间联系赛事工作人员 核验身份，并把邮寄信息发给 ，奖品会统一采购寄送到你手上！
抽奖数量
礼品名称
礼品图
礼品亮点
1份
抖音文创 OTM 系列带电脑隔层轻量双肩包
图片：image.png（src: ZYrFbxjNJo6PxJxL4W9cOoWQn2f）
内置电脑隔层，大容量超能装，上课 / 实习 / 通勤一包搞定
1 份
抖音文创「OTM」系列-自带插头自带线充电宝
图片：image.png（src: HBfYb2yyVoo0XBx8YZGcsKeLn0B）
自带插头与充电线，即插即充，便携实用
1 份
汽水音乐 复古磁带造型充电宝（自带双线快充移动电源）
图片：image.png（src: SiJbbmKCMoT0N7xvoDWck2uXnqc）
复古磁带造型，自...
```

### Trae IDE 模型配置指南

- resource_id: `KlW9dIlyzo17ccxl26Gc9TGsnig`
- resource_type: `feishu_document`
- source_url: https://bytedance.larkoffice.com/docx/KlW9dIlyzo17ccxl26Gc9TGsnig
- chunk_count: `7`（可检索子 chunk `7`，父级上下文 chunk `0`）

#### 可检索子 Chunk

##### child `1`

- chunk_id: `KlW9dIlyzo17ccxl26Gc9TGsnig#chunk_1_37aa82bdd82a`
- chunk_type: `paragraph`
- parent_chunk_id: ``
- content_tokens: `75`
- source_locator: `doc:chunk:1`
- toc_path: `['Trae IDE 模型配置指南']`
- keywords: `['trae', 'ide', '模型配置指南', '背景介绍', '本指南旨在帮助同学们快速掌握在', '中配置自定义大语言模型', 'llm', '的方法。通过配置自定义模型', '你可以根据学习需求灵活切换不同的', 'ai', '服务', '提升编程效率']`

```text
背景介绍 本指南旨在帮助同学们快速掌握在 Trae IDE 中配置自定义大语言模型（LLM）的方法。通过配置自定义模型，你可以根据学习需求灵活切换不同的 AI 服务，提升编程效率。
```

##### child `2`

- chunk_id: `KlW9dIlyzo17ccxl26Gc9TGsnig#chunk_2_00400102f724`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `123`
- source_locator: `doc:chunk:2`
- toc_path: `['1. 准备工作']`
- keywords: `['trae', 'ide', '模型配置指南', '准备工作', '在开始配置之前', '请确保你已经从指导老师或相关平台获取了以下三项关键信息', '接入点', 'endpoint', '在这里是服务商', '选火山引擎-自定义模型即可', '模型', 'id']`

```text
1. 准备工作
在开始配置之前，请确保你已经从指导老师或相关平台获取了以下三项关键信息：
接入点 (Endpoint) 在这里是服务商，选火山引擎-自定义模型即可
模型 ID (Model ID) 你想要使用的具体模型名称（如 gpt-4o , claude-3-5-sonnet 等）。
API Key 用于身份验证的密钥，请务必妥善保管，不要泄露。
```

##### child `3`

- chunk_id: `KlW9dIlyzo17ccxl26Gc9TGsnig#chunk_3_329f7db97c61`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `21`
- source_locator: `doc:chunk:3`
- toc_path: `['2. 配置步骤']`
- keywords: `['trae', 'ide', '模型配置指南', '配置步骤', '请按照以下步骤在', '中进行操作']`

```text
2. 配置步骤
请按照以下步骤在 Trae IDE 中进行操作：
```

##### child `4`

- chunk_id: `KlW9dIlyzo17ccxl26Gc9TGsnig#chunk_4_e0af38db84b3`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `60`
- source_locator: `doc:chunk:4`
- toc_path: `['2. 配置步骤', '步骤一：打开设置界面']`
- keywords: `['trae', 'ide', '模型配置指南', '步骤一', '打开设置界面', '打开', '在界面左下角找到并点击', '“设置”', 'settings', '图标', '齿轮形状', '或者使用快捷键']`

```text
步骤一：打开设置界面
打开 Trae IDE，在界面左下角找到并点击 “设置” (Settings) 图标（齿轮形状），或者使用快捷键 Ctrl + , (Windows/Linux) 或 Cmd + , (macOS)。
```

##### child `5`

- chunk_id: `KlW9dIlyzo17ccxl26Gc9TGsnig#chunk_5_a8f48635ff30`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `35`
- source_locator: `doc:chunk:5`
- toc_path: `['2. 配置步骤', '步骤二：进入模型配置']`
- keywords: `['trae', 'ide', '模型配置指南', '步骤二', '进入模型配置', '在设置页面的左侧导航栏中', '点击', '“模型”', 'model', '选项卡']`

```text
步骤二：进入模型配置
在设置页面的左侧导航栏中，点击 “模型” (Model) 选项卡。
```

##### child `6`

- chunk_id: `KlW9dIlyzo17ccxl26Gc9TGsnig#chunk_6_2a3af4e72d6b`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `197`
- source_locator: `doc:chunk:6`
- toc_path: `['2. 配置步骤', '步骤三：添加并配置自定义模型']`
- keywords: `['trae', 'ide', '模型配置指南', '步骤三', '添加并配置自定义模型', '在模型配置界面中', '找到“自定义模型”或“添加模型”按钮', '并根据提示填入你准备好的信息', 'endpoint', '选择火山引擎', '自定义模型', 'model']`

```text
步骤三：添加并配置自定义模型
在模型配置界面中，找到“自定义模型”或“添加模型”按钮，并根据提示填入你准备好的信息：
Endpoint : 选择火山引擎 - 自定义模型
Model ID : 填入对应的模型标识符。（请用自行认领的 ）
API Key : 填入导师提供的 API key。（ ）
注意，以上配置信息仅用于本次活动，活动结束后将会收回。请保存好不要外泄，信息安全你我共建
图片：image.png（src: CdwGb1Hs1olfqzxJWxFc5Mk3nkb）
提示： 填写完成后，请确保点击“保存”或“应用”按钮以生效配置。
```

##### child `7`

- chunk_id: `KlW9dIlyzo17ccxl26Gc9TGsnig#chunk_7_3a000ebb4a8b`
- chunk_type: `section`
- parent_chunk_id: ``
- content_tokens: `173`
- source_locator: `doc:chunk:7`
- toc_path: `['3. 测试与确认']`
- keywords: `['trae', 'ide', '模型配置指南', '测试与确认', '配置完成后', '你可以通过以下方式验证是否成功', '打开', 'ai', '聊天窗口', 'chat', '在模型下拉菜单中选择你刚刚配置的', '自定义模型']`

```text
3. 测试与确认
配置完成后，你可以通过以下方式验证是否成功：
打开 Trae IDE 的 AI 聊天窗口 (Chat)。
在模型下拉菜单中选择你刚刚配置的 自定义模型 。
输入一个简单的问题（例如：“你好，请介绍一下你自己”），观察模型是否能正常回复。
如果模型能够流畅回答，说明你的配置已经成功！
遇到问题？ 如果你在配置过程中遇到报错，请首先检查 Endpoint 是否填写完整（包含 https://），以及 API Key 是否有余量或已过期。
```

## 5. 工具检索结果

## 6. 卡片 Payload 草案

```json
{
  "title": "MeetFlow 会前背景卡：飞书 AI 校园竞赛-主题分享直播-产品专场",
  "summary": "围绕 飞书 AI 校园竞赛-主题分享直播-产品专场，已召回 2 条相关资料。会前待读资料：飞书 AI 校园挑战赛-线上开赛仪式、Trae IDE 模型配置指南。",
  "facts": [
    {
      "label": "会议主题",
      "value": "飞书 AI 校园竞赛-主题分享直播-产品专场"
    },
    {
      "label": "背景摘要",
      "value": "围绕 飞书 AI 校园竞赛-主题分享直播-产品专场，已召回 2 条相关资料。会前待读资料：飞书 AI 校园挑战赛-线上开赛仪式、Trae IDE 模型配置指南。"
    },
    {
      "label": "置信度",
      "value": "0.95"
    },
    {
      "label": "待读资料",
      "value": "飞书 AI 校园挑战赛-线上开赛仪式；Trae IDE 模型配置指南"
    }
  ],
  "sections": [
    {
      "key": "last_decisions",
      "title": "上次结论",
      "empty": "暂无明确结论",
      "items": []
    },
    {
      "key": "current_questions",
      "title": "当前问题",
      "empty": "暂无待确认问题",
      "items": []
    },
    {
      "key": "risks",
      "title": "风险点",
      "empty": "暂无显著风险",
      "items": []
    },
    {
      "key": "must_read_resources",
      "title": "待读资料",
      "empty": "暂无必读资料",
      "items": [
        {
          "title": "飞书 AI 校园挑战赛-线上开赛仪式",
          "content": "<title>飞书 AI 校园挑战赛-线上开赛仪式</title><h1>开赛仪式流程总览</h1><ol><li><b>飞书介绍（6–8min）</b>：飞书是什么？飞书 AI 相关产品介绍</li><li><b>赛事介绍（6–8min）</b>：参赛收获、赛程安排、赛事支持</li><li><b>技术嘉宾分享（约 25min）</b>：《飞书 AI-friendly 分享》飞书技术专家@黄同学</li><li><b>资源与环境配置（10min）</b>：资源领取方式、开发\n召回原因：命中检索词:飞书；命中检索词:AI；命中检索词:校园挑战赛-线上开赛仪式",
          "ref_id": "Eq0ywVPwdirCLakfBeucCwKWnoh"
        },
        {
          "title": "Trae IDE 模型配置指南",
          "content": "<title>Trae IDE 模型配置指南</title><callout emoji=\"💡\"><p><b>背景介绍</b><br/>本指南旨在帮助同学们快速掌握在 Trae IDE 中配置自定义大语言模型（LLM）的方法。通过配置自定义模型，你可以根据学习需求灵活切换不同的 AI 服务，提升编程效率。</p></callout><h3>1. 准备工作</h3><p>在开始配置之前，请确保你已经从指导老师或相关平台获取了以下三项关键信息：</p><grid><column \n召回原因：命中检索词:AI；命中检索词:Trae；命中检索词:IDE",
          "ref_id": "KlW9dIlyzo17ccxl26Gc9TGsnig"
        }
      ]
    },
    {
      "key": "possible_related_resources",
      "title": "可能相关资料",
      "empty": "暂无候选资料",
      "items": []
    }
  ],
  "card": {
    "config": {
      "wide_screen_mode": true
    },
    "header": {
      "template": "green",
      "title": {
        "tag": "plain_text",
        "content": "MeetFlow 会前背景卡：飞书 AI 校园竞赛-主题分享直播-产品专场"
      }
    },
    "elements": [
      {
        "tag": "markdown",
        "content": "**主题**：飞书 AI 校园竞赛-主题分享直播-产品专场\n**状态**：可参考  |  **置信度**：0.95\n**背景摘要**：围绕 飞书 AI 校园竞赛-主题分享直播-产品专场，已召回 2 条相关资料。会前待读资料：飞书 AI 校园挑战赛-线上开赛仪式、Trae IDE 模型配置指南。"
      },
      {
        "tag": "hr"
      },
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "**待读资料**\n1. 飞书 AI 校园挑战赛-线上开赛仪式：<title>飞书 AI 校园挑战赛-线上开赛仪式</title><h1>开赛仪式流程总览</h1><ol><li><b>飞书介绍（6–8min）</b>：飞书是什么？飞书 AI 相关产品介绍</li><li><b>赛事介绍（6–8min）</b>：参赛收获、赛程安排、赛事支持</li><li><b>技术嘉宾分享（约 25min）</b>：《飞书 AI-friendly 分享》飞书技术专家@黄同学</li><li><b>资源与环境配置（10min）</b>：资源领取方式、开发\n召回原因：命中检索词:飞书；命中检索词:AI；命中检索词:校园挑战赛-线上开赛仪式 `Eq0ywVPwdirCLakfBeucCwKWnoh`\n2. Trae IDE 模型配置指南：<title>Trae IDE 模型配置指南</title><callout emoji=\"💡\"><p><b>背景介绍</b><br/>本指南旨在帮助同学们快速掌握在 Trae IDE 中配置自定义大语言模型（LLM）的方法。通过配置自定义模型，你可以根据学习需求灵活切换不同的 AI 服务，提升编程效率。</p></callout><h3>1. 准备工作</h3><p>在开始配置之前，请确保你已经从指导老师或相关平台获取了以下三项关键信息：</p><grid><column \n召回原因：命中检索词:AI；命中检索词:Trae；命中检索词:IDE `KlW9dIlyzo17ccxl26Gc9TGsnig`"
        }
      },
      {
        "tag": "hr"
      },
      {
        "tag": "markdown",
        "content": "**证据引用**\n- `Eq0ywVPwdirCLakfBeucCwKWnoh` doc：<title>飞书 AI 校园挑战赛-线上开赛仪式</title><h1>开赛仪式流程总览</h1><ol><li><b>飞书介绍（6–8min）</b>：飞书\n- `KlW9dIlyzo17ccxl26Gc9TGsnig` doc：<title>Trae IDE 模型配置指南</title><callout emoji=\"💡\"><p><b>背景介绍</b><br/>本指南旨在帮助同学们快速"
      }
    ]
  },
  "source_meeting_id": "b9c6ca7b-c1dd-4f1a-b995-edf71f3faa7c_0",
  "idempotency_key": "pre_meeting_brief:b9c6ca7b-c1dd-4f1a-b995-edf71f3faa7c_0"
}
```

## 7. Agent 最终结果

- status: `failed`
- trace_id: `39cf0e18644d`

```text
Agent Loop 执行失败：LLM api_base 为空，请在配置或环境变量中设置 MEETFLOW_LLM_API_BASE
```
