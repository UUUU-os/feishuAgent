# 仓库清理与 GitHub 上传准备记录

## 任务目标

清理本地运行产物、依赖包、缓存、下载二进制和可能包含敏感信息的运行数据，降低上传 GitHub 时误提交密钥、token、真实业务数据或无意义文件的风险。

## 当前基线

- 当前目录不是可用 Git 仓库；`.git` 是运行环境挂载点，`git status` 返回“不是 git 仓库”。
- 项目包含 Python 后端、前端 Console、飞书本地联调脚本和运行数据目录。
- 本轮没有修改业务代码。

## 已完成内容

- 删除 Python 缓存与编译产物：`__pycache__/`、`*.pyc`。
- 删除可再生成依赖与构建产物：`.venv-lark-oapi/`、`frontend/node_modules/`、`frontend/dist/`、`frontend/tsconfig.tsbuildinfo`。
- 删除本地运行数据和报告：`storage/*.sqlite`、`storage/*.jsonl`、`storage/runtime/`、`storage/knowledge/`、`storage/reports/`、`storage/projects/`、`storage/post_meeting_pending_actions.json`。
- 删除无意义根目录文件：空的 `--chat-id`、`--doc`、`--event-title`、`-H`、`-X`、`-d` 等命令参数残留文件。
- 删除下载二进制和孤立锁文件：`cloudflared-linux-amd64.deb`、根目录 `package-lock.json`。
- 补强 `.gitignore`，覆盖本地密钥配置、环境变量文件、Agent/编辑器元数据、运行数据、依赖包、构建产物、下载二进制和误生成参数文件。
- 精简根目录 Markdown：根目录仅保留 `README.md`，其余设计、任务、联调和协作文档入口保留在 `docs/` 或 `docs/tasks/` 下。
- 更新 `README.md` 和 `docs/demo/index.html`，移除指向已删除根目录 Markdown 与 `frontend/dist/` 的链接。

## 涉及文件

- `.gitignore`
- `README.md`
- `docs/demo/index.html`
- `docs/tasks/repository-cleanup-github-prep.md`

## 验证方式

- `find` 检查已无 `__pycache__`、`node_modules`、`dist`、`.venv*`、`*.pyc`、`*.sqlite`、`*.db`、`*.jsonl`、`*.tsbuildinfo`、`*.deb` 等待清理产物。
- `du -sh .` 确认项目目录由约 281M 降至约 4.1M。
- `rg` 按 `app_secret`、`refresh_token`、`access_token`、`api_key`、`Bearer`、`sk-` 等关键词扫描；剩余命中为文档字段名、示例占位符、测试假 key 或代码脱敏逻辑，未发现真实本地配置文件。

## 剩余风险

- `.git`、`.agents`、`.codex` 是当前运行环境挂载点，无法在本轮删除；已在 `.gitignore` 屏蔽。若要在此目录直接 `git init`，需要先在普通文件系统副本中操作，或由宿主环境移除空 `.git` 挂载点。
- 上传 GitHub 前仍建议重新运行一次敏感词扫描，并确认没有新增 `config/*.local.json`、`.env*` 或 `storage/` 运行数据。
