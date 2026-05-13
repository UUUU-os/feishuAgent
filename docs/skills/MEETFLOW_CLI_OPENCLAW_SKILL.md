---
name: meetflow-cli-openclaw
version: 1.2.0
description: "Use the MeetFlow CLI to run pre-meeting, post-meeting, task-card, risk-scan, evaluation, replay, service, and OpenClaw-tool workflows. Defaults to dry-run; real Feishu writes require explicit authorization."
metadata:
  requires:
    bins: ["meetflow", "python3"]
  cliHelp: "meetflow --help"
---

# MeetFlow CLI / OpenClaw

> Run commands from the repository root unless the project has been installed into PATH.
> Prefer `meetflow <module> +<action> [options]`.
> If `meetflow` is not available after downloading the project, run `export PATH="$PWD/bin:$PATH"` or call `bin/meetflow ...` directly.

## 1. When To Use

Use this Skill when the user wants an Agent to operate MeetFlow through the supported CLI surface:

- check local configuration, storage, migrations, and service status;
- generate an M3 pre-meeting briefing card;
- read Feishu Minutes and generate an M4 post-meeting summary card;
- generate the D4 task-card view from meeting minutes;
- run M5 task risk scanning and optional reminder-card sending;
- run Agent evaluation or offline demo replay;
- start or inspect supported local services;
- expose MeetFlow tools to OpenClaw or another external Agent runtime.

Do not use this Skill to execute arbitrary shell commands, arbitrary Python expressions, direct database writes, direct Feishu side effects, or any workflow that bypasses `AgentPolicy`, `ToolRegistry`, the CLI facade, or the configured Feishu client wrappers.

## 2. Setup Check

Before running business workflows, make sure the command exists:

```bash
export PATH="$PWD/bin:$PATH"
meetflow --help
meetflow workflow +health
```

If `meetflow workflow +health` reports missing Feishu config or invalid local authorization, ask the user to configure their local settings and complete OAuth before attempting real Feishu reads or writes. Never print or store access tokens, refresh tokens, app secrets, API keys, or Authorization headers.

## 3. Command Map

| Scenario | Command | Notes |
|---|---|---|
| Health check | `meetflow workflow +health` | No Feishu write; use before demos and debugging |
| Pre-meeting briefing | `meetflow workflow +pre-meeting ...` | Defaults to dry-run; add `--allow-write` only for a confirmed test send |
| Post-meeting summary | `meetflow workflow +post-meeting --minute ...` | Requires a Feishu Minutes link or token |
| Task-card view | `meetflow workflow +task-cards --minute ...` | Reuses the post-meeting controlled path |
| Risk scan | `meetflow workflow +risk-scan --backend local` | Use `local` for demos; use `feishu` only when real task access is configured |
| Agent evaluation | `meetflow workflow +eval --suite agent_trajectory` | No Feishu write |
| Offline replay | `meetflow workflow +demo-replay --all` | No Feishu write; useful when external services are unavailable |
| Service status | `meetflow service +list` | Only manages whitelisted MeetFlow services |
| Service logs | `meetflow service +logs <name>` | Reads logs for whitelisted services only |
| OpenClaw tools | `meetflow openclaw +tools` | Emits the tool catalog JSON |
| SDK callback live process | `meetflow live +sdk-callback` | Foreground long-running process |
| Worker live process | `meetflow live +worker` | Foreground long-running process |
| D3 card live send | `meetflow live +d3-card --minute ...` | Real live-send wrapper unless `--dry-run` is provided |
| Callback log tail | `meetflow live +watch-callbacks` | Foreground log tail command |

Legacy top-level commands may still work for compatibility, but Agents should prefer the `module +action` form above.

## 4. Safety Rules

- Treat every command as dry-run unless the output says otherwise.
- Add `--allow-write` only when the user explicitly asks for a real Feishu write and the target is a test chat or otherwise confirmed safe destination.
- For real pre-meeting card sends, provide an idempotency suffix, for example `--idempotency-suffix "m3-cli-test-001"`.
- Do not claim a card was sent unless the CLI returns `status=success` with `allow_write=true` and the user requested a real send.
- Do not treat `live +d3-card` as a normal dry-run command. It is a live-send helper; add `--dry-run` when only previewing.
- Do not expose secrets in user-facing answers, logs, reports, or documentation.

## 5. Common Workflows

### 5.1 Health Check

```bash
meetflow workflow +health
```

Read `status`, `data.feishu_config_present`, `data.default_chat_configured`, `data.migration`, and `data.services` before recommending a real workflow.

### 5.2 Pre-Meeting Briefing Dry Run

```bash
meetflow workflow +pre-meeting \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --provider scripted_debug \
  --write-report
```

Use `scripted_debug` for quick local verification. Use the project-configured provider only when the user wants a real Agent/LLM run.

### 5.3 Pre-Meeting Real Test Send

```bash
meetflow workflow +pre-meeting \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --provider settings \
  --idempotency-suffix "m3-cli-test-001" \
  --allow-write \
  --write-report
```

Warn the user that a real provider may take longer because the workflow may query Feishu, build context, run retrieval, call the LLM, write reports, and then send the card.

### 5.4 Post-Meeting Summary

```bash
meetflow workflow +post-meeting \
  --minute "<Feishu Minutes link or token>" \
  --show-card-json
```

Add `--allow-write` only when the user explicitly confirms a real card send.

### 5.5 Task-Card View

```bash
meetflow workflow +task-cards \
  --minute "<Feishu Minutes link or token>" \
  --show-card-json
```

Use this when the user asks about action items, task ownership, or task-card grouping.

### 5.6 Risk Scan

```bash
meetflow workflow +risk-scan \
  --backend local \
  --show-card
```

For real Feishu tasks, use `--backend feishu`; add `--allow-write` only when sending the risk reminder card is confirmed.

### 5.7 Evaluation And Replay

```bash
meetflow workflow +eval \
  --suite agent_trajectory \
  --write-report
```

```bash
meetflow workflow +demo-replay \
  --all \
  --write-report
```

Use these commands for regression checks, demos without external connectivity, and evidence that the Agent workflow is reproducible.

### 5.8 OpenClaw Tool Catalog

```bash
meetflow openclaw +tools
```

Use the emitted JSON tool catalog as the integration source for OpenClaw or another Agent runtime.

## 6. Output Contract

Most workflow commands output JSON. Agents should inspect these fields:

| Field | Meaning |
|---|---|
| `status` | `success` or `failed`; never claim success when this is failed |
| `workflow_type` | Business workflow identifier |
| `trace_id` | Correlates CLI output with reports and logs |
| `dry_run` | Whether side effects were suppressed |
| `allow_write` | Whether this invocation allowed a real write |
| `report_path` | Local report artifact path when generated |
| `agent_trace_path` | Evaluation or trace artifact path when available |
| `command` | Redacted downstream whitelist command |
| `data` | Structured workflow-specific result |
| `error` | Redacted failure message |
| `safety_summary` | Safety and redaction summary |

If a command fails, summarize the redacted `error`, then suggest focused checks such as OAuth authorization, Feishu app configuration, test chat configuration, Minutes permission, worker status, or service logs.

## 7. Troubleshooting

| Symptom | Likely Cause | Suggested Action |
|---|---|---|
| `meetflow: command not found` | `bin` is not on PATH | Run `export PATH="$PWD/bin:$PATH"` from the repo root |
| `feishu_config_present=false` | Local Feishu config is missing | Ask the user to configure local settings; do not request secrets in chat |
| OAuth or token error | User authorization expired or missing | Ask the user to complete the project OAuth login flow |
| Real card send is slow | Real LLM/RAG/Feishu calls are running | Explain that the synchronous CLI waits for the full Agent workflow |
| No card received | Wrong chat config, missing bot permission, send failed, or still running | Check CLI JSON, report path, service logs, and Feishu app/chat setup |
| `--allow-write: command not found` | Shell line continuation has a trailing space after `\` | Remove spaces after `\` or run the command on one line |
| `live +d3-card` would send unexpectedly | Missing `--dry-run` | Add `--dry-run` for preview-only use |

## 8. Agent Response Guidance

When reporting results to the user:

- Say exactly which command was run.
- State whether it was dry-run or a real write.
- Mention the `report_path` when present.
- Summarize the useful business result, not just that the command exited.
- Clearly call out unresolved risk, missing config, or anything that still needs user confirmation.
