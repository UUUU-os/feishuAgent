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
    "校园挑战赛-线上开赛仪式"
  ],
  "attendee_names": [
    "F39-08🎦[应急会议室](14) Shenzhen Bay I&T Center B(深圳湾创新科技中心B座)"
  ],
  "attachment_titles": [
    "飞书 AI 校园挑战赛-线上开赛仪式"
  ],
  "related_resource_titles": [
    "飞书 AI 校园挑战赛-线上开赛仪式"
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
    "飞书 AI 校园挑战赛-线上开赛仪式",
    "飞书 AI 校园竞赛-主题分享直播-产品专场 校园挑战赛-线上开赛仪式",
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
        "校园挑战赛-线上开赛仪式"
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
        "飞书 AI 校园挑战赛-线上开赛仪式"
      ],
      "needs_confirmation": false,
      "reason": "候选项目 meetflow 命中 project_id:meetflow；识别到实体 飞书, AI, 校园竞赛-主题分享直播-产品专场, 校园挑战赛-线上开赛仪式"
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
- chunk_count: `2`

#### chunk `0`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#parent_c21aa3900278`
- chunk_type: `parent_section`
- parent_chunk_id: ``
- content_tokens: `4554`
- source_locator: `doc:chunk:1`
- toc_path: `['doc']`
- keywords: `['<title>飞书', 'ai', '校园挑战赛-线上开赛仪式<', 'title><h1>开赛仪式流程总览<', 'h1><ol><li><b>飞书介绍', '6–8min', 'b>', '飞书是什么？飞书', '相关产品介绍<', 'li><li><b>赛事介绍', '参赛收获、赛程安排、赛事支持<', 'li><li><b>技术嘉宾分享']`

```text
<title>飞书 AI 校园挑战赛-线上开赛仪式</title><h1>开赛仪式流程总览</h1><ol><li><b>飞书介绍（6–8min）</b>：飞书是什么？飞书 AI 相关产品介绍</li><li><b>赛事介绍（6–8min）</b>：参赛收获、赛程安排、赛事支持</li><li><b>技术嘉宾分享（约 25min）</b>：《飞书 AI-friendly 分享》飞书技术专家@黄同学</li><li><b>资源与环境配置（10min）</b>：资源领取方式、开发环境配置、个人阶段成果小结/提交流程</li><li><b>Q&amp;A（5–10min）</b>：集中答疑 + 会后渠道说明</li></ol><p></p><h1 seq="auto" seq-level="auto">飞书：<b>字节跳动旗下 AI 工作平台</b></h1><hr/><p><b>飞书是 AI 时代先进生产力平台</b><blockquote><p><b>飞书是字节跳动旗下 AI 工作平台，提供一站式协同办公、组织管理、业务提效工具和深入企业场景的 AI 能力，让 AI 真能用、真落地。</...
```

#### chunk `1`

- chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_1_f393702e8088`
- chunk_type: `paragraph`
- parent_chunk_id: `Eq0ywVPwdirCLakfBeucCwKWnoh#parent_c21aa3900278`
- content_tokens: `4554`
- source_locator: `doc:chunk:1`
- toc_path: `['doc']`
- keywords: `['飞书', 'ai', '校园挑战赛-线上开赛仪式', '<title>飞书', '校园挑战赛-线上开赛仪式<', 'title><h1>开赛仪式流程总览<', 'h1><ol><li><b>飞书介绍', '6–8min', 'b>', '飞书是什么？飞书', '相关产品介绍<', 'li><li><b>赛事介绍']`

```text
<title>飞书 AI 校园挑战赛-线上开赛仪式</title><h1>开赛仪式流程总览</h1><ol><li><b>飞书介绍（6–8min）</b>：飞书是什么？飞书 AI 相关产品介绍</li><li><b>赛事介绍（6–8min）</b>：参赛收获、赛程安排、赛事支持</li><li><b>技术嘉宾分享（约 25min）</b>：《飞书 AI-friendly 分享》飞书技术专家@黄同学</li><li><b>资源与环境配置（10min）</b>：资源领取方式、开发环境配置、个人阶段成果小结/提交流程</li><li><b>Q&amp;A（5–10min）</b>：集中答疑 + 会后渠道说明</li></ol><p></p><h1 seq="auto" seq-level="auto">飞书：<b>字节跳动旗下 AI 工作平台</b></h1><hr/><p><b>飞书是 AI 时代先进生产力平台</b><blockquote><p><b>飞书是字节跳动旗下 AI 工作平台，提供一站式协同办公、组织管理、业务提效工具和深入企业场景的 AI 能力，让 AI 真能用、真落地。</...
```

## 5. 工具检索结果

### knowledge.search `success`

```json
{
  "query": "MeetFlow M3 会前知识卡片",
  "hits": [
    {
      "ref_id": "kref_7c4d5148301e66f3",
      "chunk_id": "D067w8sC4iYsjjk7nnAcMEXqnwb#chunk_1_3bdc5fd45f83",
      "document_id": "D067w8sC4iYsjjk7nnAcMEXqnwb",
      "source_type": "doc",
      "title": "李健文-个人阶段小结",
      "snippet": "<title>李健文-个人阶段小结</title><h1>第一周期（4.23-4.25）</h1><h3>一、核心产出 （必填）</h3><p><em>本周期你交付的最满意的一项成果是什么？</em></p><blockquote><p><...",
      "reason": "混合命中 final_score:0.370；向量召回:0.47；命中查询词:meetflow；包含回链定位；包含来源链接；关键词召回:0.23；命中查询词:meetflow；包含回链定位；包含来源链接",
      "score": 0.37,
      "vector_similarity": 0.465,
      "term_similarity": 0.227,
      "rerank_score": 0.0,
      "final_score": 0.37,
      "source_url": "https://jcneyh7qlo8i.feishu.cn/wiki/D067w8sC4iYsjjk7nnAcMEXqnwb",
      "source_locator": "doc:chunk:1",
      "parent_chunk_id": "D067w8sC4iYsjjk7nnAcMEXqnwb#parent_92e5dc10cf8f",
      "toc_path": [
        "doc"
      ],
      "updated_at": "510",
      "metadata": {
        "document_id": "HjZ7dtVXao5Decxc6f5czWYUn81",
        "revision_id": 510,
        "doc_format": "xml",
        "detail": "simple",
        "scope": "full",
        "content_length": 5808,
        "content_excerpt": "李健文-个人阶段小结 第一周期（4.23-4.25） 一、核心产出 （必填） 本周期你交付的最满意的一项成果是什么？ 可以是一个功能、一段代码、一个工作流、一篇踩坑记录……不限形式 飞书客户端的搭建。能够通过飞书api获取到用户的日程、文档等信息。 二、量化指标 （必填） 例如：不同的 AI 使用场景、代码提交约几次、处理数据量多少、响应速度提升多少、被Star/Fork次数、接口调用次数等。 代码提交约9次，新增代码约7000行。 三、过程复盘与沉淀（必填） 这周主要搞定了哪些具体环节？用了什么方法或工具辅助？ 例如：AI 帮你做了哪些事情（跟 AI 分工）、用工具生成了接口初版代码，自己改了边界逻辑；用脚本跑了数据清洗；画了架构图；写了测试用例；设计并实现了AI工作流/插件/自动化……等等 通过描述AI的角色、项目背景等，引导AI生成了项目的 prd 文档、项目的 架构 文档，项目的 开发任务 文档。 已经构造好了项目的代码结构，实现了飞书客户端，能够获取到用户的相关信息。 过程中有没有遇到什么特别不顺、卡住很久的情况？后来是怎么破局的？ 例如：生成的内容格式总是不对、输出的结果不...",
        "embedding_provider": "sentence-transformers",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "embedding_dimensions": 512,
        "embedding_fingerprint": "sentence-transformers:BAAI/bge-small-zh-v1.5:512",
        "knowledge_namespace": "sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce",
        "vector_collection_name": "meetflow_knowledge_chunks_137933ce",
        "title": "李健文-个人阶段小结",
        "source_url": "https://jcneyh7qlo8i.feishu.cn/wiki/D067w8sC4iYsjjk7nnAcMEXqnwb",
        "source_type": "doc",
        "heading": "",
        "positions": {
          "heading": "",
          "source_type": "doc",
          "source_locator": "doc:chunk:1",
          "chunk_order": 1
        },
        "toc_path": [
          "doc"
        ],
        "keywords": [
          "李健文-个人阶段小结",
          "<title>李健文-个人阶段小结<",
          "title><h1>第一周期",
          "4.23-4.25",
          "h1><h3>一、核心产出",
          "必填",
          "h3><p><em>本周期你交付的最满意的一项成果是什么？<",
          "em><",
          "p><blockquote><p><em>可以是一个功能、一段代码、一个工作流、一篇踩坑记录……不限形式<",
          "p><",
          "blockquote><p><",
          "p><p>飞书客户端的搭建。能够通过飞书api获取到用户的日程、文档等信息。<"
        ],
        "questions": [
          "<title>李健文-个人阶段小结</title><h1>第一周期（4.23-4.25）</h1><h3>一、核心产出 （必填）</h3><p><em>本周期你交付的最满意的一项成果是什么？",
          "</p><p></p><h3>三、过程复盘与沉淀（必填）</h3><ol><li>这周主要搞定了哪些具体环节？",
          "用了什么方法或工具辅助？",
          "</p><p></p><ol><li>过程中有没有遇到什么特别不顺、卡住很久的情况？",
          "后来是怎么破局的？"
        ],
        "doc_type": "doc",
        "parent_chunk_id": "D067w8sC4iYsjjk7nnAcMEXqnwb#parent_92e5dc10cf8f"
      }
    },
    {
      "ref_id": "kref_63b20f7a78d63631",
      "chunk_id": "Eq0ywVPwdirCLakfBeucCwKWnoh#chunk_1_f393702e8088",
      "document_id": "Eq0ywVPwdirCLakfBeucCwKWnoh",
      "source_type": "doc",
      "title": "飞书 AI 校园挑战赛-线上开赛仪式",
      "snippet": "<title>飞书 AI 校园挑战赛-线上开赛仪式</title><h1>开赛仪式流程总览</h1><ol><li><b>飞书介绍（6–8min）</b>：飞书是什么？飞书 AI 相关产品介绍</li><li><b>赛事介绍（6–8min）</b...",
      "reason": "混合命中 final_score:0.320；向量召回:0.39；命中查询词:meetflow；包含回链定位；包含来源链接；关键词召回:0.23；命中查询词:meetflow；包含回链定位；包含来源链接",
      "score": 0.32,
      "vector_similarity": 0.387,
      "term_similarity": 0.227,
      "rerank_score": 0.0,
      "final_score": 0.32,
      "source_url": "https://bytedance.larkoffice.com/wiki/Eq0ywVPwdirCLakfBeucCwKWnoh",
      "source_locator": "doc:chunk:1",
      "parent_chunk_id": "Eq0ywVPwdirCLakfBeucCwKWnoh#parent_c21aa3900278",
      "toc_path": [
        "doc"
      ],
      "updated_at": "1310",
      "metadata": {
        "document_id": "Ak9dd3uUbozl3SxdhvncFEZenOf",
        "revision_id": 1310,
        "doc_format": "xml",
        "detail": "simple",
        "scope": "full",
        "content_length": 9230,
        "content_excerpt": "飞书 AI 校园挑战赛-线上开赛仪式 开赛仪式流程总览 飞书介绍（6–8min） ：飞书是什么？飞书 AI 相关产品介绍 赛事介绍（6–8min） ：参赛收获、赛程安排、赛事支持 技术嘉宾分享（约 25min） ：《飞书 AI-friendly 分享》飞书技术专家@黄同学 资源与环境配置（10min） ：资源领取方式、开发环境配置、个人阶段成果小结/提交流程 Q&A（5–10min） ：集中答疑 + 会后渠道说明 飞书： 字节跳动旗下 AI 工作平台 飞书是 AI 时代先进生产力平台 飞书是字节跳动旗下 AI 工作平台，提供一站式协同办公、组织管理、业务提效工具和深入企业场景的 AI 能力，让 AI 真能用、真落地。 从互联网、高科技、消费零售，到制造、金融、医疗健康等，各行各业先进企业都在选择飞书，与飞书共创行业最佳实践。先进团队，先用飞书。 🚀 飞书，让每个人都拥有自己的 AI 智能伙伴 在 AI 时代，我们正在重新定义「办公」。以下是飞书最新释放的 AI 能力，也是这次挑战赛你们可以尽情探索的\"武器库\"👇 🧠AI 原生体验，飞书已就绪 1. 飞书知识问答 —— 企业的\"AI 大脑...",
        "embedding_provider": "sentence-transformers",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "embedding_dimensions": 512,
        "embedding_fingerprint": "sentence-transformers:BAAI/bge-small-zh-v1.5:512",
        "knowledge_namespace": "sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce",
        "vector_collection_name": "meetflow_knowledge_chunks_137933ce",
        "title": "飞书 AI 校园挑战赛-线上开赛仪式",
        "source_url": "https://bytedance.larkoffice.com/wiki/Eq0ywVPwdirCLakfBeucCwKWnoh",
        "source_type": "doc",
        "heading": "",
        "positions": {
          "heading": "",
          "source_type": "doc",
          "source_locator": "doc:chunk:1",
          "chunk_order": 1
        },
        "toc_path": [
          "doc"
        ],
        "keywords": [
          "飞书",
          "ai",
          "校园挑战赛-线上开赛仪式",
          "<title>飞书",
          "校园挑战赛-线上开赛仪式<",
          "title><h1>开赛仪式流程总览<",
          "h1><ol><li><b>飞书介绍",
          "6–8min",
          "b>",
          "飞书是什么？飞书",
          "相关产品介绍<",
          "li><li><b>赛事介绍"
        ],
        "questions": [
          "<title>飞书 AI 校园挑战赛-线上开赛仪式</title><h1>开赛仪式流程总览</h1><ol><li><b>飞书介绍（6–8min）</b>：飞书是什么？",
          "以下是飞书最新释放的 AI 能力，也是这次挑战赛你们可以尽情探索的\"武器库\"👇</p></callout><p>🧠AI 原生体验，飞书已就绪</p><p><b>1. 飞书知识问答</b> —— 企业的\"AI 大脑\"，一问即答👉 <a hre",
          "from=feishu_home_nav\">立即访问</a> 或在飞书搜索「aily」</p><p><b>5. 飞书 aily 专业版</b> —— 复杂任务的专业伙伴，创作可视化，更强更可控👉 <a href=\"https://aily.",
          "</li><li>在 AI 能力快速迭代、产业深度融合的背景下，本次挑战赛旨在助力参赛者完成从创意构想到项目落地的全流程实践，打造可运行、可验证的 AI 实战成果，让 AI 切实解决真实问题、创造可持续的产业价值",
          "</li></ul><hr/><h2 seq=\"auto\" seq-level=\"auto\">参加本次大赛，你能获得什么？"
        ],
        "doc_type": "doc",
        "parent_chunk_id": "Eq0ywVPwdirCLakfBeucCwKWnoh#parent_c21aa3900278"
      }
    }
  ],
  "omitted_count": 0,
  "token_budget": 600,
  "used_tokens": 409,
  "knowledge_namespace": "sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce",
  "vector_collection_name": "meetflow_knowledge_chunks_137933ce",
  "embedding_provider": "sentence-transformers",
  "embedding_model": "BAAI/bge-small-zh-v1.5",
  "embedding_dimensions": 512,
  "low_confidence": false,
  "reason": "混合检索候选 2 条；向量命中 2 条；关键词命中 2 条；最终返回 2 条；已过滤 embedding 不兼容文档 0 个、缺少指纹旧文档 5 个；namespace=sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce；collection=meetflow_knowledge_chunks_137933ce"
}
```

## 6. 卡片 Payload 草案

```json
{
  "title": "MeetFlow 会前背景卡：飞书 AI 校园竞赛-主题分享直播-产品专场",
  "summary": "围绕 飞书 AI 校园竞赛-主题分享直播-产品专场，已召回 1 条相关资料。会前待读资料：飞书 AI 校园挑战赛-线上开赛仪式。",
  "facts": [
    {
      "label": "会议主题",
      "value": "飞书 AI 校园竞赛-主题分享直播-产品专场"
    },
    {
      "label": "背景摘要",
      "value": "围绕 飞书 AI 校园竞赛-主题分享直播-产品专场，已召回 1 条相关资料。会前待读资料：飞书 AI 校园挑战赛-线上开赛仪式。"
    },
    {
      "label": "置信度",
      "value": "0.95"
    },
    {
      "label": "待读资料",
      "value": "飞书 AI 校园挑战赛-线上开赛仪式"
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
        "content": "**主题**：飞书 AI 校园竞赛-主题分享直播-产品专场\n**状态**：可参考  |  **置信度**：0.95\n**背景摘要**：围绕 飞书 AI 校园竞赛-主题分享直播-产品专场，已召回 1 条相关资料。会前待读资料：飞书 AI 校园挑战赛-线上开赛仪式。"
      },
      {
        "tag": "hr"
      },
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "**待读资料**\n1. 飞书 AI 校园挑战赛-线上开赛仪式：<title>飞书 AI 校园挑战赛-线上开赛仪式</title><h1>开赛仪式流程总览</h1><ol><li><b>飞书介绍（6–8min）</b>：飞书是什么？飞书 AI 相关产品介绍</li><li><b>赛事介绍（6–8min）</b>：参赛收获、赛程安排、赛事支持</li><li><b>技术嘉宾分享（约 25min）</b>：《飞书 AI-friendly 分享》飞书技术专家@黄同学</li><li><b>资源与环境配置（10min）</b>：资源领取方式、开发\n召回原因：命中检索词:飞书；命中检索词:AI；命中检索词:校园挑战赛-线上开赛仪式 `Eq0ywVPwdirCLakfBeucCwKWnoh`"
        }
      },
      {
        "tag": "hr"
      },
      {
        "tag": "markdown",
        "content": "**证据引用**\n- `Eq0ywVPwdirCLakfBeucCwKWnoh` doc：<title>飞书 AI 校园挑战赛-线上开赛仪式</title><h1>开赛仪式流程总览</h1><ol><li><b>飞书介绍（6–8min）</b>：飞书"
      }
    ]
  },
  "source_meeting_id": "b9c6ca7b-c1dd-4f1a-b995-edf71f3faa7c_0",
  "idempotency_key": "pre_meeting_brief:b9c6ca7b-c1dd-4f1a-b995-edf71f3faa7c_0"
}
```

## 7. Agent 最终结果

- status: `success`
- trace_id: `ef7936994aba`

```text
scripted_debug 最终回复：工具 knowledge.search 执行成功。
结构化数据 JSON：
{
  "query": "MeetFlow M3 会前知识卡片",
  "hits": [
    {
      "ref_id": "kref_7c4d5148301e66f3",
      "chunk_id": "D067w8sC4iYsjjk7nnAcMEXqnwb#chunk_1_3bdc5fd45f83",
      "document_id": "D067w8sC4iYsjjk7nnAcMEXqnwb",
      "source_type": "doc",
      "title": "李健文-个人阶段小结",
      "snippet": "<title>李健文-个人阶段小结</title><h1>第一周期（4.23-4.25）</h1><h3>一、核心产出 （必填）</h3><p><em>本周期你交付的最满意的一项成果是什么？</em></p><blockquote><p><...",
      "reason": "混合命中 final_score:0.370；向量召回:0.47；命中查询词:meetflow；包含回链定位；包含来源链接；关键词召回:0.23；命中查询词:meetflow；包含回链定位；包含来源链接",
      "score": 0.37,
      "vector_similarity": 0.465,
      "term_similarity": 0.227,
      "rerank_score": 0.0,
      "final_score": 0.37,
      "source_url": "https://jcneyh7qlo8i.feishu.cn/wiki/D067w8sC4iYsjjk7nnAcMEXqnwb",
      "source_locator": "doc:chunk:1",
      "parent_chunk_id": "D067w8sC4iYsjjk7nnAcMEXqnwb#parent_92e5dc10cf8f",
      "toc_path": [
        "doc"
      ],
      "updated_at": "510",
      "metadata": {
        "document_id": "HjZ7dtVXao5Decxc6f5czWYUn81",
        "revision_id": 510,
        "doc_format": "xml",
        "detail": "simple",
        "scope": "full",
        "content_length": 5808,
        "content_excerpt": "李健文-个人阶段小结 第一周期（4.23-4.25） 一、核心产出 （必填） 本周期你交付的最满意的一项成果是什么？ 可以是一个功能、一段代码、一个工作流、一篇踩坑记录……不限形式 飞书客户端的搭建。能够通过飞书api获取到用户的日程、文档等信息。 二、量化指标 （必填） 例如：不同的 AI 使用场景、代码提交约几次、处理数据量多少、响应速度提升多少、被Star/Fork次数、接口调用次数等。 代码提交约9次，新增代码约7000行。 三、过程复盘与沉淀（必填） 这周主要搞定了哪些具体环节？用了什么方法或工具辅助？ 例如：AI 帮你做了哪些事情（跟 AI 分工）、用工具生成了接口初版代码，自己改了边界逻辑；用脚本跑了数据清洗；画了架构图；写了测试用例；设计并实现了AI工作流/插件/自动化……等等 通过描述AI的角色、项目背景等，引导AI生成了项目的 prd 文档、项目的 架构 文档，项目的 开发任务 文档。 已经构造好了项目的代码结构，实现了飞书客户端，能够获取到用户的相关信息。 过程中有没有遇到什么特别不顺、卡住很久的情况？后来是怎么破局的？ 例如：生成的内容格式总是不对、输出的结果不...",
        "embedding_provider": "sentence-transformers",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "embedding_dimensions": 512,
        "embedding_fingerprint": "sentence-transformers:BAAI/bge-small-zh-v1.5:512",
        "kn...
```
