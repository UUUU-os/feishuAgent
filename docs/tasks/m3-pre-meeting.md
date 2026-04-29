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
  - `chunk_document_text()`：按标题、段落、列表和表格行切分飞书文档文本
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
  - 当前清洗输入是已读取到的 `Resource` / `RetrievedResource`，真实飞书资源读取仍沿用 M2 的 adapter 和后续 T3.6 工具链
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/*.py scripts/knowledge_index_demo.py scripts/pre_meeting_retrieval_demo.py scripts/workflow_runner_demo.py` 验证语法正确
  - 已通过 `python3 scripts/knowledge_index_demo.py` 验证文档、表格、妙记三类资源可清洗为 `KnowledgeDocument` 和 `KnowledgeChunk`
  - 已验证同一资源第二次索引会因为 `updated_at + checksum` 未变化返回 `status=skipped`
  - 已验证本地创建 `storage/knowledge/knowledge.sqlite`，且可以读取文档元数据和 chunk 列表

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

### T3.8 接入会前定时触发

- 优先级：`P0`
- 目标：在会议开始前固定时间自动执行
- 验收标准：
  - 能通过定时或模拟触发运行整个工作流
  - 不重复发送相同卡片
  - 触发后进入 `PreMeetingBriefWorkflow` 骨架，而不是直接把事件丢给 LLM 自由处理

### T3.9 增加手动兜底入口

- 优先级：`P1`
- 目标：支持命令式触发
- 示例：
  - “生成项目 A 今日会前卡片”
- 验收标准：
  - 自动触发失败时仍可演示主能力

### T3.10 预留知识变更更新机制

- 优先级：`P1`
- 目标：为后续监听飞书文档、表格、知识库变化预留索引刷新入口
- M3 实现边界：
  - 记录资源 `updated_at`、`checksum`、`last_indexed_at`、`index_status`
  - 支持按资源 token 手动触发重新索引
  - 支持对最近被会议引用过的资源做定时校验
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
  - `IndexJob.status`: `pending | running | succeeded | failed`
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

### T3.13 实现可配置混合检索和可解释分数

- 优先级：`P1`
- 来源：RAGFlow 使用关键词召回、向量召回、metadata filter、权重融合和阈值过滤
- 目标：把当前 ChromaDB 向量召回升级为可解释的混合检索链路
- 设计补充：
  - `knowledge.search` 内部区分 `top_k` 和 `top_n`：前者控制候选召回量，后者控制 evidence pack 返回量
  - 增加默认 `similarity_threshold`、`keyword_weight`、`vector_weight`
  - 支持 metadata filters：`project_id`、`meeting_id`、`source_type`、`owner`、`updated_after`、`permission_scope`
  - `KnowledgeSearchHit` 返回 `vector_similarity`、`term_similarity`、`final_score` 和命中原因
  - 当显式指定 `document_id` 或 `source_url` 时，可以放宽相似度阈值，但必须在原因中说明
- 验收标准：
  - 检索结果能说明来自向量命中、关键词命中还是 metadata 过滤
  - 同一 query 可以通过参数控制召回范围和最终返回数量
  - 低于阈值的结果不会进入高置信会前摘要

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
