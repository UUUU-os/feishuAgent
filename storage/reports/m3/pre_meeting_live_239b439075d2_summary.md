# M3 DeepSeek + BM25/RRF 真实联调简报

## 1. 本次结论

- 执行时间：2026-04-30 14:04-14:05 Asia/Shanghai
- 执行路径：真实日历会议 -> 真实文档读取 -> ChromaDB 向量检索 + SQLite FTS5/BM25 -> RRF 融合 -> DeepSeek 决策 -> 飞书测试群真实发卡
- 会议：`飞书环境配置`
- 会议时间：`2026-04-30 18:30-19:00 Asia/Shanghai`
- 真实文档：`Trae IDE 模型配置指南`
- DeepSeek 模型：`deepseek-chat`
- 执行状态：`success`
- 测试群消息：`chat_id=oc_3e432398cc43063fda2b2d322bb6dead`
- 飞书消息 ID：`om_x100b501b5cce7cb8b2a4c2062fa1cf3`

执行命令：

```bash
python3 scripts/pre_meeting_live_test.py --identity user --event-title '飞书环境配置' --lookahead-hours 24 --doc 'https://bytedance.larkoffice.com/docx/KlW9dIlyzo17ccxl26Gc9TGsnig' --llm-provider deepseek --max-iterations 6 --allow-write --enable-idempotency --idempotency-suffix 'deepseek-bm25-rrf-20260430-confirmed' --write-report
```

## 2. 混合索引过程

本次文档 `Trae IDE 模型配置指南` 已存在于知识库，`updated_at + checksum + embedding_fingerprint` 未变化，因此资源索引状态为 `skipped`，没有重复重写向量库。

但检索仍使用同一套混合索引：

- 业务主数据：`storage/knowledge/knowledge.sqlite`
- Dense 向量索引：ChromaDB collection `meetflow_knowledge_chunks_137933ce`
- Embedding namespace：`sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce`
- 可检索 chunk 数：`7`
- BM25 关键词索引：SQLite FTS5 表 `knowledge_chunks_fts`
- BM25 不索引 `parent_section`，只索引子 chunk，避免父级长文本压过精确片段

## 3. RRF 融合过程

DeepSeek 在一次会话中发起了两次检索：

第一次查询：`飞书环境配置`

- 向量命中：`8`
- BM25 命中：`0`
- 融合策略：`rrf`
- 结果说明：这个查询太泛，主要依赖向量召回，因此没有体现 BM25 优势。

第二次查询：`Trae IDE 模型配置 火山引擎 自定义模型`

- 向量命中：`8`
- BM25 命中：`7`
- 融合策略：`rrf`
- `rrf_k=60`
- top1：`Trae IDE 模型配置指南 / 步骤三：添加并配置自定义模型`
- top1 排名解释：`vector_rank=1`，`keyword_rank=1`，`bm25_score=-1.19834`，`rrf_score=0.032787`

RRF 计算口径：

```text
rrf_score = 1 / (rrf_k + vector_rank) + 1 / (rrf_k + keyword_rank)
top1 = 1 / (60 + 1) + 1 / (60 + 1) = 0.032787
```

本次验证点：当查询词足够具体时，同一个 chunk 同时被向量检索和 BM25 检索排到第 1，RRF 会把它稳定推到最终首位；这比直接加权比较向量相似度和 BM25 原始分更容易解释。

## 4. DeepSeek 与发卡结果

DeepSeek 的工具调用顺序：

```text
knowledge.search -> knowledge.search -> knowledge.fetch_chunk -> knowledge.fetch_chunk -> im.send_card
```

最终卡片已由应用身份发送到测试群。卡片内容围绕 `Trae IDE 模型配置指南`，包含配置目的、准备信息、配置步骤、验证与排障，以及原始文档链接。

原始完整报告仍保留在：

- `storage/reports/m3/pre_meeting_live_239b439075d2.md`
- `storage/reports/m3/pre_meeting_live_239b439075d2.json`
