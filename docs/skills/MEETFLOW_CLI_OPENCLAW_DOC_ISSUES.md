# MeetFlow CLI / OpenClaw 文档与代码不一致记录

本文件记录在编写 `docs/skills/MEETFLOW_CLI_OPENCLAW_SKILL.md` 时发现的文档、期望口径与当前代码实现之间的不一致或需澄清点。

## 1. `live` 命令不是标准 JSON 输出

- 不一致位置：`docs/openclaw-meetflow-tool-guide.md` 的“输出格式”章节写有“CLI 只输出 JSON”。
- 代码真实情况：`scripts/meetflow_cli.py::run_live_from_args()` 会打印“将执行：”和下游命令，然后通过 `subprocess.call()` 前台运行底层脚本；`live sdk-callback`、`live worker`、`live d3-card`、`live watch-callbacks` 都不返回 `CLIResult` JSON。
- 文档当前说法：容易让 AI / OpenClaw 误以为所有子命令都可按标准 JSON 解析。
- 建议修复方式：在使用手册中明确“常规业务命令输出标准 JSON，`live` 命令组是人工真实联调长进程/发卡包装，不保证 JSON 输出”；后续可为 `live d3-card --dry-run` 增加 `--json` 输出。

## 2. `live d3-card` 默认不是 dry-run

- 不一致位置：`docs/openclaw-meetflow-tool-guide.md` 开头写有“所有命令默认是 dry-run”。
- 代码真实情况：推荐命令为 `scripts/meetflow_cli.py live +d3-card`；旧入口 `live d3-card` 仍兼容。不加 `--dry-run` 时，会调用 `scripts/card_send_live.py m4` 且不附加 `--dry-run`；`card_send_live.py m4` 会包装真实发卡链路。
- 文档当前说法：同一文档 D3 章节又说明“如果只想打印下游命令，不发送卡片，需要加 `--dry-run`”，这与开头总述存在冲突。
- 建议修复方式：把总述改为“常规业务命令默认 dry-run；`live d3-card` 是真实联调快捷命令，不加 `--dry-run` 会发送卡片”。

## 3. 顶层 `suggested_fix` 字段尚未实现

- 不一致位置：Skill 需求要求“如果 `status=failed`，必须读取 `error` 和 `suggested_fix`”。
- 代码真实情况：`core/cli_facade.py::CLIResult` 当前字段包括 `status`、`workflow_type`、`trace_id`、`dry_run`、`allow_write`、`report_path`、`agent_trace_path`、`command`、`data`、`error`、`safety_summary`，没有顶层 `suggested_fix`。
- 文档当前说法：现有使用手册 JSON 样例也没有 `suggested_fix`。
- 建议修复方式：短期在 Skill 中要求 AI 优先读取 `error`，若输出包含 `suggested_fix` 再读取；长期给 `CLIResult` 增加可选 `suggested_fix` 字段，并在常见错误处结构化生成修复建议。

## 4. `health` 不直接验证 OAuth token 有效性

- 不一致位置：使用手册在真实飞书联调前建议运行 `health` 和 `scripts/oauth_device_login.py`，容易被理解为 `health` 能完整判断 OAuth token 是否有效。
- 代码真实情况：`core/cli_facade.py::MeetFlowCLI.health()` 检查飞书 app 配置、默认群、storage、migration、服务状态和 LLM provider，但不主动调用飞书 API 验证 `user_access_token` 是否仍可用。
- 文档当前说法：没有明确说明 `health` 只能检查本地配置存在性，不能保证 token 权限/有效期。
- 建议修复方式：在手册和 Skill 中说明 OAuth 有效性要通过真实飞书读操作或重新运行 `python3 scripts/oauth_device_login.py` 验证；后续可新增只读 token 检查命令。

## 5. `service start` 已实现但手册弱化展示

- 不一致位置：`docs/openclaw-meetflow-tool-guide.md` 的“其他服务控制”只展示 `service list`、`service logs`、`service stop`。
- 代码真实情况：`scripts/meetflow_cli.py` 和 `core/service_manager.py` 已实现 `service start <name> --profile <profile>`，白名单服务包括 `worker`、`sdk_callback`、`m4_callback`。
- 文档当前说法：为避免与 D3 四终端流程重复，手册没有展开 `service start` 示例。
- 建议修复方式：保留当前手册的 D3 优先口径，同时在 Skill 中说明 `service start` 是已实现能力，但 D3 人工四终端联调优先用 `live` 命令。
