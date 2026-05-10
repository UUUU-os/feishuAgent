# Git 协作规范

本文档用于约束 MeetFlow 后续 5 天冲刺开发的 Git 协作方式，目标是减少冲突、降低合并成本，并保证比赛演示链路始终可运行。

## 默认集成分支

当前分支 `feature/one-click-live-test-console` 作为后续默认集成分支。

后续所有功能分支都从这个分支切出，并最终合并回这个分支。除非团队重新约定，不再以 `main` 或 `develop` 作为日常集成目标。

推荐命名：

```bash
feature/ai-rag-auto-strategy
feature/ai-litellm-gateway
feature/runtime-worker-concurrency
feature/runtime-console-health
fix/frontend-build-types
docs/demo-runbook
```

## 基本原则

核心原则是：

> 小分支、短周期、早同步、少改共享文件。

冲突多通常不是 Git 本身的问题，而是分支活太久、PR 太大、多人同时修改同一个热点文件。

## 每次开发前

开始新任务前，先回到默认集成分支并同步远端：

```bash
git checkout feature/one-click-live-test-console
git pull --ff-only origin feature/one-click-live-test-console
```

再切出自己的任务分支：

```bash
git checkout -b feature/your-task-name
```

一个分支只做一个小目标，尽量在半天到两天内合回默认集成分支。

## 开发过程中

如果任务超过半天，建议至少同步一次默认集成分支：

```bash
git fetch origin
git rebase origin/feature/one-click-live-test-console
```

如果不习惯 rebase，也可以使用 merge：

```bash
git fetch origin
git merge origin/feature/one-click-live-test-console
```

团队内建议统一一种方式。比赛冲刺阶段更推荐 `rebase`，因为提交历史更线性，冲突也能更早暴露。

## 提交前检查

提交前先看自己改了哪些文件：

```bash
git status --short
git diff --stat
```

只提交和当前任务相关的文件。不要把本地配置、运行数据、缓存、截图临时文件混进提交。

推荐至少跑：

```bash
python3 -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

如果修改了前端，还需要跑：

```bash
cd frontend
npm run build
```

如果 `npm run build` 因项目依赖缺失失败，应单独修复依赖问题，不要把功能代码和依赖修复混在一个大提交里。

## 合并前流程

推送自己的分支：

```bash
git push -u origin feature/your-task-name
```

开 PR 前，再同步一次默认集成分支：

```bash
git fetch origin
git rebase origin/feature/one-click-live-test-console
```

解决冲突后重新跑测试。确认通过后，再请求合并。

## 文件 Ownership

为了减少冲突，后续按功能划分文件归属。

AI / RAG / LLM 相关文件默认由负责 AI 的同学修改：

- `core/knowledge.py`
- `core/llm.py`
- `core/agent.py`
- `core/agent_loop.py`
- `core/tools.py`
- `config/llm_providers.example.json`
- `config/settings.example.json` 中的 `llm`、`embedding`、`reranker`、`knowledge_search` 配置段
- `scripts/*llm*`
- `scripts/*rag*`
- `scripts/*knowledge*`
- AI/RAG/LLM 相关测试文件

运行服务 / 高并发 / Console 后端相关文件默认由负责 runtime 的同学修改：

- `scripts/meetflow_console_server.py`
- `scripts/meetflow_worker.py`
- `core/console_api.py`
- `core/jobs.py`
- `core/service_manager.py`
- `core/migrations.py`
- `frontend/src/api/*`
- `frontend/src/pages/JobsHealthPage.tsx`
- `frontend/src/pages/LiveFlowPage.tsx`
- `frontend/src/components/ServiceControlPanel.tsx`
- runtime/job/console 相关测试文件

共享契约文件需要双方共同确认后再改：

- `core/models.py`
- `config/loader.py`
- 新增的 `core/contracts.py` 或 `core/ai_facade.py`
- README 和演示文档
- 任何会影响两边输入输出结构的类型定义

## 热点文件处理

以下文件容易产生冲突，修改前先在群里说一声：

- `README.md`
- `core/models.py`
- `core/__init__.py`
- `config/loader.py`
- `config/settings.example.json`
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`
- `frontend/src/App.tsx`

如果某个任务必须修改热点文件，建议先开一个很小的 PR，只改契约或结构，再让双方基于新结构继续开发。

## 不要做的事

- 不要在功能 PR 里做全项目格式化。
- 不要把重命名、移动文件和业务功能混在一个提交里。
- 不要在自己的分支里长期积累大量改动。
- 不要直接提交 `config/*.local.json`、`storage/*.sqlite`、`storage/*.jsonl`、`frontend/node_modules/`。
- 不要在没有沟通的情况下修改对方负责范围内的核心文件。

## 推荐提交粒度

好的提交：

- `feat(ai): add auto strategy selector for knowledge search`
- `feat(runtime): add worker concurrency option`
- `docs: clarify branch workflow`
- `fix(frontend): add missing react type dependencies`

不好的提交：

- `update`
- `fix all`
- `final version`
- `big changes`

## 比赛冲刺建议

剩余时间有限，优先保证闭环可演示：

1. 默认集成分支必须随时能启动 Console。
2. 每个功能分支合并前至少跑后端单测。
3. 大功能通过 feature flag 或配置开关接入。
4. 最后一天冻结功能，只修 bug、补文档、录演示。

## 一句话总结

后续统一合并到 `feature/one-click-live-test-console`。每个人从它切短分支，小步开发，频繁同步，只改自己负责范围内的文件；共享契约先沟通再改。
