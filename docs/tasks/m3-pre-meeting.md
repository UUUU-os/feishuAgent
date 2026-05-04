## 5.3 M3：会前知识卡片工作流

### M3 数据处理设计补充

M3 的核心难点不是“根据会议标题搜索文档”，而是在日程信息不足、飞书资源格式不统一、文档持续变化的情况下，仍然能生成可解释、可追溯、可更新的会前背景知识。当前阶段采用“轻量 RAG + 结构化元数据 + 增量更新”的边界，不一开始建设全量企业知识库。

RAGFlow 代码阅读中可借鉴的 RAG 设计已沉淀到 [RAGFlow 代码阅读笔记：MeetFlow 可借鉴的 RAG 设计](../ragflow-design-notes.md)，后续增强 chunk schema、混合检索、rerank、TOC/父子 chunk 和索引任务时优先参考该笔记。

设计原则：

- Query 增强优先：检索词不能只来自会议标题，还要结合会议描述、参会人、日程附件、历史同名会议、参会人组合、项目记忆和近期共享文档。
- 小范围知识域优先：M3 只索引会议相关知识域，包括日程附件、历史会议纪要、指定知识库空间、项目群近期分享文档和已被 MeetFlow 推送过的资料。
- 可追溯优先：保存 chunk 时必须保留原始文档 token、标题、URL、更新时间、block/range/sheet 位置信息和来源类型，避免只保存 embedding 后无法解释。
- 混合检索优先：语义向量适合召回相似背景，关键词/元数据适合匹配项目名、客户名、版本号、人名、会议 ID 等精确信号。
- 工具化检索优先：RAG 检索应作为受控只读工具暴露给 Agent，由模型在需要补充证据时调用，但工具返回给模型的是压缩后的 evidence pack，不是文档全文。
- 增量更新优先：M3 先实现 `updated_at + checksum` 的增量刷新；飞书事件订阅、`index_jobs` 和后台 worker 作为后续增强任务逐步落地。

建议新增或扩展模块：

- `core/knowledge.py`：定义 `KnowledgeDocument`、`KnowledgeChunk`、`RetrievalQuery`、`RetrievalResult` 等知识模型。
- `core/retrieval.py`：负责 query enrichment、候选召回、混合排序和低置信度判断。
- `storage/knowledge_store.py`：保存文档元数据、chunk、索引状态、checksum 和最近刷新时间。
- `adapters/feishu_docs.py` 或现有飞书 adapter 扩展：封装文档/表格搜索、读取、导出和更新时间检查。
- `workflows/pre_meeting_brief.py`：编排会前 query 构建、资源召回、证据排序、摘要和卡片输出。

M3 暂不要求完成图片 OCR、全量企业文档监听和大规模分布式向量库部署；这些能力可以在基础链路稳定后演进。

### RAGFlow 设计转化任务总览

RAGFlow 阅读笔记中的可借鉴设计已转化为 M3 后续任务：

- T3.11：知识域与 embedding 模型一致性治理
- T3.12：扩展 chunk schema 与结构化位置元数据
- T3.13：实现可配置混合检索和可解释分数
- T3.14：接入可选 reranker 阶段
- T3.15：支持 TOC 增强与父子 chunk 展开
- T3.16：实现 evidence pack token budget 与稳定引用格式

这些任务优先服务会前知识卡片的准确性、可解释性和可回链能力，不引入 RAGFlow 的完整多租户知识库、RAPTOR、知识图谱或复杂 Canvas 编排。

### T3.1 定义 `pre_meeting_brief` 工作流输入输出

- 优先级：`P0`
- 目标：明确会前工作流的输入、输出和中间结构
- 设计补充：
  - 会前工作流应以 `PreMeetingBriefWorkflow` 或等价 Runner 形式落地，而不是只把目标文本交给 `MeetFlowAgentLoop`
  - Runner 固定执行阶段：准备上下文、构造 `RetrievalQuery`、调用 Agent Loop 补证据、校验 `MeetingBrief`、渲染卡片、执行发送或保存
  - Agent Loop 只负责在限定工具集内检索、展开证据和生成 `MeetingBrief` 草案
- 验收标准：
  - 有统一函数签名或接口定义
  - 输出可直接给卡片渲染层使用
  - 工作流能明确区分确定性阶段和 LLM 工具编排阶段

#### T3.1 当前实现细节

- 已创建文件：
  - `core/pre_meeting.py`
- 已更新文件：
  - `core/workflows.py`
  - `core/__init__.py`
  - `scripts/workflow_runner_demo.py`
  - `tasks.md`
- 已实现的核心模型：
  - `PreMeetingBriefInput`：会前工作流确定性输入，统一承接会议 ID、日历事件 ID、会议标题、描述、时间、参与人、附件、相关资源和项目记忆
  - `RetrievalQuery`：会前检索结构化查询，包含会议标题、描述、实体线索、参会人、附件标题、相关资源标题、资源类型、时间窗口、检索词、置信度和缺失上下文
  - `MeetingBriefItem`：会前卡片中的单条可溯源内容，后续用于承接关键决策、当前问题、待读资料和风险点
  - `MeetingBrief`：会前背景知识卡片的结构化产物，作为 Agent Loop 草案和卡片渲染层之间的稳定契约
  - `PreMeetingCardPayload`：当前卡片工具可直接消费的最小渲染输入，字段为 `title`、`summary`、`facts`、`source_meeting_id` 和 `idempotency_key`
  - `PreMeetingBriefArtifacts`：会前工作流阶段产物集合，统一包含输入、检索查询、MeetingBrief 草案、卡片 payload 和阶段计划
- 已实现的核心函数：
  - `build_pre_meeting_brief_artifacts()`：从 `WorkflowContext` 一次性构造 T3.1 约定的会前工作流产物
  - `build_pre_meeting_brief_input()`：把通用上下文转换为会前专用输入
  - `build_retrieval_query()`：根据会议标题、描述、附件、参与人、相关资源和项目记忆生成结构化检索查询
  - `build_initial_meeting_brief()`：生成进入 Agent Loop 前的 `MeetingBrief` 空壳，明确哪些内容还需要证据补全
  - `render_pre_meeting_card_payload()`：把 `MeetingBrief` 转成当前 `im.send_card` 工具可用的卡片 payload
- 已接入的 Runner 行为：
  - `PreMeetingBriefWorkflow.prepare_context()` 现在会固定生成 `pre_meeting_brief` artifacts
  - `raw_context` 中同步写入 `pre_meeting_input`、`retrieval_query`、`retrieval_query_draft`、`meeting_brief_draft`、`pre_meeting_card_payload` 和 `pre_meeting_stage_plan`
  - `build_retrieval_query_draft()` 保留旧函数名，但内部已改为基于新的 `RetrievalQuery` 模型返回字典，避免破坏现有 demo
  - `PreMeetingBriefWorkflow.validate_output()` 增加 T3.1 结构校验，成功结果必须包含会前 artifacts 和可供卡片渲染的 payload
- 当前阶段边界：
  - 确定性阶段负责准备上下文、构造 `RetrievalQuery`、生成 `MeetingBrief` 空壳和卡片 payload
  - LLM 工具编排阶段仍由 `MeetFlowAgentLoop` 执行，后续 T3.2-T3.6 会逐步补主题识别、知识检索、证据展开和摘要生成
  - 当前 `MeetingBrief.summary` 仍是占位草案，不代表 M3 的证据摘要能力已经完成
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/*.py scripts/workflow_runner_demo.py scripts/agent_demo.py` 验证语法正确
  - 已通过 `python3 scripts/workflow_runner_demo.py` 验证会前 Runner 能生成 `RetrievalQuery`、`MeetingBrief` 草案、卡片 payload，并继续完成 Agent Loop 工具调用

### T3.2 实现会议主题识别

- 优先级：`P0`
- 目标：根据会议标题、参与人、上下文识别项目或议题
- 设计补充：
  - 输出不只是单个主题字符串，还应包含候选项目、业务实体、参会人线索、置信度和缺失字段
  - 当日程标题/描述过短时，应尝试结合历史同名会议、相似参会人组合、项目记忆和附件标题补全检索上下文
  - 置信度过低时进入待确认或“可能相关资料”模式，不强行生成确定性结论
- 验收标准：
  - 对至少 3 条样例会议能正确归类
  - 至少覆盖一条“日程信息不完整”的样例，并能输出 query 增强结果

#### T3.2 当前实现细节

- 已创建文件：
  - `scripts/pre_meeting_topic_demo.py`
- 已更新文件：
  - `core/pre_meeting.py`
  - `core/__init__.py`
  - `tasks.md`
- 已实现的核心模型：
  - `CandidateProject`：会议可能归属的项目候选，包含 `project_id`、项目名称、规则分数、命中线索和来源
  - `MeetingTopicSignal`：会议主题识别结果，包含主题、候选项目、业务实体、参会人线索、置信度、缺失上下文、检索提示词、是否需要确认和识别原因
- 已实现的核心函数：
  - `identify_meeting_topic()`：基于会议标题、描述、附件、相关资源、参会人和项目记忆识别主题，并输出 query 增强线索
  - `extract_memory_projects()`：从项目记忆读取候选项目，兼容单项目记忆和 `projects` / `related_projects` 列表
  - `score_candidate_projects()`：根据项目名、别名、关键词、参会人和 `project_id` 对候选项目打分
  - `infer_topic_phrase()`：从标题或描述中提取可读主题短语
  - `is_weak_meeting_title()`：识别“同步 / 周会 / 讨论”等过短或泛化标题
  - `build_topic_reason()`：生成主题识别解释，方便审计和答辩展示
- 已接入的 query 增强行为：
  - `build_pre_meeting_brief_artifacts()` 现在会先生成 `MeetingTopicSignal`，再构造 `RetrievalQuery`
  - `RetrievalQuery.entities` 会合并主题识别出的业务实体和显式标题/附件实体
  - `RetrievalQuery.search_queries` 会加入识别主题、候选项目、项目记忆关键词、附件标题和参会人线索
  - `RetrievalQuery.extra.topic_signal` 会完整保留主题识别结果，供后续 T3.3/T3.6 检索和审计使用
  - `MeetingBrief.topic` 会使用识别后的主题，低置信或缺少上下文时设置 `needs_confirmation`
- 当前样例覆盖：
  - `topic_demo_clear`：标题和描述明确，能识别 MeetFlow、M3、轻量 RAG 等主题线索
  - `topic_demo_short_title`：标题只有“同步”，但能通过附件和项目记忆补全为 MeetFlow / M3 / 轻量 RAG 相关检索上下文
  - `topic_demo_missing_context`：标题泛化且缺少参与人和附件，会输出缺失字段并进入待确认模式
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/*.py scripts/pre_meeting_topic_demo.py scripts/workflow_runner_demo.py scripts/agent_demo.py` 验证语法正确
  - 已通过 `python3 scripts/pre_meeting_topic_demo.py` 验证 3 条样例会议的主题识别、候选项目、实体线索、置信度和 query 增强结果
  - 已通过 `python3 scripts/workflow_runner_demo.py` 验证 T3.2 主题识别已接入 `PreMeetingBriefWorkflow`，且原有 Agent Loop 链路仍可运行

### T3.3 实现关联资源召回

- 优先级：`P0`
- 目标：召回最近相关文档、妙记和未完成任务
- 设计补充：
  - 构造结构化 `RetrievalQuery`，字段至少包含会议标题、实体词、参会人、时间窗口、资源类型和置信度
  - 对飞书文档、妙记、任务采用混合召回：关键词/元数据过滤 + 语义相似度排序 + 最近更新时间加权
  - 返回结果必须保留来源 URL、资源更新时间、命中原因和可用于证据回链的位置标识
- 验收标准：
  - 能返回去重后的相关资源列表
  - 至少包含标题、摘要、链接
  - 能解释每个资源为什么被召回

#### T3.3 当前实现细节

- 已创建文件：
  - `scripts/pre_meeting_retrieval_demo.py`
- 已更新文件：
  - `core/pre_meeting.py`
  - `core/workflows.py`
  - `core/__init__.py`
  - `scripts/workflow_runner_demo.py`
  - `tasks.md`
- 已实现的核心模型：
  - `RetrievedResource`：一条会前召回资源，包含资源 ID、类型、标题、摘要、来源 URL、更新时间、分数、召回原因、回链定位和元数据
  - `RetrievalResult`：召回结果集合，包含原始 `RetrievalQuery`、去重排序后的资源列表、被省略数量、低置信标记和整体说明
- 已实现的核心函数：
  - `recall_related_resources()`：根据 `RetrievalQuery` 从本地候选池召回相关资源，并按关键词、元数据和更新时间排序
  - `build_resource_candidates()`：构造首版候选池，来源包括 `related_resources`、日程附件和项目记忆中的 `resources/documents/docs/minutes/tasks/recent_resources`
  - `score_resource_candidate()`：对候选资源做轻量混合打分，考虑检索词、业务实体、参会人、附件标题、资源类型、更新时间、来源链接和回链定位
  - `has_business_match()`：过滤只命中类型、链接、更新时间的弱相关资源，避免无关文档混入会前资料
  - `build_brief_items_from_retrieval()`：把召回资源转换成 `MeetingBrief.possible_related_resources`，并附 `EvidenceRef`
  - `normalize_resource_type()`：把 `feishu_document/docx/documents/minutes/tasks/attachment` 等字段归一到 `doc/minute/task/sheet`
  - `estimate_freshness_score()` / `parse_timestamp()`：根据 `updated_at` 做轻量新鲜度加权
- 已接入的 Runner 行为：
  - `build_pre_meeting_brief_artifacts()` 现在会在构造 `RetrievalQuery` 后执行 `recall_related_resources()`
  - `PreMeetingBriefArtifacts` 新增 `retrieval_result`
  - `PreMeetingBriefWorkflow.prepare_context()` 会把 `retrieval_result` 写入 `raw_context`
  - `MeetingBrief.possible_related_resources` 会使用召回结果生成，卡片 payload 中也会展示“可能相关资料”
- 当前实现边界：
  - T3.3 首版候选池来自事件 payload 和项目记忆，不直接调用真实飞书搜索接口
  - 当前排序是关键词/元数据过滤 + 更新时间加权的轻量混合召回；语义向量排序和 chunk 级检索会在 T3.4/T3.6 接入 KnowledgeStore 后继续增强
  - 每条召回结果已经保留 `source_url`、`updated_at`、`source_locator` 和 `reasons`，满足后续证据回链需要
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/*.py scripts/pre_meeting_retrieval_demo.py scripts/pre_meeting_topic_demo.py scripts/workflow_runner_demo.py` 验证语法正确
  - 已通过 `python3 scripts/pre_meeting_retrieval_demo.py` 验证文档、妙记、任务候选召回、去重排序、原因解释和回链定位
  - 已通过 `python3 scripts/workflow_runner_demo.py` 验证 T3.3 已接入 `PreMeetingBriefWorkflow`，并能把召回资源写入 `MeetingBrief` 与卡片 payload

### T3.4 实现轻量知识索引与文档清洗

- 优先级：`P0`
- 目标：把飞书文档、表格、妙记等资源清洗成可检索、可回链的知识 chunk
- 处理范围：
  - 飞书文档：按标题层级、段落、列表、表格 block 切分
  - 飞书表格：按 sheet、表头、关键列、行记录生成结构化文本和元数据
  - 妙记：按章节、时间段、发言主题或 Action Item 附近片段切分
  - 图片/附件：M3 先保存元信息和上下文，后续再扩展 OCR 或文件解析
- 验收标准：
  - 本地能保存 `KnowledgeDocument` 与 `KnowledgeChunk`
  - chunk 能回链到原始资源 URL 或 block/range/sheet
  - 同一资源重复索引时能通过 `updated_at + checksum` 避免无意义重建

#### T3.4 当前实现细节

- 已创建文件：
  - `core/knowledge.py`
  - `scripts/knowledge_index_demo.py`
- 已更新文件：
  - `core/__init__.py`
  - `tasks.md`
- 已实现的核心模型：
  - `KnowledgeDocument`：文档级元数据，包含 `document_id`、`source_type`、标题、来源 URL、owner、更新时间、权限范围、checksum、索引状态、最近索引时间、chunk 数和 metadata
  - `KnowledgeChunk`：可检索片段，包含 `chunk_id`、`document_id`、chunk 类型、文本、回链定位、metadata、embedding 引用占位、checksum 和创建/更新时间
  - `KnowledgeIndexResult`：一次索引结果，包含文档、chunk 列表、状态、是否跳过和原因
- 已实现的核心存储：
  - `KnowledgeIndexStore`：知识索引 SQLite 存储，默认落到 `storage/knowledge/knowledge.sqlite`
  - `knowledge_documents` 表：保存文档元数据、checksum、index_status、last_indexed_at 和 chunk_count
  - `knowledge_chunks` 表：保存 chunk 文本、类型、source_locator、metadata、checksum 和 embedding_ref 占位
- 已实现的核心函数：
  - `build_knowledge_index()`：把 `Resource` / `RetrievedResource` 清洗为 `KnowledgeDocument + KnowledgeChunk[]`
  - `KnowledgeIndexStore.index_resource()`：索引资源并写入本地 SQLite；当 `updated_at + checksum` 未变化时跳过重复构建
  - `KnowledgeIndexStore.get_document()` / `list_chunks()`：读取文档元数据和 chunk 列表
  - `chunk_document_text()`：按飞书 DocxXML/HTML-like 结构解析标题、段落、列表、表格单元、引用和图片，再按 TOC 路径与 token 预算合并为可检索子 chunk
  - `chunk_sheet_text()`：按表头和行记录切分表格/CSV 风格文本
  - `chunk_minute_text()`：按章节或时间戳切分妙记文本
  - `normalize_source_type()`：把 `feishu_document/docx/sheet/minute/task` 等来源类型归一
  - `sha256_text()` / `stable_chunk_id()`：生成文档和 chunk checksum 以及稳定 chunk ID
- 当前回链能力：
  - 文档 chunk 会保留 `source_url`、标题、source_type、heading 和 `block_id/source_locator`
  - 表格 chunk 会保留 `sheet:header` 或 `sheet:row:{n}` 定位，并在 metadata 中保留表头和行号
  - 妙记 chunk 会保留章节/时间戳上下文，并支持使用 `segment_id/source_locator` 作为基础定位
- 当前实现边界：
  - T3.4 先完成本地清洗、切片、索引状态和增量跳过；T3.6 已在此基础上接入 ChromaDB 向量索引
  - `embedding_ref` 在 T3.6 后会写入 `chroma:{collection}:{chunk_id}`，SQLite 仍保存权威元数据和回链信息
  - `knowledge.sqlite` 是 MeetFlow 的知识库主存储，不只是 ChromaDB 的重复备份：它负责保存文档和 chunk 的业务事实、完整正文、来源链接、结构化位置、父子 chunk、checksum、索引状态、增量刷新依据和 `embedding_ref`
  - ChromaDB 是可替换的向量索引层，负责 embedding 生成和语义召回；检索命中后仍需要通过 `chunk_id` 回到 `knowledge.sqlite` 展开完整证据、来源 URL、TOC 路径和父级上下文
  - chunk 文本在两边都保存是有意分层：ChromaDB 需要文本构建向量索引，`knowledge.sqlite` 需要文本服务关键词召回、审计回链、`knowledge.fetch_chunk` 证据展开、增量重建和未来 SQLite FTS5/BM25
  - 当前清洗输入是已读取到的 `Resource` / `RetrievedResource`，真实飞书资源读取仍沿用 M2 的 adapter 和后续 T3.6 工具链
  - 飞书文档导出内容如果是一整行 XML/HTML 字符串，会优先走结构化解析；普通 Markdown/纯文本仍保留换行切分兜底
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/*.py scripts/knowledge_index_demo.py scripts/pre_meeting_retrieval_demo.py scripts/workflow_runner_demo.py` 验证语法正确
  - 已通过 `python3 scripts/knowledge_index_demo.py` 验证文档、表格、妙记三类资源可清洗为 `KnowledgeDocument` 和 `KnowledgeChunk`
  - 已验证同一资源第二次索引会因为 `updated_at + checksum` 未变化返回 `status=skipped`
  - 已验证本地创建 `storage/knowledge/knowledge.sqlite`，且可以读取文档元数据和 chunk 列表
  - 已用真实飞书 DocxXML 文档 `飞书 AI 校园挑战赛-线上开赛仪式` 验证结构化切分：原先整篇退化为 1 个超长子 chunk，优化后可切为 13 个带 TOC 路径的可检索子 chunk

### T3.5 实现证据排序与摘要生成

- 优先级：`P0`
- 目标：从召回结果中提炼“最小知识集”
- 输出建议：
  - 上次结论
  - 当前问题
  - 待读资料
  - 风险点
- 验收标准：
  - 输出内容简洁
  - 每一条结论都带来源
  - 能区分“高置信背景知识”和“可能相关资料”

#### T3.5 当前实现细节

- 已创建文件：
  - `scripts/pre_meeting_summary_demo.py`
- 已更新文件：
  - `core/pre_meeting.py`
  - `scripts/workflow_runner_demo.py`
  - `docs/tasks/m3-pre-meeting.md`
- 已实现的核心能力：
  - `build_initial_meeting_brief()` 现在会基于召回结果生成可读摘要，不再只输出占位草案
  - `rank_retrieved_resources_for_brief()` 会在 T3.3 相关性排序基础上，轻微优先妙记、任务、文档和带回链定位的资源
  - `build_brief_items_from_retrieval()` 会把召回资源转换成带 `EvidenceRef` 的 `MeetingBriefItem`
  - `select_must_read_resources()` 会挑选高置信资料进入“待读资料”
  - `select_brief_items_by_intent()` 会根据标题和摘要关键词提炼“上次结论”和“当前问题”
  - `select_risk_items()` 会优先选择任务类资源和真实风险/阻塞/逾期/待办信号，并避免把“风险点字段说明”误判为真实风险
  - `build_pre_meeting_summary()` 会把主题、召回数量、上次结论、当前问题、风险点和待读资料压缩成一句会前摘要
  - `collect_brief_evidence_refs()` 会把摘要条目的来源证据去重后挂到 `MeetingBrief.evidence_refs`
- 已接入的卡片输出：
  - `render_pre_meeting_card_payload()` 现在会输出“上次结论”“当前问题”“风险点”“待读资料”和“可能相关资料”
  - 每条卡片事实仍来自 `MeetingBriefItem`，并保留来源 URL、更新时间和证据片段，满足后续审计回链
- 当前实现边界：
  - T3.5 首版摘要仍是确定性规则摘要，不调用 LLM 生成自由文本
  - 当前确定性摘要仍来源于 T3.3 的资源级召回结果；T3.6 已接入 `knowledge.search` / `knowledge.fetch_chunk`，后续可把摘要输入升级为 chunk 级 evidence pack
  - 低置信或缺少上下文时，摘要会明确提示需要人工确认，并把资源放入“可能相关资料”模式
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/*.py scripts/pre_meeting_summary_demo.py scripts/pre_meeting_retrieval_demo.py scripts/workflow_runner_demo.py` 验证语法正确
  - 已通过 `python3 scripts/pre_meeting_summary_demo.py` 验证会前摘要、上次结论、当前问题、待读资料、风险点和证据来源可正常生成
  - 已通过 `python3 scripts/workflow_runner_demo.py` 验证 T3.5 已接入 `PreMeetingBriefWorkflow`，并能输出更新后的 `meeting_brief_draft` 与 `pre_meeting_card_payload`

### T3.6 实现知识检索 Agent 工具

- 优先级：`P0`
- 目标：把 RAG 检索能力封装成 `ToolRegistry` 可注册的只读工具，让 `MeetFlowAgentLoop` 在需要时通过工具调用获取背景证据
- P0 工具：
  - `knowledge.search`：输入 query、meeting_id、project_id、resource_types、time_window、top_k，输出压缩后的 evidence pack、召回原因、来源链接和省略结果数量
  - `knowledge.fetch_chunk`：输入 chunk_id 或 ref_id，输出单个 chunk 的更完整内容、原文位置和来源信息
- P1 工具：
  - `knowledge.refresh_resource`：输入 resource_id 或 source_url，触发索引刷新或返回刷新计划
  - `knowledge.explain_retrieval`：输入 retrieval_id，输出召回原因、排序分、过滤条件和被省略结果
- 设计补充：
  - `knowledge.search` 不返回全文，只返回经过去重、排序和预算控制的 evidence pack
  - 完整检索结果保存在 `AgentToolResult.data`、`KnowledgeStore` 或审计记录中
  - 如果模型认为证据不足，再通过 `knowledge.fetch_chunk` 二次展开指定片段
  - 工具必须是只读或低风险工具，仍然经过 `ToolRegistry` 和必要的 `AgentPolicy` 校验
- 验收标准：
  - Agent 可以在会前工作流中主动调用 `knowledge.search`
  - 长检索结果不会直接塞入 `AgentMessage.content`
  - 工具返回内容包含 `ref_id`、`snippet`、`reason`、`source_url` 和 `omitted_count`
  - 模型可以基于 `ref_id` 调用 `knowledge.fetch_chunk` 获取更完整证据

#### T3.6 当前实现细节

- 已创建文件：
  - `scripts/knowledge_tools_demo.py`
- 已更新文件：
  - `core/knowledge.py`
  - `core/__init__.py`
  - `core/agent.py`
  - `core/router.py`
  - `core/workflows.py`
  - `scripts/agent_demo.py`
  - `scripts/workflow_runner_demo.py`
  - `docs/tasks/m3-pre-meeting.md`
- 已实现的核心模型：
  - `KnowledgeSearchHit`：`knowledge.search` 返回的一条压缩证据，包含 `ref_id`、`chunk_id`、`document_id`、`source_type`、标题、snippet、召回原因、分数、来源 URL、回链定位和更新时间
  - `KnowledgeSearchResult`：知识检索结果集合，包含 hits、`omitted_count`、低置信标记和整体说明
  - `KnowledgeChunkFetchResult`：`knowledge.fetch_chunk` 的展开结果，包含完整 chunk 文本、原文位置和来源元数据
- 已实现的核心函数：
  - `ChromaKnowledgeVectorIndex`：ChromaDB 适配器，负责把 chunk 写入持久化向量库，并按 query 做向量召回
  - `OpenAICompatibleEmbeddingFunction`：通过真实 OpenAI-compatible `/embeddings` 接口生成向量，可用于 `text-embedding-3-small` 等付费或高性能模型
  - `SentenceTransformersEmbeddingFunction`：通过本地开源 `sentence-transformers` 模型生成真实向量，可用于开发阶段免费模型，例如 `BAAI/bge-small-zh-v1.5`
  - `KnowledgeIndexStore.index_resource()`：写入 SQLite 权威元数据后，同步把 chunk upsert 到 ChromaDB，并写入 `embedding_ref`
  - `KnowledgeIndexStore.search_chunks()`：通过 ChromaDB 向量索引召回 chunk，再结合 SQLite 中的标题、来源 URL、回链定位、更新时间和关键词命中做 evidence pack 排序
  - `KnowledgeIndexStore.fetch_chunk()`：按 `chunk_id` 或 `ref_id` 展开指定知识片段
  - `build_knowledge_search_tool()`：构造只读工具 `knowledge.search`，暴露给 LLM 的名称为 `knowledge_search`
  - `build_knowledge_fetch_chunk_tool()`：构造只读工具 `knowledge.fetch_chunk`，暴露给 LLM 的名称为 `knowledge_fetch_chunk`
  - `register_knowledge_tools()`：把两个知识工具注册到 `ToolRegistry`
  - `build_snippet()`：为搜索结果生成压缩片段，避免直接把长文档全文塞回 Agent 上下文
- 已接入的 Agent 行为：
  - `create_meetflow_agent()` 默认创建飞书工具注册器后，会初始化 `KnowledgeIndexStore` 并注册 `knowledge.search` / `knowledge.fetch_chunk`
  - `WorkflowRouter` 和 `PreMeetingBriefWorkflow` 的会前工具边界已加入 `knowledge.search` 和 `knowledge.fetch_chunk`
  - 会前 workflow goal 明确提示 Agent 优先调用 `knowledge_search` 获取压缩证据包，必要时再通过 `knowledge_fetch_chunk` 展开指定 `ref_id`
  - 本地 `build_local_registry()` 已注册知识工具，`ScriptedDebugProvider` 会在会前 demo 中优先调用 `knowledge_search`
- 当前实现边界：
  - 当前 T3.6 已使用 ChromaDB 作为持久化向量数据库，向量库默认路径为 `storage/knowledge/chroma`
  - SQLite 仍是权威元数据存储；ChromaDB 只负责向量召回，避免只保存 embedding 后无法审计和回链
  - 检索链路采用“ChromaDB 返回候选 `chunk_id`，SQLite 回表补齐业务证据”的结构；这使得后续替换向量库、增加 BM25、增加 RRF 或重建 embedding collection 时，不需要重写文档/chunk 主数据
  - 当前 embedding 必须是真实模型；开发阶段默认配置为 `sentence-transformers` + `BAAI/bge-small-zh-v1.5`，测试/生产阶段可通过配置切换为 OpenAI-compatible `text-embedding-3-small`
  - 为避免不同 embedding 模型或维度冲突，Chroma collection 名会包含 `model + dimensions` 的短 hash
  - `knowledge.search` 返回的是 evidence pack，不返回全文；全文展开必须显式调用 `knowledge.fetch_chunk`
  - `knowledge.refresh_resource` 和 `knowledge.explain_retrieval` 仍属于 P1，留到后续索引刷新和审计增强
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/*.py adapters/*.py scripts/knowledge_tools_demo.py scripts/workflow_runner_demo.py scripts/agent_demo.py` 验证语法正确
  - 若使用 `sentence-transformers` 但本地未安装依赖，`python3 scripts/knowledge_tools_demo.py` 会明确提示安装 `sentence-transformers`
  - 配置真实 embedding 模型后，`python3 scripts/knowledge_tools_demo.py` 可验证 `knowledge.search` 通过 ChromaDB 向量索引返回 `ref_id`、`snippet`、`reason`、`source_url`、`omitted_count`，且 `knowledge.fetch_chunk` 能通过 `ref_id` 展开 chunk

### T3.7 实现会前卡片模板

- 优先级：`P0`
- 目标：设计一张适合答辩演示的会前卡片
- 验收标准：
  - 卡片字段完整
  - 支持替换不同会议数据

#### T3.7 当前实现细节

- 已创建文件：
  - `cards/__init__.py`
  - `cards/pre_meeting.py`
  - `scripts/pre_meeting_card_demo.py`
- 已更新文件：
  - `core/pre_meeting.py`
  - `core/__init__.py`
  - `adapters/feishu_tools.py`
  - `docs/tasks/m3-pre-meeting.md`
- 已实现的核心能力：
  - 新增 `build_pre_meeting_card()`：把 `MeetingBrief` 渲染为完整飞书 interactive card JSON
  - 新增 `build_pre_meeting_card_sections()`：固定会前卡片分区，包含“上次结论”“当前问题”“风险点”“待读资料”“可能相关资料”
  - 卡片顶部展示主题、状态、置信度和背景摘要，便于用户第一眼判断是否可参考
  - 每个分区最多展示 3 条核心内容，并保留首个证据 `ref_id`，确保会前结论可追溯
  - 卡片末尾展示最多 5 条证据引用，包含 `source_id`、来源类型和 snippet
  - 根据上下文状态选择 header 颜色：需确认为 orange，有风险为 red，高置信为 green，默认 blue
  - `PreMeetingCardPayload` 新增 `sections` 和 `card` 字段，同时保留原 `title`、`summary`、`facts`、`idempotency_key`
  - `render_pre_meeting_card_payload()` 现在同时产出旧版最小发送 payload 和完整卡片 JSON
  - `im.send_card` 工具新增可选 `card` 参数；传入完整 card 时直接发送，未传时仍使用旧的通用卡片构造逻辑
  - `im.send_card` 的 `facts` 兼容字符串列表和 `{label, value}` 对象列表，避免旧工具把字典直接渲染成 Python 字面量
- 当前实现边界：
  - 当前模板以飞书通用 interactive card JSON 为目标，不引入卡片 DSL 或外部模板引擎
  - 发送完整 T3.7 模板需要调用 `im.send_card` 时传入 `card=pre_meeting_card_payload.card`；旧调用只传 `title/summary/facts` 仍然可用
- 当前验证方式：
  - 已通过 `python3 -m py_compile cards/*.py core/pre_meeting.py core/__init__.py adapters/feishu_tools.py scripts/pre_meeting_card_demo.py` 验证语法正确
  - 已通过 `python3 scripts/pre_meeting_card_demo.py` 验证不同卡片字段、分区、证据引用、完整 `card` JSON 和幂等键可正常生成

### T3.8 接入会前定时触发

- 优先级：`P0`
- 目标：在会议开始前固定时间自动执行
- 当前实现状态：已完成本地可验证版本
- 当前修改文件：
  - `core/pre_meeting_trigger.py`
  - `core/__init__.py`
  - `scripts/pre_meeting_trigger_demo.py`
- 已实现的核心能力：
  - 新增 `PreMeetingTriggerPlan`，把“日历事件进入会前窗口”的判断结果封装为稳定触发计划
  - 新增 `select_due_pre_meeting_events()`，按 `settings.scheduler.pre_meeting_minutes_before` 和容忍窗口筛选即将开始的会议
  - 新增 `build_pre_meeting_trigger_plan()`，把日历事件转换为 `meeting.soon` 的 `AgentInput`
  - 自动补齐 `workflow_type=pre_meeting_brief`、`project_id`、`meeting_id`、`calendar_event_id` 和 `idempotency_key`
  - `WorkflowRouter.build_idempotency_key()` 会直接复用触发器已生成的完整 `idempotency_key`，避免路由层再次追加工作流前缀
  - 触发后仍进入 `WorkflowRouter -> PreMeetingBriefWorkflow -> Agent Loop`，不会绕过固定工作流骨架
  - `scripts/pre_meeting_trigger_demo.py` 使用本地 scripted provider 演练定时触发，并在同一事件重复运行时验证幂等跳过
- 当前实现边界：
  - 当前是 scheduler/cron 可调用的触发构造层，尚未接入真实后台定时进程
  - demo 不发送真实飞书卡片，`allow_write=False` 会移除 `im.send_card`
- 当前验证方式：
  - 已通过 `python3 scripts/pre_meeting_trigger_demo.py` 验证：命中 1 条会前事件，第一次执行 `success`，第二次执行 `skipped`，且返回的幂等键不会重复追加 `pre_meeting_brief:`
- 验收标准：
  - 能通过定时或模拟触发运行整个工作流
  - 不重复发送相同卡片
  - 触发后进入 `PreMeetingBriefWorkflow` 骨架，而不是直接把事件丢给 LLM 自由处理

### T3.9 增加手动兜底入口

- 优先级：`P1`
- 目标：支持命令式触发
- 示例：
  - “生成项目 A 今日会前卡片”
- 当前实现状态：已完成本地可验证版本
- 当前修改文件：
  - `core/pre_meeting_trigger.py`
  - `core/__init__.py`
  - `scripts/pre_meeting_manual_demo.py`
- 已实现的核心能力：
  - 新增 `build_manual_pre_meeting_input()`，把用户命令转换为 `message.command` 的 `AgentInput`
  - 手动入口固定写入 `workflow_type=pre_meeting_brief`，确保路由到会前卡片工作流
  - 根据命令文本生成稳定 `meeting_id`、`calendar_event_id` 和 `idempotency_key`，便于后续接入真实命令入口时做去重
  - `scripts/pre_meeting_manual_demo.py` 支持通过 `--command`、`--project-id`、`--meeting-title` 模拟手动触发
- 当前实现边界：
  - 当前手动入口是本地 CLI 演示脚本，后续可挂到飞书消息命令、机器人菜单或管理后台按钮
  - 默认 `enable_idempotency=False`，便于本地重复演示；真实命令入口接入时应按业务需要打开幂等
- 当前验证方式：
  - 已通过 `python3 scripts/pre_meeting_manual_demo.py --command '生成 MeetFlow 今日会前卡片'` 验证：入口为 `message.command`，工作流为 `pre_meeting_brief`，执行状态为 `success`
- 验收标准：
  - 自动触发失败时仍可演示主能力

### T3.10 预留知识变更更新机制

- 优先级：`P1`
- 目标：为后续监听飞书文档、表格、知识库变化预留索引刷新入口
- 当前实现状态：已完成本地队列与刷新入口
- M3 实现边界：
  - 记录资源 `updated_at`、`checksum`、`last_indexed_at`、`index_status`
  - 支持按资源 token 手动触发重新索引
  - 支持对最近被会议引用过的资源做定时校验
- 当前修改文件：
  - `core/knowledge.py`
  - `core/__init__.py`
  - `scripts/knowledge_refresh_demo.py`
- 已实现的核心能力：
  - 新增 `IndexJob` 模型，记录 `job_id`、资源 ID、资源类型、刷新原因、状态、失败原因、chunk 数和 token 数
  - `KnowledgeIndexStore.initialize()` 新增 `index_jobs` SQLite 表和 `status/resource_id` 索引
  - 新增 `enqueue_index_job()`，供手动刷新、定时校验、后续飞书事件订阅统一写入任务
  - 新增 `refresh_resource()`，执行单个资源重索引，并把任务状态更新为 `running/succeeded/skipped/failed`
  - 新增 `enqueue_recent_document_refresh_jobs()`，为最近索引过的资源生成 `scheduled` 刷新任务
  - 新增 `list_index_jobs()` 和 `get_index_job()`，便于调试和后续 worker 查看任务状态
  - `ensure_knowledge_chunk_schema()` 改为幂等迁移，兼容旧库已经部分添加字段时重复初始化
  - `scripts/knowledge_refresh_demo.py` 使用 `NoopVectorIndex` 演示本地刷新链路，避免 demo 依赖外部 embedding 服务或下载模型
- 当前实现边界：
  - 当前已实现队列、手动刷新和定时候选任务生成；后台 worker 消费循环和飞书事件订阅接入仍是后续增强
  - 当前刷新入口依赖调用方传入已拉取的 `Resource/RetrievedResource`；真实 worker 后续需要负责按资源 token 调飞书接口拉取最新内容
- 当前验证方式：
  - 已通过 `python3 scripts/knowledge_refresh_demo.py` 验证：手动 job 从 `pending` 更新为 `succeeded`，并记录 chunk 数、token 数；定时校验可生成 `scheduled` 的 `pending` job
- 后续增强方向：
  - 接入飞书事件订阅，把文档/表格/知识库变更事件写入 `index_jobs`
  - 后台 worker 消费任务并更新 chunk 与检索索引
  - 对权限变化、删除、移动等事件做索引失效处理
  - 记录索引进度、chunk 数、token 数、失败原因和最近处理时间，避免会前工作流误用未完成或已失效索引
- 设计澄清：
  - `updated_at + checksum` 解决的是“系统已经检查资源后，如何判断是否需要重建索引”，不能解决“文档变化瞬间如何知道”的问题
  - 要想第一时间感知飞书文档变化，需要接入飞书事件订阅、Webhook 或 WebSocket 事件流
  - 飞书事件只应作为“资源可能变化”的触发信号，事件处理器不应直接执行重索引重活，而应写入 `index_jobs`
  - `checksum` 仍然必要，因为飞书事件可能由权限、标题、评论、移动等非正文变化触发；worker 拉取最新内容后应再次比较 checksum，确认正文是否真的变化
  - 推荐分层为：事件订阅负责变化感知，`index_jobs` 负责异步排队，`KnowledgeIndexStore` 负责内容校验、chunk 重建和状态落盘
- 建议后续实现的索引任务模型：
  - `IndexJob.job_id`
  - `IndexJob.resource_id`
  - `IndexJob.resource_type`
  - `IndexJob.reason`: `manual | scheduled | feishu_event | dependency`
  - `IndexJob.status`: `pending | running | succeeded | skipped | failed`
  - `IndexJob.last_error`
  - `IndexJob.created_at`
  - `IndexJob.updated_at`
- 建议后续刷新流程：
  - 飞书文档/表格/知识库事件到达
  - 写入 `index_jobs`，状态为 `pending`
  - 后台 worker 拉取最新资源内容
  - 比较 `updated_at + checksum`
  - 内容变化则重建 `KnowledgeChunk`，未变化则标记跳过
  - 更新 `index_status`、`last_indexed_at` 和审计日志
- 验收标准：
  - 文档内容变化后能重新索引并更新召回结果
  - 未变化文档不会重复生成 chunk
  - 索引失败原因可在日志或审计记录中定位

### T3.11 知识域与 embedding 模型一致性治理

- 优先级：`P1`
- 来源：RAGFlow 的知识库会绑定 embedding 模型，并避免不同向量空间混合检索
- 目标：为 MeetFlow 的项目知识域建立清晰的索引命名、模型绑定和兼容性检查
- 设计补充：
  - 增加知识域或索引命名空间概念，用于区分项目、会议来源、embedding 模型和向量维度
  - 文档元数据中记录 `embedding_provider`、`embedding_model`、`embedding_dimensions` 和 collection 名称
  - 检索多个知识域时检查 embedding 模型和维度是否一致，不一致时拆分检索或拒绝混查
  - 切换 embedding 模型后，旧索引应标记为 `stale` 或使用新 collection 重建
- 验收标准：
  - 同一检索请求不会混用不同 embedding 维度的 chunk
  - 切换模型后不会误读旧 Chroma collection
  - 文档或日志能解释当前检索使用的 embedding 模型和索引空间

#### T3.11 当前实现细节

- 已更新文件：
  - `core/knowledge.py`
  - `docs/tasks/m3-pre-meeting.md`
  - `config/README.md`
- 已实现的核心能力：
  - 新增 `embedding_fingerprint`：由 `embedding_provider`、`embedding_model`、`embedding_dimensions` 组成，用来标识一个不可混用的向量空间
  - 新增 `knowledge_namespace`：由 embedding 指纹生成的人类可读命名空间，便于日志、审计和排查
  - `KnowledgeIndexStore` 的 ChromaDB collection 名称改为基于完整 embedding 指纹生成，避免只按模型名和维度隔离时遗漏 provider 差异
  - `index_resource()` 写入文档和 chunk 时，会把 `embedding_provider`、`embedding_model`、`embedding_dimensions`、`embedding_fingerprint`、`knowledge_namespace`、`vector_collection_name` 写入 SQLite 权威 metadata
  - `index_resource()` 的增量跳过逻辑会检查 embedding 指纹；如果正文未变但 embedding 配置变化，不会跳过，会进入新 collection 重建索引
  - `KnowledgeSearchResult` 新增 `knowledge_namespace`、`vector_collection_name`、`embedding_provider`、`embedding_model`、`embedding_dimensions`
  - `search_chunks()` 会先统计当前检索范围内的 embedding domain 状态；如果只有指纹不一致或缺少指纹的旧索引，会拒绝混合检索并返回明确原因
  - SQLite 关键词召回和 Chroma 向量召回回表阶段都会过滤 embedding 指纹不一致的文档，避免同一次检索混用不同向量空间
  - Chroma metadata 同步写入 embedding 指纹和 namespace，便于后续向量库侧审计
- 当前实现边界：
  - 当前策略是“新 embedding 配置使用新 collection，旧索引在检索时被过滤或拒绝混查”；未对所有旧文档批量写入 `stale` 状态，避免读路径隐式修改大量数据
  - 旧版没有 embedding 指纹的索引会被视为 `unknown`，需要重新索引后才能参与当前知识域检索
- 当前验证方式：
  - 已通过 `python3 -m py_compile config/*.py core/knowledge.py core/agent.py scripts/knowledge_tools_demo.py` 验证语法正确
  - 已用临时 SQLite 验证当前 embedding 指纹的数据可以被 `knowledge.search` 检索，并返回 namespace 与 collection 信息
  - 已用临时 SQLite 验证当库中只有旧模型/旧维度索引时，当前配置会拒绝混合检索并说明 incompatible/unknown 数量

### T3.12 扩展 chunk schema 与结构化位置元数据

- 优先级：`P1`
- 来源：RAGFlow 的 chunk 不只保存 text，还保存位置、文档类型、父子关系、关键词和分数字段
- 目标：让 MeetFlow 的 chunk 具备更强的解释、过滤、回链和上下文展开能力
- 设计补充：
  - `KnowledgeChunk` 增加 `chunk_order`、`parent_chunk_id`、`doc_type`、`content_tokens`
  - metadata 增加 `positions`，用于保存 block/range/sheet/row/minute timestamp 等结构化位置
  - metadata 增加 `keywords` / `questions`，用于关键词召回、query 改写和审计解释
  - 表格行 chunk 保留表名、sheet、字段名、行号；妙记 chunk 保留章节、时间戳、发言人；图片或附件 chunk 保留所在标题和前后上下文
- 验收标准：
  - 每个 chunk 都能定位到原始飞书资源中的具体段落、行或时间片段
  - 表格、妙记和文档 chunk 的 metadata 字段可区分来源类型和结构位置
  - `knowledge.fetch_chunk` 能返回结构化位置，而不是只返回纯文本 `source_locator`

#### T3.12 当前实现细节

- 已更新文件：
  - `core/knowledge.py`
  - `docs/tasks/m3-pre-meeting.md`
- 已实现的核心能力：
  - `KnowledgeChunk` 新增 `chunk_order`、`parent_chunk_id`、`doc_type`、`content_tokens`
  - `knowledge_chunks` SQLite 表新增同名列，并在 `KnowledgeIndexStore.initialize()` 中通过 `ensure_knowledge_chunk_schema()` 为旧库自动补列
  - `chunk_resource_text()` 会为每个 chunk 写入顺序、文档类型、粗略 token 数和增强 metadata
  - metadata 统一补充 `positions`、`keywords`、`questions` 和 `doc_type`
  - 文档 chunk 的 `positions` 保留标题、来源类型、source locator 和 chunk 顺序
  - 表格 chunk 的 `positions` 保留 sheet 和行号，metadata 保留表头字段 `fields`
  - 妙记 chunk 的 `positions` 保留章节，并会从 `[00:01]` 等章节标题中提取 `timestamp`
  - `KnowledgeChunkFetchResult` 新增 `positions` 字段，`knowledge.fetch_chunk` 会直接返回结构化位置，调用方不必从纯文本 `source_locator` 反解析
  - ChromaDB metadata 同步写入 `chunk_order`、`parent_chunk_id`、`doc_type`、`content_tokens`，SQLite 仍作为权威元数据来源
- 当前实现边界：
  - `keywords` / `questions` 采用轻量规则提取，不引入中文分词或 LLM 生成；后续可在 T3.13/T3.14 的检索评估中逐步增强
  - `parent_chunk_id` 字段已落库，但父子 chunk 的实际构建和展开逻辑留给 T3.15
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/knowledge.py core/pre_meeting.py scripts/knowledge_index_demo.py scripts/knowledge_tools_demo.py` 验证语法正确
  - 已用本地构造的 chunk 验证 `chunk_order`、`doc_type`、`content_tokens`、`positions`、`keywords` 写入正常
  - 已用临时 SQLite 验证旧库初始化会补齐新增列
  - 已用临时 SQLite 验证 `knowledge.fetch_chunk` 能按 `ref_id` 返回结构化 `positions`

### T3.13 实现可配置混合检索和可解释分数

- 优先级：`P1`
- 来源：RAGFlow 使用关键词召回、向量召回、metadata filter、RRF/权重融合和阈值过滤
- 目标：把当前 ChromaDB 向量召回升级为可解释的混合检索链路
- 设计补充：
  - `knowledge.search` 内部区分 `top_k` 和 `top_n`：前者控制候选召回量，后者控制 evidence pack 返回量
  - 增加默认 `similarity_threshold`、`keyword_weight`、`vector_weight`，并支持 `fusion_strategy=rrf|weighted` 与 `rrf_k`
  - 支持 metadata filters：`project_id`、`meeting_id`、`source_type`、`owner`、`updated_after`、`permission_scope`
  - `KnowledgeSearchHit` 返回 `vector_similarity`、`term_similarity`、`bm25_score`、`vector_rank`、`keyword_rank`、`rrf_score`、`final_score` 和命中原因
  - 当显式指定 `document_id` 或 `source_url` 时，可以放宽相似度阈值，但必须在原因中说明
- 验收标准：
  - 检索结果能说明来自向量命中、关键词命中还是 metadata 过滤
  - 同一 query 可以通过参数控制召回范围和最终返回数量
  - 低于阈值的结果不会进入高置信会前摘要

#### T3.13 当前实现细节

- 已更新文件：
  - `core/knowledge.py`
  - `core/agent.py`
  - `config/loader.py`
  - `config/__init__.py`
  - `config/settings.example.json`
  - `config/README.md`
  - `scripts/knowledge_tools_demo.py`
  - `docs/tasks/m3-pre-meeting.md`
- 已实现的核心能力：
  - `knowledge.search` 内部区分 `top_k` 和 `top_n`：`top_k` 控制候选召回量，`top_n` 控制最终进入 evidence pack 的片段数
  - `KnowledgeIndexStore.initialize()` 新增 SQLite FTS5 表 `knowledge_chunks_fts(chunk_id UNINDEXED, document_id UNINDEXED, title, text, keywords, tokenize='unicode61')`
  - `index_resource()` 写入 `knowledge_chunks` 后会同步刷新 FTS 表：先按 `document_id` 删除旧 FTS 记录，再插入当前文档的可检索子 chunk
  - `parent_section` 不进入 FTS/BM25 精准召回，只保留给 `knowledge.fetch_chunk` 做父级上下文展开，避免长父 chunk 因包含词更多而压过具体子 chunk
  - 新增 `_build_bm25_hits()`：通过 `knowledge_chunks_fts MATCH ? ORDER BY bm25(knowledge_chunks_fts)` 做 BM25 关键词召回，再回表 JOIN `knowledge_chunks` / `knowledge_documents` 补齐标题、URL、metadata、权限、更新时间和证据定位
  - SQLite 不支持 FTS5 或 FTS 表不可用时，`_build_bm25_hits()` 会自动回退到旧 `_build_keyword_hits()` 扫描路径，保证向量失败时仍有关键词兜底
  - `KnowledgeSearchHit` 新增 `bm25_score`、`vector_rank`、`keyword_rank`、`rrf_score`，并保留 `vector_similarity`、`term_similarity`、`final_score` 和旧 `score` 兼容字段
  - 新增 `merge_hybrid_hits_rrf()`：按 `rrf_score = Σ 1 / (rrf_k + rank_i)` 融合 ChromaDB dense vector 排名和 SQLite BM25 排名，默认 `rrf_k=60`
  - 保留旧 `merge_hybrid_hits()` 加权融合逻辑作为 `fusion_strategy="weighted"` 调试选项；默认配置切到 `fusion_strategy="rrf"`
  - 新增 `similarity_threshold`：低于最终分数阈值的结果不会进入高置信 evidence pack
  - 新增 `KnowledgeSearchSettings` 配置段，`config/settings.example.json` 默认 `knowledge_search.fusion_strategy="rrf"`、`knowledge_search.rrf_k=60`，并支持 `MEETFLOW_KNOWLEDGE_FUSION_STRATEGY` / `MEETFLOW_KNOWLEDGE_RRF_K` 环境变量覆盖
  - 新增显式 metadata filter：`filter_project_id`、`filter_meeting_id`、`document_id`、`source_url`、`owner_id`、`updated_after`、`permission_scope`
  - 当显式指定 `document_id` 或 `source_url` 时，检索会放宽相似度阈值，并在 `reason` 中写明“显式资源过滤放宽阈值”
  - `knowledge.search` 工具 schema 已暴露 `top_n`、`similarity_threshold`、`vector_weight`、`keyword_weight`、`fusion_strategy`、`rrf_k` 和上述 metadata filter 参数
- 当前实现边界：
  - 现有 `project_id` / `meeting_id` 仍用于检索增强和 query term 提取，不默认作为硬过滤，避免破坏旧 demo；需要硬过滤时使用 `filter_project_id` / `filter_meeting_id`
  - BM25 使用 `knowledge.sqlite` 中的 chunk 正文和 metadata 派生关键词，不依赖 ChromaDB 内部 `chroma.sqlite3` 或 fulltext 表；ChromaDB 仍只作为可替换的 dense vector 索引层
  - RRF 默认只使用检索器内排名做融合，不直接比较向量相似度和 BM25 原始分数；`term_similarity` 只是 BM25 rank 的解释性归一化分
  - freshness 目前只作为轻量辅助分，不单独暴露为字段；后续 T3.14/T3.15 或评估审计需要时可扩展

#### BM25/RRF 设计沉淀

本次 M3 检索升级的稳定架构口径：

```text
knowledge.sqlite 负责业务主数据、chunk 正文、FTS5/BM25 关键词索引和证据回表
ChromaDB 负责 dense vector 语义向量召回
RRF 负责融合向量排名和 BM25 排名
reranker 是 RRF 之后的可选二阶段精排
```

BM25 的数据库与表：

- 数据库文件：`storage/knowledge/knowledge.sqlite`
- 主数据表：`knowledge_documents`、`knowledge_chunks`
- FTS5 虚拟表：`knowledge_chunks_fts(chunk_id, document_id, title, text, keywords)`
- FTS5 影子表：`knowledge_chunks_fts_config`、`knowledge_chunks_fts_content`、`knowledge_chunks_fts_data`、`knowledge_chunks_fts_docsize`、`knowledge_chunks_fts_idx`

BM25 的运行过程：

1. `KnowledgeIndexStore.initialize()` 创建 `knowledge_chunks_fts`。
2. `index_resource()` 写入 `knowledge_chunks` 后，同步删除并重建该 `document_id` 的 FTS 记录。
3. `_sync_fts_chunks()` 只写入可检索子 chunk，跳过 `parent_section`。
4. `_build_bm25_hits()` 使用 `knowledge_chunks_fts MATCH ?` 和 `bm25(knowledge_chunks_fts)` 排名。
5. BM25 命中后回表 JOIN `knowledge_chunks` / `knowledge_documents`，补齐标题、正文、URL、metadata、权限、更新时间和证据定位。
6. 如果 FTS5 不可用，自动回退到 `_build_keyword_hits()`。

RRF 的运行过程：

1. `_build_hits_from_vector_ids()` 生成向量候选，并写入 `vector_rank`。
2. `_build_bm25_hits()` 生成关键词候选，并写入 `keyword_rank`、`bm25_score`。
3. `merge_hybrid_hits_rrf()` 按 `rrf_score = Σ 1 / (rrf_k + rank_i)` 融合排名，默认 `rrf_k=60`。
4. 同一个 chunk 如果同时被向量和 BM25 排到靠前位置，RRF 分会自然升高；如果只被一个检索器命中，也仍可进入候选集。
5. RRF 之后再进入 `apply_optional_reranker()`；关闭 reranker 时，RRF 排序就是 evidence pack 的最终排序基础。

这套设计避免直接比较向量相似度和 BM25 原始分数，解释时只需要说明“每个检索器内部排第几，以及 RRF 如何按名次融合”。

- 当前验证方式：
  - 已通过 `python3 -m py_compile config/*.py core/knowledge.py core/agent.py scripts/knowledge_tools_demo.py` 验证语法正确
  - 首次在沙箱内运行 `python3 scripts/knowledge_tools_demo.py` 因无法访问 HuggingFace 下载 `BAAI/bge-small-zh-v1.5` 失败；提权允许网络后重跑成功
  - 已通过 `python3 scripts/knowledge_tools_demo.py` 验证 `knowledge.search` 返回 `BM25 命中 3 条；融合策略 rrf；rrf_k=60`，hit 中包含 `bm25_score`、`vector_rank`、`keyword_rank`、`rrf_score`，且 `knowledge.fetch_chunk` 仍可按 `ref_id` 展开父级上下文
  - 2026-04-30 收口验证发现：在无网络沙箱中直接运行 `python3 scripts/knowledge_tools_demo.py` 时，`sentence-transformers` 会尝试访问 HuggingFace HEAD 接口并失败；如果模型已缓存，可用 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 scripts/knowledge_tools_demo.py` 离线复现成功
  - 已通过 `sqlite3 storage/knowledge/knowledge_tools_demo.sqlite "SELECT count(*) FROM knowledge_chunks_fts;"` 验证 FTS 表有 7 条可检索子 chunk
  - 已通过 `sqlite3 storage/knowledge/knowledge_tools_demo.sqlite "SELECT count(*) FROM knowledge_chunks_fts f JOIN knowledge_chunks c ON c.chunk_id=f.chunk_id WHERE c.chunk_type='parent_section';"` 验证 `parent_section` 未进入 BM25 索引，结果为 0
  - 已通过 `sqlite3 storage/knowledge/knowledge_tools_demo.sqlite "SELECT f.chunk_id, bm25(knowledge_chunks_fts) FROM knowledge_chunks_fts f WHERE knowledge_chunks_fts MATCH '\"风险\"' ORDER BY bm25(knowledge_chunks_fts) LIMIT 3;"` 验证 BM25 能按关键词召回正确 chunk
  - 已通过本地 monkeypatch `_fts_index_exists=False` 调用 `_build_bm25_hits()`，验证 FTS5 不可用时返回 `关键词回退 3 knowledge_tool_doc#chunk_5_ac05eff05b3e`

### T3.14 接入可选 reranker 阶段

- 优先级：`P1`
- 来源：RAGFlow 把 reranker 作为独立 provider，并限制送入 reranker 的候选数量
- 目标：在向量召回和关键词召回之后增加可配置重排阶段，提高最终 evidence 的相关性
- 设计补充：
  - 配置项增加 `reranker.provider`、`reranker.model`、`reranker.enabled`、`reranker.top_k`
  - 开发阶段默认关闭 rerank，真实测试阶段可接 bge-reranker、Jina reranker 或 OpenAI-compatible rerank
  - 进入 reranker 的候选集默认限制在 32 或 64 条，避免成本和接口限制失控
  - `KnowledgeSearchHit` 保留 `rerank_score`，最终分数保留融合逻辑，便于审计
- 验收标准：
  - 开启 reranker 后，`knowledge.search` 能在同一 query 下返回重排后的结果
  - 关闭 reranker 时，检索链路仍可正常使用
  - 返回结果能区分 `vector_similarity`、`term_similarity` 和 `rerank_score`

#### T3.14 当前实现细节

- 已更新文件：
  - `config/loader.py`
  - `config/settings.example.json`
  - `config/__init__.py`
  - `config/README.md`
  - `core/agent.py`
  - `core/knowledge.py`
  - `docs/tasks/m3-pre-meeting.md`
- 已实现的核心能力：
  - 配置层新增 `RerankerSettings`，字段包括 `enabled`、`provider`、`model`、`top_k`、`timeout_seconds`
  - `settings.example.json` 新增 `reranker` 配置段，默认 `enabled=false`、`provider=local-rule`、`top_k=32`
  - 支持环境变量覆盖：`MEETFLOW_RERANKER_ENABLED`、`MEETFLOW_RERANKER_PROVIDER`、`MEETFLOW_RERANKER_MODEL`、`MEETFLOW_RERANKER_TOP_K`、`MEETFLOW_RERANKER_TIMEOUT_SECONDS`
  - `create_meetflow_agent()` 初始化 `KnowledgeIndexStore` 时会传入 `settings.reranker`
  - `knowledge.search` 工具 schema 新增 `reranker_enabled`、`reranker_provider`、`reranker_model`、`reranker_top_k`、`reranker_weight`
  - `KnowledgeSearchHit` 新增 `rerank_score`，并保留 `vector_similarity`、`term_similarity`、`final_score`
  - 新增 `apply_optional_reranker()`：在混合检索之后、evidence pack 截断之前执行可选重排
  - 当前实现 `local-rule` provider：根据 query 覆盖率、标题命中、问题命中和完整查询命中生成 `rerank_score`
  - reranker 候选数量限制为最大 64，默认使用配置里的 32，避免后续真实 provider 成本失控
- 当前实现边界：
  - 真实 bge-reranker、Jina 或 OpenAI-compatible rerank provider 尚未接入；当前 provider 用于打通可插拔重排链路和审计字段
  - 开发阶段默认关闭 reranker；只有配置或工具参数显式开启时才会重排
- 当前验证方式：
  - 已通过 `python3 -m py_compile config/*.py core/knowledge.py core/agent.py scripts/knowledge_tools_demo.py` 验证语法正确
  - 已验证 `load_settings()` 能读取默认 `reranker` 配置
  - 已用本地构造的 `KnowledgeSearchHit` 验证开启 `local-rule` 后会写入 `rerank_score` 并改变排序
  - 已用临时 SQLite 验证 `knowledge.search(reranker_enabled=True)` 会返回带 `rerank_score` 的结果，关闭 reranker 时链路仍使用原混合检索

### T3.15 支持 TOC 增强与父子 chunk 展开

- 优先级：`P1`
- 来源：RAGFlow 对结构化文档使用 TOC 增强和父子 chunk 展开
- 目标：让飞书文档、知识库页面和妙记能兼顾精准召回与完整上下文
- 设计补充：
  - 文档解析时保存标题层级、章节路径和目录信息
  - 小 chunk 用于向量召回，章节级 parent chunk 用于 `knowledge.fetch_chunk` 或摘要生成
  - 检索命中某个小 chunk 时，可以按 `parent_chunk_id` 展开同章节上下文
  - 飞书文档标题、妙记章节和表格分组都可以作为 parent chunk 边界
- 验收标准：
  - 命中短片段后可以展开对应章节，而不是只能看到孤立片段
  - 会前摘要使用父级上下文时仍能保留具体命中 chunk 的引用
  - TOC 或章节路径能出现在检索解释和证据回链中

#### T3.15 当前实现细节

- 已更新文件：
  - `core/knowledge.py`
  - `docs/tasks/m3-pre-meeting.md`
- 已实现的核心能力：
  - `chunk_resource_text()` 在生成小 chunk 后，会通过 `attach_parent_chunks()` 按 TOC 路径聚合同章节内容；只有同一章节被拆成多个子 chunk 时才生成 `parent_section`，避免单子 chunk 章节重复保存一份完全相同的父 chunk
  - 多子 chunk 章节会写入稳定 `parent_chunk_id`，metadata 中同步保留 `parent_chunk_id` 和 `toc_path`
  - 文档 chunk 使用标题路径作为 parent 边界；妙记使用章节路径；表格使用 sheet 路径
  - `knowledge.search` 的向量和关键词检索都会跳过 `parent_section`，避免父级长文本抢走小 chunk 的精准召回位置
  - `KnowledgeSearchHit` 新增 `parent_chunk_id` 和 `toc_path`，检索结果能解释命中的章节路径
  - `KnowledgeChunkFetchResult` 新增 `parent_chunk_id`、`parent_text`、`context_chunks` 和 `toc_path`
  - `knowledge.fetch_chunk` 命中子 chunk 后，会按 `parent_chunk_id` 展开同章节 sibling chunks，并在 `context_chunks` 中保留每个 sibling 的 `ref_id`、`chunk_id`、位置和 `is_hit`
- 当前实现边界：
  - parent chunk 目前用于上下文展开和审计，不作为搜索结果返回；后续摘要生成可显式读取 `parent_text`
  - 单子 chunk 章节不创建 parent chunk，此时 `knowledge.fetch_chunk` 直接返回该命中 chunk；多子 chunk 章节才通过 `parent_chunk_id` 展开同章节上下文
  - TOC 路径仍是轻量规则生成，飞书 Docx 原生目录层级读取接入后可以替换为真实层级
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/knowledge.py core/pre_meeting.py scripts/knowledge_index_demo.py scripts/knowledge_tools_demo.py` 验证语法正确
  - 已用本地长章节文档切片验证：同一 TOC 下拆成多个子 chunk 时会生成 parent chunk，且子 chunk 写入 `parent_chunk_id` 和 `toc_path`
  - 已用临时 SQLite 验证 `knowledge.fetch_chunk` 命中子 chunk 后能返回 `parent_text`、同章节 `context_chunks`，并保留具体命中 chunk 的 `is_hit`

### T3.16 实现 evidence pack token budget 与稳定引用格式

- 优先级：`P0`
- 来源：RAGFlow 在 prompt 前统一格式化证据字段，并按 token budget 截断
- 目标：控制 Agent 工具输出长度，同时保证证据引用稳定、可展开、可审计
- 设计补充：
  - 定义 evidence pack 单条 snippet 最大长度和单次工具返回总预算
  - 工具返回统一字段：`ref_id`、`document_id`、`chunk_id`、`title`、`source_url`、`source_locator`、`snippet`、`score`、`reason`
  - 超出预算的结果进入 `omitted_count`，必要时通过 `knowledge.fetch_chunk` 二次展开
  - 卡片和摘要只引用稳定 `ref_id`，避免模型直接引用不稳定的列表序号
- 验收标准：
  - `knowledge.search` 返回内容不会因候选过多而撑爆 Agent 上下文
  - 卡片中的每条关键结论都能通过 `ref_id` 展开到原始 chunk
  - evidence pack 在本地 demo 中能稳定复现同一引用格式

#### T3.16 当前实现细节

- 已更新文件：
  - `core/knowledge.py`
  - `docs/tasks/m3-pre-meeting.md`
- 已实现的核心能力：
  - `KnowledgeIndexStore.search_chunks()` 新增 `evidence_token_budget` 和 `max_snippet_tokens` 参数，默认分别为 600 和 120，工具侧限制最大预算，避免一次检索把长文档片段直接塞入 Agent 上下文
  - `KnowledgeSearchResult` 新增 `token_budget` 和 `used_tokens`，便于审计本次 evidence pack 实际占用
  - `build_evidence_pack()` 会先按单条 snippet 预算压缩片段，再按总预算截断返回条数；被预算裁掉的结果会累计进入 `omitted_count`
  - `knowledge.search` 工具 schema 暴露 `evidence_token_budget` 和 `max_snippet_tokens`，调用方可以按会前摘要场景调整返回证据规模
  - `ref_id` 统一为 `kref_<digest>` 格式，由 `document_id + chunk_id` 稳定生成，不依赖检索结果排序；工具仍保留原始 `chunk_id` 字段用于审计
  - `knowledge.fetch_chunk` 支持用稳定 `ref_id` 或原始 `chunk_id` 展开完整 chunk，返回同一套 `ref_id`，保证 search/fetch 引用闭环
- 当前实现边界：
  - token 估算使用轻量规则，不引入额外 tokenizer 依赖；后续如果接入具体 LLM tokenizer，可替换 `estimate_text_tokens()`
  - 稳定 `ref_id` 面向“已索引 chunk”的可复现引用；如果文档内容变化导致 chunk 重建，旧引用是否长期可追溯需要后续索引版本/审计表支持
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/knowledge.py core/pre_meeting.py scripts/knowledge_tools_demo.py` 验证语法正确
  - 已用本地构造的 `KnowledgeSearchHit` 验证 evidence pack 会按 token budget 截断、生成 `kref_...` 稳定引用，并累计 `omitted_count`

---

## M3 真实环境联调入口

- 新增脚本：
  - `scripts/pre_meeting_live_test.py`
- 相关更新：
  - `scripts/agent_demo.py`
- 适用场景：
  - 选择一条真实日历会议，按当前 embedding 指纹拉取并重建指定文档/妙记索引，然后执行 `pre_meeting_brief`
  - 默认只读联调，确认链路稳定后再加 `--allow-write` 真发卡
- 运行逻辑：
  - 先读取真实日历，在给定时间窗口内选择指定 `event_id` 或最近一条即将开始的会议
  - 可通过 `--doc` / `--minute` 传入真实飞书文档或妙记，脚本会先读取资源，再调用 `KnowledgeIndexStore.index_resource(..., force=True)` 按当前 embedding 指纹重建索引
  - 将真实会议和已索引资源转换为 `meeting.soon` 触发 payload，再进入 `WorkflowRouter -> PreMeetingBriefWorkflow -> Agent Loop`
  - `--llm-provider scripted_debug` 可先稳定验证真实飞书 + 真实知识索引链路；切到 `settings/default/其他 provider` 时可验证真实 LLM
  - 默认不再生成 `storage/reports/m3/` 报告文件；需要排查会议输入、检索 query、资源 chunk、工具命中结果和卡片 payload 草案时，可显式传 `--write-report`
  - 报告会把“可检索子 chunk”和“父级上下文 chunk”分开展示，避免把 parent_section 误读为重复检索片段
  - `scripted_debug` 会优先解析 Agent Loop 消息中的“运行时上下文 JSON”，并用真实会议标题、会议描述和相关资料标题构造 `knowledge.search` query，避免真实联调时继续使用固定的 MeetFlow 调试查询词
  - 默认复用 `updated_at + checksum + embedding_fingerprint` 均未变化的既有索引；只有传 `--force-index` 时才强制重建，减少真实联调时反复下载 embedding 模型和重写向量库的外部不稳定性
  - 人工联调同一会议需要重复发送时，可传 `--idempotency-suffix` 为本次运行生成新的业务幂等键；该方式不清理本地幂等记录，也不绕过 `AgentPolicy`
  - `--write-report` 会按需写入 Markdown 与 JSON 可观察性报告；不传该参数时，脚本只打印运行摘要和 Agent 结果，避免真实联调后继续堆积 `reports/m3` 文件
- 推荐命令：
  - `python3 scripts/pre_meeting_live_test.py --identity user --lookahead-hours 24 --doc '<你的飞书文档 URL>'`
  - `python3 scripts/pre_meeting_live_test.py --identity user --event-id '<真实 event_id>' --doc '<文档 URL>' --minute '<妙记 URL>'`
  - `python3 scripts/pre_meeting_live_test.py --identity user --event-id '<真实 event_id>' --doc '<文档 URL>' --allow-write --enable-idempotency`
  - `python3 scripts/pre_meeting_live_test.py --identity user --event-id '<真实 event_id>' --doc '<文档 URL>' --allow-write --idempotency-suffix '<本次联调标识>'`
- 当前验证方式：
  - 已通过 `python3 -m py_compile scripts/pre_meeting_live_test.py` 验证语法正确
  - 已通过 `python3 scripts/pre_meeting_live_test.py --help` 验证 CLI 参数可正常解析
  - 已确认 `--write-report` 未开启时不会输出 M3 链路可观察性报告，`--report-dir` 仅在显式开启报告时生效
  - 已通过 `python3 -m py_compile scripts/agent_demo.py scripts/pre_meeting_live_test.py` 验证真实联调脚本和 scripted_debug 上下文解析语法正确
  - 已用真实会议 `飞书 AI 校园竞赛-主题分享直播-产品专场` 和真实文档 `飞书 AI 校园挑战赛-线上开赛仪式` 完成只读联调，报告输出到 `storage/reports/m3/pre_meeting_live_ff39cd17f654.md` 与 `storage/reports/m3/pre_meeting_live_ff39cd17f654.json`
  - 早期联调 `pre_meeting_live_ff39cd17f654` 确认链路状态为 `success`，但暴露出飞书 XML 文档被切成 1 个子 chunk + 1 个重复 parent chunk 的问题
  - 已完成飞书 DocxXML/HTML-like 结构化切分优化，并用真实会议 `飞书 AI 校园竞赛-主题分享直播-产品专场` 和真实文档 `飞书 AI 校园挑战赛-线上开赛仪式` 重新只读联调，报告输出到 `storage/reports/m3/pre_meeting_live_da829619a3ba.md` 与 `storage/reports/m3/pre_meeting_live_da829619a3ba.json`
  - 新联调确认链路状态为 `success`，文档被重建为 13 个可检索子 chunk、0 个重复 parent chunk，`knowledge.search` 首条命中为 `「飞书 AI 校园挑战赛」-赛事介绍` 章节，最终生成会前卡片 payload 草案但未发送
  - 已用真实会议同时传入相关文档 `飞书 AI 校园挑战赛-线上开赛仪式` 和弱相关文档 `Trae IDE 模型配置指南` 做 scripted_debug 对照联调，报告输出到 `storage/reports/m3/pre_meeting_live_96fb651ecf42.md` 与 `.json`；结果显示两篇文档都能索引，相关文档 13 个 chunk，弱相关文档 7 个 chunk，脚本查询下 evidence pack 前两条仍来自相关文档
  - 已用 `--llm-provider deepseek` 完成真实模型只读联调，报告输出到 `storage/reports/m3/pre_meeting_live_1f947b7ecf64.md` 与 `.json`；真实模型自主调用多次 `knowledge.search` 和 `knowledge.fetch_chunk`，验证 Agent Loop 不是 scripted_debug 固定流程
  - 已用 `--allow-write` 验证真实模型会看到并尝试调用 `im.send_card`，报告输出到 `storage/reports/m3/pre_meeting_live_400d561a46bd.md`、`191a3355c132.md`、`f5cf80431014.md`；其中 `400d561a46bd` 暴露出模型会传不完整/不稳定卡片参数，`191a3355c132` 暴露出旧幂等键会被 `AgentPolicy` 正确拦截，`f5cf80431014` 暴露出飞书 IM `uuid` 字段不能直接使用内部可读幂等键
  - 已更新 `adapters/feishu_tools.py`：`im.send_card` 支持 title/summary/facts 优先的稳定卡片发送；当模型传入完整 card 但飞书拒绝时，工具会在有 title/summary 的情况下回退到内置最小卡片模板
  - 已更新 `adapters/feishu_client.py`：新增 `normalize_feishu_message_uuid()`，把内部幂等键稳定映射为 `mf_<sha1>` 短 uuid 后再传给飞书 IM 接口，避免把包含冒号和长业务 ID 的内部键原样传给外部接口
  - 当前真实写入发送尚未完成最终成功确认：修复 uuid 后，因环境外部执行审批额度限制，无法继续发起飞书真实网络探针；下一次可直接使用带新 `--idempotency-suffix` 的命令复测
  - 当前联调暴露的检索质量问题：真实模型自由调用 `knowledge.search` 时会搜索全局知识库，可能把历史个人阶段小结等旧文档排到本次补充文档之前；后续需要为会前链路增加“候选文档范围过滤/项目知识域过滤/本次会议资源 boost”，否则弱相关或历史文档可能污染卡片证据
  - 已新增 `--event-title`，支持按日程标题包含匹配真实会议，避免默认选择最近会议时误测其他日程
  - 已修复会前卡片来源链接展示：`cards/pre_meeting.py` 会在完整卡片的待读资料和证据引用中渲染来源 URL；`core/pre_meeting.py` 会在最小 facts 中追加“资料链接”
  - 已收紧 `im.send_card` 的 LLM 可见 schema：不再向模型暴露自由 `card` 参数，避免真实模型自造没有来源链接的卡片；工具层仍统一通过 `title/summary/facts` 生成稳定卡片
  - 2026-04-30 使用真实会议标题 `飞书环境配置` 完成全链路写入联调，报告输出到 `storage/reports/m3/pre_meeting_live_9c44a6ce81cb.md` 与 `.json`；日历中未找到用户口述的 `飞书环境测试`，同日窗口实际匹配到 `飞书环境配置`
  - 本次联调使用三个已给文档：`李健文-个人阶段小结`、`飞书 AI 校园挑战赛-线上开赛仪式`、`Trae IDE 模型配置指南`；索引均复用已有 namespace `sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce`
  - 本次 `knowledge.search` 首要命中为 `Trae IDE 模型配置指南` 的配置步骤 chunk，随后模型通过 `knowledge.fetch_chunk` 展开两个 Trae chunk，并成功调用 `im.send_card`；飞书返回 `message_id=om_x100b501909b7c888b217c7cb23ad2f7`
  - 本次发送结果确认卡片内容包含三篇原始文档链接和会议日历链接；发送者为应用身份，说明 `im.send_card` 默认 tenant 身份可向配置测试群发送
  - 2026-04-30 二次复盘发现真实模型仍可能自行组织 facts，导致卡片背景和链接混排，并把 Unix 时间戳错误换算为 `10:30/14:30`；根因是 workflow goal 只给了原始时间戳，且卡片模板没有强制链接后置
  - 已更新 `scripts/pre_meeting_live_test.py`：`build_live_goal()` 会把会议时间格式化为 `Asia/Shanghai` 的权威展示时间，并明确禁止模型自行换算时间戳；`飞书环境配置` 的 `1777545000-1777546800` 本地格式化为 `2026-04-30 18:30-19:00 Asia/Shanghai`
  - 已更新 `adapters/feishu_client.py`：`build_meetflow_card()` 会把 facts 分为“核心背景知识”和“原始链接”两个区块，链接类 facts 永远后置，避免群卡片阅读结构漂移
  - 已通过 `python3 -m py_compile adapters/feishu_client.py scripts/pre_meeting_live_test.py` 验证语法正确，并用本地函数验证时间格式化和 facts 分组逻辑正确
  - 2026-04-30 按用户偏好更新 `scripts/pre_meeting_live_test.py`：默认不再写入 `storage/reports/m3/pre_meeting_live_*.md/.json`；新增 `--write-report` 作为显式可观察性报告开关，保留复杂链路排查能力
  - 2026-04-30 验证 BM25/RRF 后的真实联调安全边界：直接使用 `--llm-provider deepseek --allow-write` 会把真实会议/文档内容发送给外部 LLM，审批器拒绝；改用 `scripted_debug` 跑真实飞书读写链路
  - 已更新 `scripts/agent_demo.py`：`ScriptedDebugProvider` 在 `knowledge.search` 成功且 `im_send_card` 可用时，会继续调用 `im_send_card`；这只用于受控联调，避免 scripted_debug 停在只读检索阶段
  - 复测发现旧文档在 `updated_at + checksum + embedding_fingerprint` 未变化时会跳过重建，导致后加的 FTS5/BM25 表没有旧 chunk 记录；已更新 `core/knowledge.py`，在资源跳过重建时仍会轻量回填 `knowledge_chunks_fts`
  - 已通过命令 `python3 scripts/pre_meeting_live_test.py --identity user --event-title '飞书环境配置' --lookahead-hours 24 --doc 'https://bytedance.larkoffice.com/docx/KlW9dIlyzo17ccxl26Gc9TGsnig' --llm-provider scripted_debug --max-iterations 5 --allow-write --enable-idempotency --idempotency-suffix 'bm25-rrf-20260430-1346' --write-report` 完成 BM25/RRF 后的全链路真实写入
  - 本次联调只使用一篇真实文档 `Trae IDE 模型配置指南`，索引复用已有 namespace `sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce`，`chunk_count=7`
  - 本次 `knowledge.search` 返回 `混合检索候选 4 条；向量命中 3 条；BM25 命中 3 条；融合策略 rrf；最终返回 2 条；rrf_k=60`，命中结果包含 `BM25召回`、`keyword_rank`、`bm25_score`、`vector_rank` 和 `rrf_score` 解释字段
  - 本次 `im.send_card` 成功向测试群发送交互式卡片：`chat_id=oc_3e432398cc43063fda2b2d322bb6dead`，`message_id=om_x100b501af60f7880b2a6c2ecaf3ad8e`，发送者为应用身份
  - 本次链路文档已写入 `storage/reports/m3/pre_meeting_live_b22f5cf8350e.md` 与 `.json`；Markdown 顶部补充了执行命令、安全说明、BM25/RRF 证据和飞书写入结果
  - 2026-04-30 在用户明确确认外部模型与真实写入风险后，已执行 `deepseek + allow-write` 真实链路：`python3 scripts/pre_meeting_live_test.py --identity user --event-title '飞书环境配置' --lookahead-hours 24 --doc 'https://bytedance.larkoffice.com/docx/KlW9dIlyzo17ccxl26Gc9TGsnig' --llm-provider deepseek --max-iterations 6 --allow-write --enable-idempotency --idempotency-suffix 'deepseek-bm25-rrf-20260430-confirmed' --write-report`
  - 本次 DeepSeek 真实链路状态为 `success`，工具顺序为 `knowledge.search -> knowledge.search -> knowledge.fetch_chunk -> knowledge.fetch_chunk -> im.send_card`，测试群真实消息为 `message_id=om_x100b501b5cce7cb8b2a4c2062fa1cf3`
  - 本次混合检索验证重点：第一次泛查询 `飞书环境配置` 为 `向量命中 8 条 / BM25 命中 0 条`；DeepSeek 随后改用更具体查询 `Trae IDE 模型配置 火山引擎 自定义模型`，结果为 `向量命中 8 条 / BM25 命中 7 条 / 融合策略 rrf / rrf_k=60`
  - 本次 RRF top1 为 `Trae IDE 模型配置指南` 的 `步骤三：添加并配置自定义模型` chunk，解释字段为 `vector_rank=1`、`keyword_rank=1`、`bm25_score=-1.19834`、`rrf_score=0.032787`，验证了向量与 BM25 同时高排名时 RRF 会稳定推到首位
  - 为避免报告过长，本次另写简明链路记录 `storage/reports/m3/pre_meeting_live_239b439075d2_summary.md`；完整原始报告保留在 `storage/reports/m3/pre_meeting_live_239b439075d2.md` 与 `.json`
  - 2026-05-04 新增 `cards/layout.py` 作为 M3/M4 共用卡片骨架，`cards/pre_meeting.py` 的会前背景卡已改为复用统一 `build_interactive_card()`、`markdown()`、`lark_md_div()` 和 `divider()`。卡片业务区块仍保持“主题/状态/摘要 -> 分区资料 -> 证据引用”，但 header/config/分隔符结构与 M4 保持同一套基础格式，避免后续优化时两边样式继续分叉。
  - 2026-05-04 新增 `scripts/card_preview_demo.py`，可用 `python3 scripts/card_preview_demo.py --workflow m3 --print-json` 本地查看 M3 完整卡片 JSON；传 `--output-dir storage/reports/card_preview` 可写出 `m3_pre_meeting/card.json` 和 `payload.json` 供人工 diff。
  - 2026-05-04 新增 `scripts/meetflow_daemon.py` 作为 M3 后台常驻入口。飞书侧可订阅日历事件 `calendar.calendar.event.changed_v4`，用 `lark-cli event +subscribe --event-types calendar.calendar.event.changed_v4 --compact --quiet --as bot | python3 scripts/meetflow_daemon.py --event-stdin --enable-m3 ...` 把事件作为实时唤醒；守护进程仍会按 `--poll-seconds` 扫描日历兜底。当会议进入 `--m3-minutes-before` 窗口时，脚本调用 `card_send_live.py m3` 走既有 Agent/Policy 发卡链路。
  - 2026-05-04 RAG 更新主路径改为长连接优先。新增 `scripts/rag_add_document_live.py`，用户只需首次执行 `python3 scripts/rag_add_document_live.py --doc '<文档链接>' --identity user`，脚本会读取文档、索引并调用飞书云文档事件订阅接口；M3 的 `pre_meeting_live_test.py --doc` 路径也会在索引后自动订阅。后台用 `lark-cli event +subscribe --event-types drive.file.edit_v1,drive.file.title_updated_v1,drive.file.bitable_record_changed_v1 --compact --quiet --as bot | python3 scripts/meetflow_daemon.py --event-stdin --enable-rag ...` 接收更新事件并刷新对应索引，定时扫描只作为兜底。
  - 2026-05-04 新增 `scripts/live_environment_watch.py` 作为 M3/M4/RAG 真实环境观察台。脚本会直接启动飞书长连接，清晰打印收到的日历/云文档事件、日程扫描结果、RAG 索引任务状态和 M3/M4 发卡触发意图；默认真实刷新本地 RAG 索引但不真实发卡，传 `--allow-card-send` 后才允许 M3/M4 走真实发卡链路。脚本支持 `--python-bin` 和 `--lark-cli-bin`，并会在启用 RAG 时自动切换到包含 `chromadb/sentence_transformers` 的 Python，避免与 `lark_oapi` 长连接环境冲突。验证通过：`python3 -m py_compile scripts/live_environment_watch.py`；`python3 scripts/live_environment_watch.py --help`；`.venv-lark-oapi/bin/python scripts/live_environment_watch.py --help`。
