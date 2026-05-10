# Agent Development Instructions

This repository uses `AGENTS.md` as the standing instruction file for coding agents.

Before making code changes, read and follow:

- `tasks.md`
- `git-instruction.md`
- `team-work-division.md`

The goal is to keep the sprint branch runnable, reduce merge conflicts, and avoid coupling between the AI/RAG/LLM work and the runtime/high-concurrency work.

## Default Integration Branch

Treat `feature/one-click-live-test-console` as the default integration branch for this project.

All feature branches should be created from it and merged back into it unless the human team explicitly changes this rule.

Do not assume `main` or `develop` is the active integration target for day-to-day work.

## Required Workflow Before Development

Before starting a task:

1. Check the current branch and working tree.
2. Find the matching task in `tasks.md` and read that task's goal, suggested files, and acceptance criteria.
3. Read `team-work-division.md` and identify which ownership area the task belongs to.
4. Keep changes inside the relevant ownership area whenever possible.
5. If the task requires modifying shared contracts or another person's ownership area, call that out before making broad edits.

Recommended commands:

```bash
git status --short
git branch --show-current
```

## Task Tracking

Use `tasks.md` as the source of truth for sprint task status.

Before implementation, identify the relevant task id, such as `TASK-01-02`, and follow only that task's requirements plus any directly related shared-contract task.

After implementation, update the corresponding "完成记录" in `tasks.md`.

Keep task records short. Record only:

- final status,
- branch or commit when available,
- files actually changed,
- concrete behavior implemented,
- checks actually run,
- important remaining risk or blocker.

Do not paste long logs, full diffs, detailed reasoning, or repeated summaries into `tasks.md`. If no code changed, say that briefly.

## Ownership Boundaries

Follow the boundaries in `team-work-division.md`.

AI/RAG/LLM work should stay mainly in:

- `core/knowledge.py`
- `core/llm.py`
- `core/agent.py`
- `core/agent_loop.py`
- `core/tools.py`
- `core/evaluation.py`
- `core/eval_metrics.py`
- AI/RAG/LLM scripts and tests
- `core/ai_facade.py`
- `core/ai_runtime/*`
- LiteLLM-related config and demos

Runtime/high-concurrency work should stay mainly in:

- `scripts/meetflow_console_server.py`
- `scripts/meetflow_worker.py`
- `scripts/meetflow_daemon.py`
- `core/console_api.py`
- `core/jobs.py`
- `core/service_manager.py`
- `core/storage.py`
- `core/migrations.py`
- `core/observability.py`
- Console/runtime frontend files
- Runtime/job/console tests
- `core/runtime_service/*`

Shared contract files require extra care:

- `core/models.py`
- `config/loader.py`
- `config/settings.example.json`
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`
- `core/contracts.py`
- `core/ai_facade.py`
- `README.md`
- Demo and runbook documents

When changing shared contracts, keep the change small and document which side must adapt.

## Coupling Rules

Runtime code should call the AI layer through `core/ai_facade.py` or another explicitly agreed facade.

Runtime code should not directly reach into RAG/LLM internals such as `core/knowledge.py` or `core/llm.py`.

AI/RAG/LLM code should not directly modify worker scheduling, job persistence, Console API routing, or frontend runtime state unless the task explicitly requires a shared contract update.

Prefer stable input/output dataclasses or typed dictionaries over passing loosely shaped dictionaries across layers.

## Before Editing Files

Before making edits, check whether the file is:

- owned by the current task area,
- shared contract surface,
- or owned by the other person.

If it is shared or owned by the other person, keep the patch minimal and explain the reason in the final response.

Do not perform broad formatting, large file moves, or unrelated cleanup in feature work.

## Required Checks Before Commit

Before any agent creates, recommends, or prepares a commit, it must follow the checks in `git-instruction.md`.

At minimum:

```bash
git status --short
git diff --stat
```

For backend Python changes, run:

```bash
python3 -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

For frontend changes, run:

```bash
cd frontend
npm run build
```

If a check cannot be run, report that clearly and explain why.

## Commit Hygiene

Only include files related to the current task.

Do not commit local secrets, local config, runtime databases, generated caches, dependency folders, or third-party source clones.

Never commit:

- `config/*.local.json`
- `storage/*.sqlite`
- `storage/*.jsonl`
- `storage/third_party/*`
- `frontend/node_modules/*`
- `.env`
- temporary screenshots or logs unless they are intentionally added as demo artifacts

Use scoped commit messages such as:

- `feat(ai): add rag auto strategy selector`
- `feat(runtime): add worker concurrency limit`
- `fix(frontend): repair console build`
- `docs: clarify agent workflow`

## Conflict Avoidance

Keep branches short-lived and changes small.

If a task must modify a hotspot file listed in `git-instruction.md`, prefer a small contract-only change first.

Avoid mixing:

- feature code and dependency fixes,
- file renames and behavior changes,
- formatting and logic changes,
- AI-layer changes and runtime-layer changes.

## Final Response Expectations

When finishing a task, summarize:

1. What changed.
2. Which ownership area was touched.
3. Whether shared contract files were changed.
4. Which checks were run.
5. Any checks that could not be run.
