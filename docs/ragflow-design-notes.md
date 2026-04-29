# RAGFlow 代码阅读笔记：MeetFlow 可借鉴的 RAG 设计

本文记录对 `/home/lear-ubuntu-22/ragflow-main` 的代码阅读结论，目标不是照搬 RAGFlow 的完整企业知识库系统，而是提炼对 MeetFlow M3 “轻量 RAG + 结构化元数据 + 增量更新”有价值的设计。

## 阅读范围

重点阅读了以下模块：

- `agent/tools/retrieval.py`：Agent 检索工具入口、参数、过滤、召回和结果格式化。
- `rag/nlp/search.py`：混合检索、向量召回、关键词召回、rerank、TOC 增强和父子 chunk 展开。
- `rag/llm/embedding_model.py`：embedding provider 抽象、文档向量和查询向量生成。
- `rag/llm/rerank_model.py`：reranker provider 抽象和结果归一化。
- `rag/flow/chunker/*`：token chunk、标题 chunk、表格/图片上下文增强。
- `rag/prompts/generator.py`：知识片段格式化、引用字段和 token budget 控制。
- `rag/svr/task_executor.py`：解析任务、索引任务、chunk 入库、进度和重复处理。
- `api/db/services/document_service.py` 与 `knowledgebase_service.py`：文档、知识库、解析状态和 embedding 模型绑定。

## 总体链路

RAGFlow 的 RAG 链路可以概括为：

1. 文档进入知识库，知识库绑定 embedding 模型和 parser 配置。
2. 文档解析为结构化记录，按 token、标题层级、表格、图片等策略切成 chunk。
3. 索引任务为 chunk 补充 metadata、关键词字段、位置字段、向量字段和状态统计。
4. 检索时先做 metadata/doc filter，再同时使用关键词和向量召回。
5. 候选集经过阈值、权重融合、可选 reranker、TOC 增强、父子 chunk 展开后得到最终证据。
6. 证据进入 prompt 前，会统一格式化引用字段，并按 token budget 截断。

这个链路对 MeetFlow 的启发是：RAG 不只是“把文本切块后丢进向量库”，更重要的是保留可以解释、过滤、回链和审计的结构化上下文。

## 可借鉴设计

### 1. 知识库、文档、chunk 分层

RAGFlow 把知识库、文档、chunk 分开管理，并在知识库层绑定 embedding 模型。检索多个知识库时，会检查它们是否使用同一个 embedding 模型，避免不同向量空间混查。

MeetFlow 当前已有 SQLite 保存权威元数据、ChromaDB 保存向量召回结果。后续应继续强化这个分层：

- 知识域或项目知识空间：保存 `embedding_model`、`embedding_dimensions`、索引策略和权限边界。
- 文档：保存 `document_id`、`source_url`、`updated_at`、`checksum`、`index_status`、`chunk_count`。
- Chunk：保存文本、位置、父子关系、文档类型、关键词、向量索引引用和召回解释字段。

### 2. Chunk 不应只有 text

RAGFlow 的 chunk 字段包含内容、关键词、问题、位置、文档类型、父 chunk、表格行 ID、URL、向量相似度和关键词相似度等信息。这样检索结果不仅能回答“相似吗”，还能回答“为什么相似、来自哪里、怎么跳回原文”。

MeetFlow 后续可以在 `KnowledgeChunk` 上逐步增加：

- `chunk_order`：文档内顺序。
- `parent_chunk_id`：用于父子 chunk 或章节级展开。
- `doc_type`：文档、表格、妙记、任务、评论等类型。
- `positions`：比 `source_locator` 更细的 block/range/sheet/row 位置信息。
- `content_tokens`：预算控制和摘要裁剪时使用。
- `keywords` / `questions`：辅助关键词召回和 query 改写。

### 3. 混合检索优先于单纯向量检索

RAGFlow 的检索不是只靠向量相似度，而是使用关键词召回、向量召回、metadata 过滤、权重融合和可选 reranker。它区分了：

- `top_k`：进入候选集的数量。
- `top_n`：最终返回给 Agent 或用户的数量。
- `similarity_threshold`：最低相似度阈值。
- `keywords_similarity_weight` / `vector_similarity_weight`：关键词和语义向量的融合权重。

MeetFlow 的会议场景也需要混合检索。项目名、客户名、版本号、飞书文档 token、人名更适合关键词和 metadata；背景主题、会议目标、风险描述更适合语义向量。

建议后续让 `knowledge.search` 支持这些参数的内部默认值：

- `top_k`：向量库候选数量。
- `top_n`：evidence pack 返回数量。
- `similarity_threshold`：低置信过滤。
- `keyword_weight` 与 `vector_weight`：混合排序权重。
- `metadata_filters`：项目、会议、资源类型、时间窗口、owner、权限范围。

### 4. Rerank 是独立阶段

RAGFlow 把 reranker 抽象成独立 provider，输入 query 和候选文本，输出归一化后的相关性分数。并且它会限制送入外部 reranker 的候选数量，避免成本和接口限制失控。

MeetFlow 可以先保留当前 ChromaDB 召回 + 轻量排序，后续加一个 P1 reranker：

- 开发阶段可关闭 rerank。
- 测试阶段可接入 bge-reranker、Jina reranker 或 OpenAI-compatible rerank。
- rerank 前候选集控制在 32 或 64 条。
- rerank 后仍保留 `vector_similarity`、`term_similarity` 和 `rerank_score`，便于审计。

### 5. TOC 增强和父子 chunk 展开适合飞书文档

RAGFlow 对结构化文档有两类增强：

- TOC 增强：先让模型或规则判断目录中哪些章节相关，再强化这些章节下的 chunk。
- 父子 chunk 展开：小 chunk 用来精准召回，召回后用父 chunk 或章节 chunk 补足上下文。

这很适合飞书文档、知识库页面和会议纪要：

- 飞书文档标题层级天然可形成目录。
- 会议纪要的章节、待办、风险、决策可以作为父级语义块。
- Agent 返回证据时可以展示小 chunk 的命中片段，但摘要生成时读取父 chunk 的完整上下文。

### 6. 表格和图片 chunk 需要上下文窗口

RAGFlow 在处理表格和图片时，会给它们附带前后文本上下文。原因是表格单元格或图片说明单独看常常缺少语义。

MeetFlow 读取飞书表格、多维表格和文档图片时，也应避免只索引孤立内容：

- 表格行 chunk 应保留表名、视图名、字段名和行号。
- 图片/OCR chunk 应保留图片所在标题、前后段落和文档 URL。
- 妙记片段应保留时间戳、章节标题和发言人。

### 7. Evidence pack 需要 token budget

RAGFlow 在把知识片段塞进 prompt 前，会统一格式化 ID、标题、URL、文档 metadata、内容，并按 token budget 截断。

MeetFlow 的 `knowledge.search` 已经返回压缩 evidence pack，后续应进一步明确：

- 每条 evidence 的最大 snippet 长度。
- 单次工具返回的总 token 预算。
- 是否允许二次调用 `knowledge.fetch_chunk` 展开全文。
- 引用字段必须稳定，包括 `ref_id`、`document_id`、`chunk_id`、`source_url`、`source_locator`。

### 8. 索引任务应该有状态和进度

RAGFlow 的解析和索引是异步任务，会记录文档进度、chunk 数、token 数、失败原因和解析完成状态。聊天或检索前可以判断知识库是否已解析完成。

MeetFlow 的 T3.10 可以借鉴这个方向：

- `index_jobs` 记录资源变化、手动刷新、失败重试和当前状态。
- `KnowledgeDocument.index_status` 区分 `pending`、`indexed`、`skipped`、`failed`、`stale`。
- 触发事件只写入任务，不在事件处理器里做重索引重活。
- 会前工作流遇到未完成索引时，明确提示“部分资料还在刷新中”。

### 9. Embedding provider 要区分文档和查询

RAGFlow 的 embedding 抽象区分 `encode(texts)` 和 `encode_queries(text)`。一些 embedding 模型对文档和查询有不同 prompt 或归一化策略。

MeetFlow 当前已经支持 `sentence-transformers` 和 OpenAI-compatible embedding。后续如果接入 BGE、E5、Jina 等模型，应在 provider 层支持：

- 文档 embedding 和 query embedding 的不同前缀或接口。
- 批量大小控制。
- 文本长度截断。
- token 统计或成本估算。

## MeetFlow 落地建议

### 近期可以做

- 在 `KnowledgeSearchHit` 中增加 `vector_similarity`、`term_similarity`、`rerank_score` 等字段，先允许为空。
- 在 `KnowledgeChunk` 中增加 `chunk_order`、`parent_chunk_id`、`doc_type`、`content_tokens`。
- 让 `knowledge.search` 内部区分 `top_k` 和 `top_n`，并保留默认阈值。
- 增加 metadata filter 结构，至少支持 `project_id`、`meeting_id`、`source_type`、`updated_after`。
- 为 evidence pack 加统一 token budget，避免工具输出无限增长。

### 中期可以做

- 增加 reranker provider，并把 rerank 作为可配置阶段。
- 为飞书文档标题层级建立 TOC metadata。
- 支持父子 chunk：小 chunk 召回，父 chunk 展开。
- 增加 `index_jobs` 表和后台 worker，接入飞书事件订阅。
- 为表格、图片、妙记片段增加上下文窗口。

### 暂不建议照搬

- RAGFlow 的完整多租户知识库权限系统。
- 大规模 provider 矩阵。
- RAPTOR、知识图谱和 Canvas 编排。
- 复杂的 parser marketplace。

这些能力很强，但会超过 MeetFlow M3 的边界。现阶段更重要的是把会前知识卡片链路做稳定、可解释、可回链。

## 对 M3 任务的映射

- T3.4：继续增强文档清洗、chunk schema、位置元数据和索引状态。
- T3.5：把摘要输入从资源级结果升级为 chunk 级 evidence pack。
- T3.6：增强 `knowledge.search` 的混合检索参数、分数字段和 token budget。
- T3.7：卡片引用区使用稳定 `ref_id` 和回链字段。
- T3.10：实现 `index_jobs`、事件触发、异步刷新和失败审计。

