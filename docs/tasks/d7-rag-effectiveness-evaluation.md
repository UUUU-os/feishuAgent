# D7 RAG 与 Agent 效果评测落地记录

## 1. 目标

D7 的目标是让 MeetFlow 在比赛答辩中能回答“项目效果如何”，尤其是 RAG 对会前和会后工作流是否真的有帮助。
本轮不追求线上全量评测，而是先建立一套 40 条真实业务风格脱敏样本、可复现、可解释的离线评测，
用来支撑演示和后续回归。

参考文章：[18. 怎么量化你的 RAG 效果？](https://xiaolinnote.com/ai/rag/18_evaluation.html)

## 2. 评测方法

本轮采用分层评测：

| 层级 | 指标 | 说明 |
|---|---|---|
| 检索层 | Hit@3、MRR | 评估正确证据 chunk 是否被召回，以及排名是否靠前 |
| 上下文层 | Context Recall、Context Precision | 评估 Top-K 检索结果是否覆盖必要证据，以及噪声比例 |
| 生成层 | Faithfulness、Answer Relevancy、Evidence Coverage | 用结构化事实和证据 ID 校验答案是否有依据、是否回答问题、关键事实是否有证据 |
| 业务层 | 会前结构完整度、会后行动项字段完整率、风险识别召回/精确率 | 对应 MeetFlow 的会前、会后、任务风险提醒主链路 |
| Agent 层 | 工具调用 F1、禁止工具检查、Policy/幂等/allow-write gate、演示稳定性 | 证明不是脚本拼接，而是可审计、受控的 Agent 工作流 |

其中 Hit@K、MRR、Context Recall/Precision、Faithfulness、Answer Relevancy 等指标口径与参考文章一致；
由于本轮评测要稳定离线可复现，Faithfulness 暂不调用 LLM-as-a-Judge，而是用人工标注的 `fact_id`
和 `support_chunk_ids` 做结构化校验。

## 3. 测试数据

数据位置：`tests/e2e_fixtures/d7_rag_effectiveness/case.json`

测试数据为脱敏业务样本，RAG 语料也保存在同一个 fixture 中，作为离线评测时“存入 RAG 的文档”：

- 30 个语料 chunk：PRD、架构说明、D2-D8 方案、历史会议、当前妙记、遗留任务、风险记录、Agent Trace、OpenClaw 指南和无关噪声文档。
- 40 条 RAG 查询：覆盖会前背景、遗留任务、授权风险、会后行动项、安全边界、OpenClaw、工具轨迹和评测解释。
- 3 条工作流样本：会前卡片、会后总结/任务、任务风险提醒。
- 3 条 Agent 轨迹样本：会前检索、会后保存 pending action、写操作安全拦截。

这些样本刻意覆盖会前和会后最容易被评委追问的点：

- RAG 是否能找回历史会议结论。
- RAG 是否能找回遗留任务和负责人。
- 会后任务抽取是否能识别负责人、截止时间和证据。
- 风险提醒是否能解释 OAuth token、allow-write、Policy 等工程安全边界。

### 3.1 什么是一条测试样本

一条测试样本不是一个文档，而是一道带标准答案的小考题。它通常包含：

- 输入：用户问题、会议场景或工作流上下文。
- 可用材料：一个或多个文档 chunk、妙记片段、任务记录、风险记录，也可以包含无关噪声材料。
- 标注答案：期望召回哪些证据、期望识别哪些事实、期望输出哪些字段。
- 评分规则：例如 Hit@3、MRR、Evidence Coverage、行动项字段完整率。

例子：

```text
问题：
本次妙记里每个人要做什么，截止时间是什么？

可用材料：
- 当前会议妙记 chunk
- 历史任务 chunk
- 无关报销制度 chunk

标准答案：
- 叶抒锐：补齐 CLI 文档，2026-05-14
- 李健文：修复负责人解析授权错误，2026-05-13
- 王宁：整理答辩 FAQ，2026-05-15

评分：
- 是否召回当前妙记 chunk
- 是否识别 3 个行动项
- 负责人、任务标题、截止时间是否正确
- 每个行动项是否有证据来源
```

所以，一个文档只是被检索的材料；一个 chunk 是文档切分后的片段；一条测试样本是一次完整评测任务；
一个评测集是一组测试样本。

## 4. 实现文件

- `scripts/d7_rag_effectiveness_eval.py`
  - 运行 D7 离线评测。
  - 输出 JSON。
  - 可写入 Markdown 与 JSON 报告。
- `tests/e2e_fixtures/d7_rag_effectiveness/case.json`
  - D7 脱敏评测样本。
- `tests/test_d7_rag_effectiveness_eval.py`
  - 锁定综合分、Hit@3、MRR、Evidence Coverage、RAG 对比提升和安全分。
- `docs/evaluation/d7_rag_effectiveness_report.md`
  - 答辩可读报告。
- `docs/evaluation/d7_rag_effectiveness_report.json`
  - 机器可读报告。

## 5. 评测结果

运行命令：

```bash
python3 scripts/d7_rag_effectiveness_eval.py --write-report --fail-under 0.85
```

结果摘要：

| 维度 | 指标 | 结果 | 含义 |
|---|---:|---:|---|
| 综合 | overall_score | 0.9489 | 四层评测综合分超过 0.85 门槛。 |
| 检索层 | Hit@3 | 1.0000 | 40 条问题的 Top-3 检索结果里都至少包含 1 个正确证据，说明 RAG 基本能找对方向。 |
| 检索层 | MRR | 0.9458 | 正确证据通常排在很靠前的位置，用户问题大多能第一时间命中关键材料。 |
| 检索层 | Context Recall | 0.8792 | 标准答案所需证据大约 87.92% 被 Top-3 覆盖，说明多证据问题仍有少量漏召回。 |
| 检索层 | Context Precision | 0.3583 | Top-3 里约 35.83% 是标注相关证据，说明召回稳定但仍混入噪声，需要后续 rerank 或压缩上下文。 |
| RAG 生成 | Faithfulness | 1.0000 | 结构化答案中的事实都能追溯到标注证据，暂未发现无依据事实。 |
| RAG 生成 | Answer Relevancy | 1.0000 | RAG 版本回答覆盖了每个问题要求识别的关键事实。 |
| RAG 生成 | Evidence Coverage | 1.0000 | 每个关键事实都有证据 chunk 支撑，便于会前/会后卡片展示 Evidence Pack。 |
| 非 RAG 基线 | score | 0.1736 | 不使用 RAG 时只能命中少量通用事实，几乎没有证据支撑，说明 RAG 对效果提升明显。 |
| 会前卡片 | 结构与证据分 | 1.0000 | 会前卡片能完整覆盖背景、历史结论、遗留任务、风险、建议议题和证据来源。 |
| 会后总结/任务 | 结构与行动项分 | 1.0000 | 会后总结结构完整，行动项负责人、标题、截止时间和证据字段都齐全。 |
| 任务风险提醒 | 风险与证据分 | 1.0000 | 风险类型识别、精确率和证据覆盖均满足样本预期，适合解释“为什么提醒”。 |
| Agent 工程 | 工具/安全/稳定性分 | 1.0000 | 工具调用、禁止工具检查、Policy/幂等/allow-write gate 和敏感信息扫描全部通过。 |

结论：

> D7 离线评测显示 MeetFlow 在 40 条业务风格脱敏样本上达到可演示水位：RAG 检索能稳定召回关键证据，
> 生成结果证据覆盖明显优于非 RAG 基线，Agent 工具轨迹和安全策略可解释。

需要诚实说明的点：

- `Context Precision=0.3583`，说明 Top-3 检索中仍有噪声，后续可以通过 rerank 或减少送入 LLM 的 chunk 数优化。
- 当前评测是 40 条业务风格脱敏样本，不代表线上全量用户分布。
- 当前生成层指标用结构化事实校验，不是完整 RAGAs LLM-as-a-Judge；后续可以接入 judge model 做自然语言答案评分。

## 6. 验证命令

```bash
python3 -m py_compile scripts/d7_rag_effectiveness_eval.py tests/test_d7_rag_effectiveness_eval.py
python3 -m unittest tests.test_d7_rag_effectiveness_eval
python3 scripts/d7_rag_effectiveness_eval.py --write-report --fail-under 0.85
```

验证结果：

- 编译检查通过。
- `tests.test_d7_rag_effectiveness_eval` 通过，1 条测试。
- D7 评测脚本通过，生成 `docs/evaluation/d7_rag_effectiveness_report.md` 和
  `docs/evaluation/d7_rag_effectiveness_report.json`。

## 7. 答辩口径

可以这样回答评委：

> 我们没有只说 Agent 能生成卡片，而是把效果拆成检索层、生成层、业务层和 Agent 安全层。
> RAG 部分用 Hit@3、MRR、Context Recall/Precision 评估证据召回；
> 生成部分用 Faithfulness、Answer Relevancy 和 Evidence Coverage 评估是否有依据、是否回答问题；
> 业务部分再看会前、会后、任务风险三个工作流是否完整。
> 在 40 条业务风格脱敏样本上，RAG 生成质量分为 1.0000，非 RAG 基线为 0.1736，综合分 0.9489。
> 这说明 RAG 对会前背景、历史任务、风险证据和会后任务落地有直接提升。

## 8. 遗留风险

- 需要后续引入更多真实脱敏飞书妙记、文档和任务记录，降低人工编写样本的分布偏差。
- 可引入 LLM-as-a-Judge 或 RAGAs 做自然语言层面的 Faithfulness / Relevancy 复核。
- 线上指标还需要结合真实使用数据，包括点踩率、追问率、转人工率、任务创建成功率和用户修正率。
