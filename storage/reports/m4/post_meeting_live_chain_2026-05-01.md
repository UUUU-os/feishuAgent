# M4 真实链路运行报告

生成时间：2026-05-01 13:50 Asia/Shanghai

## 目标

本次目标是用真实飞书妙记链接验证 M4 会后总结与任务落地链路：

```text
飞书妙记
-> 读取妙记 AI 产物/正文
-> 构造 PostMeetingInput
-> 清洗纪要
-> 抽取决策、开放问题、Action Items
-> 标记低置信/待确认任务
-> 生成会后总结卡片和待确认卡片
-> 通过 ToolRegistry + AgentPolicy 执行发卡和建任务
-> 保存 task_mappings 给 M5 风险巡检使用
```

用户提供的妙记链接：

- `https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11`
- `https://jcneyh7qlo8i.feishu.cn/minutes/obcn9xr813z8jcz9en81cyqc`
- `https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i`

## 关键入口

真实链路入口脚本：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute '<真实妙记 URL>' --read-only --content-limit 300
python3 scripts/post_meeting_live_test.py --identity user --minute '<真实妙记 URL>' --allow-write --send-card --content-limit 300
```

脚本核心路径：

- `FeishuClient.fetch_minute_resource(...)`：读取真实妙记资源。
- `build_workflow_input_from_resource(...)`：把飞书资源转换成 M4 的 `PostMeetingInput`。
- `build_post_meeting_artifacts_from_input(...)`：生成 M4 结构化产物。
- `run_write_phase(...)`：在显式 `--allow-write` 后执行真实写入。
- `execute_with_policy(...)`：所有写工具先经过 `AgentPolicy.authorize_tool_call()`，再交给 `ToolRegistry.execute()`。

## 已实际执行的步骤

### 1. 真实妙记只读尝试

执行过的命令：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11' --read-only --content-limit 800
```

结果：

- 首次在沙箱网络中访问飞书开放平台失败，原因是网络/代理访问 `open.feishu.cn` 受限。
- 在用户批准外部网络访问后，第一条妙记读取成功。
- 读取到的妙记标题为：`飞书 AI 校园竞赛-主题分享直播-产品专场`。
- 该内容进入了 M4 清洗、决策抽取、开放问题抽取、Action Item 抽取和卡片预览链路。

### 2. 真实内容暴露的问题

第一次真实只读暴露出一个抽取规则问题：

- 飞书 AI 摘要里存在大量普通编号段落。
- 旧规则会把部分普通背景、议程或说明性段落误判成 Action Item。

已经修复：

- 收紧 `core/post_meeting.py` 的 Action Item 候选行规则。
- 当前优先从显式待办章节、任务前缀、负责人/截止时间信号中抽取任务。
- 删除了过宽的编号标题检测，降低普通段落误建任务风险。

### 3. OAuth 授权恢复

后续再次访问飞书时遇到 OAuth 刷新失败：

- 飞书 OAuth token 接口返回 HTTP 400。
- 飞书错误码：`20064`。
- 判断原因：第一次成功读取时触发 token refresh，但当时脚本没有把新的 refresh token 写回本地配置，导致后续 refresh token 失效。

已经修复：

- `scripts/post_meeting_live_test.py` 创建 `FeishuClient` 时已接入 token 回写：

```python
FeishuClient(
    settings.feishu,
    user_token_callback=lambda bundle: save_token_bundle(settings, bundle),
)
```

恢复动作：

```bash
python3 scripts/oauth_device_login.py
```

用户已完成飞书 OAuth Device Flow 授权。脚本已成功写回本地配置。

安全说明：

- 本报告不记录 access token、refresh token、app secret、API key。
- 授权输出中只确认了当前用户 open_id 和姓名，不记录任何令牌明文。

### 4. Tenant 身份验证

曾尝试用 `tenant` 身份读取妙记。

结果：

- 飞书返回权限不足，错误码 `99991672`。
- 提示应用机器人身份缺少妙记读取相关 scope，例如 `minutes:minutes` / `minutes:minutes:readonly` / `minutes:minutes.basic:read` 之一。

结论：

- 当前真实妙记读取应先走 `user` 身份。
- 如果后续希望机器人身份读取妙记，需要在飞书开发者后台补齐 scope、发布版本，并重新授权/生效。

## 当前链路状态

已完成：

- M4 本地业务链路已实现。
- 真实妙记只读链路已至少成功跑通第一条链接的一次读取与解析。
- OAuth 用户授权已恢复。
- 后续 user token refresh 已具备持久化回写能力。
- 写入路径已具备 `ToolRegistry` + `AgentPolicy` 保护。
- `task_mappings` 已扩展 M5 需要的稳定字段。
- 2026-05-01 13:46-13:47 已对 3 条真实妙记完成只读复验。
- 2026-05-01 13:46-13:47 已对 3 条真实妙记执行 `--allow-write --send-card` 灰度写入。
- 测试群已收到真实 interactive card，消息发送结果均为 `success`。

尚未完成：

- 尚未创建新的飞书任务。本轮真实妙记抽出的 Action Items 均缺少负责人、截止时间或置信度不足，按 M4 安全规则进入待确认，不自动创建任务。
- 尚未产生新的真实 `task_mappings` 写入记录。当前本地 `task_mappings` 仍只有历史 demo 记录 `item_demo_001 -> task_demo_001`。

## 本轮真实执行结果

### 1. 逐条只读复验

#### 妙记 1

命令：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11' --read-only --content-limit 300
```

结果：

- 标题：`飞书 AI 校园竞赛-主题分享直播-产品专场`
- 读取状态：成功。
- `raw_text_length`：2677。
- 决策：3 条。
- 开放问题：0 条。
- Action Items：1 条。
- Pending Action Items：1 条。
- 卡片预览：
  - `summary_card`：9 个元素。
  - `pending_card`：4 个元素。
- 写入：只读模式跳过。
- 业务判断：待办“链接分享...”缺负责人和截止时间，置信度 0.45，进入待确认，不可自动建任务。

#### 妙记 2

命令：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://jcneyh7qlo8i.feishu.cn/minutes/obcn9xr813z8jcz9en81cyqc' --read-only --content-limit 300
```

结果：

- 标题：`妙计测试2`
- 读取状态：成功。
- `raw_text_length`：195。
- 飞书返回状态：当前没有返回 AI 总结、待办或章节。
- 决策：0 条。
- 开放问题：0 条。
- Action Items：0 条。
- Pending Action Items：0 条。
- 卡片预览：
  - `summary_card`：7 个元素。
  - `pending_card`：2 个元素，但由于没有待确认任务，真实写入时不会发送 pending card。
- 写入：只读模式跳过。

#### 妙记 3

命令：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i' --read-only --content-limit 300
```

结果：

- 标题：`飞书 AI 校园挑战赛-开赛仪式（线上直播）`
- 读取状态：成功。
- `raw_text_length`：5113。
- 决策：0 条。
- 开放问题：6 条。
- Action Items：3 条。
- Pending Action Items：3 条。
- 卡片预览：
  - `summary_card`：9 个元素。
  - `pending_card`：4 个元素。
- 写入：只读模式跳过。
- 业务判断：
  - “仓库创建填写...”有截止时间候选“今天”，但缺负责人，置信度 0.70，进入待确认。
  - “文档创建提交...”有截止时间候选“今天”，但缺负责人，置信度 0.70，进入待确认。
  - “文档发送...”缺负责人和截止时间，置信度 0.45，进入待确认。

### 2. 灰度真实写入

#### 妙记 1 写入

命令：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11' --allow-write --send-card --content-limit 300
```

结果：

- 任务创建：0 条。
- 跳过任务：1 条，原因是缺负责人、缺截止时间、置信度低于 0.75。
- 发送卡片：2 张，均成功。
- `summary_card`：
  - `status`: `success`
  - `message_id`: `om_x100b5077abda28a4b206dbc5e392247`
  - `chat_id`: `oc_3e432398cc43063fda2b2d322bb6dead`
- `pending_card`：
  - `status`: `success`
  - `message_id`: `om_x100b5077abd20ca4b2441b1bc851959`
  - `chat_id`: `oc_3e432398cc43063fda2b2d322bb6dead`

#### 妙记 2 写入

命令：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://jcneyh7qlo8i.feishu.cn/minutes/obcn9xr813z8jcz9en81cyqc' --allow-write --send-card --content-limit 300
```

结果：

- 任务创建：0 条。
- 跳过任务：0 条。
- 发送卡片：1 张，成功。
- `summary_card`：
  - `status`: `success`
  - `message_id`: `om_x100b5077ab15fca4b24aa2a666da705`
  - `chat_id`: `oc_3e432398cc43063fda2b2d322bb6dead`
- 未发送 `pending_card`，因为没有待确认任务。

#### 妙记 3 写入

命令：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i' --allow-write --send-card --content-limit 300
```

结果：

- 任务创建：0 条。
- 跳过任务：3 条，原因是缺负责人、缺截止时间或置信度低于 0.75。
- 发送卡片：2 张，均成功。
- `summary_card`：
  - `status`: `success`
  - `message_id`: `om_x100b5077a8a0fcb0b2452a302df3e32`
  - `chat_id`: `oc_3e432398cc43063fda2b2d322bb6dead`
- `pending_card`：
  - `status`: `success`
  - `message_id`: `om_x100b5077a8b8e8a0b3b13674966a687`
  - `chat_id`: `oc_3e432398cc43063fda2b2d322bb6dead`

### 3. 写入后检查

检查命令：

```bash
sqlite3 storage/meetflow.sqlite "select count(*) from task_mappings;"
sqlite3 storage/meetflow.sqlite "select item_id, task_id, meeting_id, minute_token, title, owner, due_date, updated_at from task_mappings;"
```

结果：

- `task_mappings` 当前共 1 条，为历史 demo 记录。
- 本次真实写入没有新增 `task_mappings`，因为没有任何 Action Item 满足自动创建任务条件。
- 当前记录：
  - `item_id`: `item_demo_001`
  - `task_id`: `task_demo_001`
  - `owner`: `lear-ubuntu-22`
  - `due_date`: `2026-04-26`

## 安全结论

本轮真实写入符合 M4 安全规则：

- 真实卡片已发送到飞书测试群。
- 所有写操作均通过 `ToolRegistry` 和 `AgentPolicy`。
- 缺负责人、缺截止时间、置信度不足的任务没有被自动创建。
- 没有绕过策略层直接调用飞书写接口。
- 没有在报告中记录 token、secret 或 API key。

## 2026-05-01 规则修复后重测

### 修复点

- 负责人识别：新增 `@姓名` / `@所有参赛同学` 解析，避免把有 mention 的待办误判为“缺少负责人”。
- 截止时间识别：新增 `今天或最晚明天`、`今天到明天`、`今天或明天`、`最晚明天` 等复合表达，避免只截成“今天”并把标题删坏。
- 标题清洗：去掉待办编号和末尾 `@mention`，保留正文里的截止时间表达，不再生成“于或最晚明天”这类破损标题。
- 群体负责人兜底：`所有参赛同学` 会作为负责人候选展示，但标记为“缺少可解析负责人”，不会直接创建飞书任务。
- 开放问题过滤：过滤 `常见问题答疑`、`技术指导`、章节目录等标题型噪声，只保留真实问题句。
- 报告输出：`scripts/post_meeting_live_test.py` 新增 `--report-dir`，每次真实运行都会生成 M3 风格 Markdown 报告，记录输入、阶段、Action Items、卡片和写入结果。

### 重新执行命令

只读复验：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11' --read-only --content-limit 300 --report-dir storage/reports/m4/rerun_2026-05-01
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://jcneyh7qlo8i.feishu.cn/minutes/obcn9xr813z8jcz9en81cyqc' --read-only --content-limit 300 --report-dir storage/reports/m4/rerun_2026-05-01
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i' --read-only --content-limit 300 --report-dir storage/reports/m4/rerun_2026-05-01
```

灰度写入：

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11' --allow-write --send-card --content-limit 300 --report-dir storage/reports/m4/rerun_2026-05-01
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://jcneyh7qlo8i.feishu.cn/minutes/obcn9xr813z8jcz9en81cyqc' --allow-write --send-card --content-limit 300 --report-dir storage/reports/m4/rerun_2026-05-01
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i' --allow-write --send-card --content-limit 300 --report-dir storage/reports/m4/rerun_2026-05-01
```

### 重测结果

- 3 条妙记只读复验均成功，并各自生成 Markdown 报告。
- 3 条妙记灰度写入均成功完成发卡阶段，并各自生成 Markdown 报告。
- 本轮再次发送 5 张真实卡片：
  - `obcnb2q4nap98l5ny5as2n11`：summary card + pending card。
  - `obcn9xr813z8jcz9en81cyqc`：summary card。
  - `obcn7xk3bg1olx8lb811fq4i`：summary card + pending card。
- 第三条妙记的 Action Items 修复后结果：
  - `仓库创建填写...`：owner_candidate=`所有参赛同学`，due_date_candidate=`今天或最晚明天`，confidence=`0.80`，needs_confirm=`True`，原因=`缺少可解析负责人`。
  - `文档创建提交...`：owner_candidate=`所有参赛同学`，due_date_candidate=`今天到明天`，confidence=`0.80`，needs_confirm=`True`，原因=`缺少可解析负责人`。
  - `文档发送...`：owner_candidate=`王恂`，due_date_candidate=`未识别`，confidence=`0.70`，needs_confirm=`True`，原因=`缺少截止时间；置信度低于阈值 0.75`。
- 第三条妙记的开放问题从旧版 6 条噪声收敛为 1 条真实问题：`存在全量预加载代价高的问题...`。
- 本轮仍没有创建飞书任务，也没有新增真实 `task_mappings`。原因是没有 Action Item 同时满足“可解析负责人 open_id + 明确截止时间 + 足够置信度 + 证据引用”。

### 新报告文件

- `storage/reports/m4/rerun_2026-05-01/post_meeting_live_obcnb2q4nap98l5ny5as2n11_readonly_20260501_135931.md`
- `storage/reports/m4/rerun_2026-05-01/post_meeting_live_obcnb2q4nap98l5ny5as2n11_write_20260501_140001.md`
- `storage/reports/m4/rerun_2026-05-01/post_meeting_live_obcn9xr813z8jcz9en81cyqc_readonly_20260501_135944.md`
- `storage/reports/m4/rerun_2026-05-01/post_meeting_live_obcn9xr813z8jcz9en81cyqc_write_20260501_140020.md`
- `storage/reports/m4/rerun_2026-05-01/post_meeting_live_obcn7xk3bg1olx8lb811fq4i_readonly_20260501_135946.md`
- `storage/reports/m4/rerun_2026-05-01/post_meeting_live_obcn7xk3bg1olx8lb811fq4i_write_20260501_140023.md`

## 已执行命令汇总

### 1. 逐条只读复验命令

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11' --read-only --content-limit 300
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://jcneyh7qlo8i.feishu.cn/minutes/obcn9xr813z8jcz9en81cyqc' --read-only --content-limit 300
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i' --read-only --content-limit 300
```

执行结果：3 条均成功。

### 2. 灰度真实写入命令

```bash
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11' --allow-write --send-card --content-limit 300
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://jcneyh7qlo8i.feishu.cn/minutes/obcn9xr813z8jcz9en81cyqc' --allow-write --send-card --content-limit 300
python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i' --allow-write --send-card --content-limit 300
```

执行结果：3 条均成功完成卡片发送阶段，共发送 5 张卡片；没有创建任务，因为没有满足自动建任务条件的 Action Item。

### 3. 写入后检查命令

```bash
sqlite3 storage/meetflow.sqlite "select count(*) from task_mappings;"
sqlite3 storage/meetflow.sqlite "select item_id, task_id, meeting_id, minute_token, title, owner, due_date, updated_at from task_mappings;"
python3 -m py_compile core/*.py adapters/*.py config/*.py cards/*.py scripts/*.py
```

执行结果：

- `task_mappings` 未新增真实记录，原因同上。
- 语法检查通过。

## 风险与注意事项

- M4 当前目标是会后卡片与飞书任务落地，不负责创建或修改飞书日程。
- 真实写入必须显式使用 `--allow-write`。
- 群发卡片依赖配置中的 `default_chat_id`，或命令行显式传入 `--chat-id`。
- 机器人发卡使用 `tenant` 身份，需要机器人在测试群内，并具备消息发送权限。
- 任务创建使用 user 授权和飞书任务 scope，需要 `task:task:write`。
- 不应绕过 `ToolRegistry`、`AgentPolicy` 或 `FeishuClient` 直接调用写接口。

## 本次结论

M4 的真实链路已经跑通到“真实读取妙记 -> 生成 M4 产物 -> 通过策略发送飞书卡片”。本轮共发送 5 张真实卡片。任务创建没有发生，是因为真实纪要里的 Action Items 均未满足自动创建条件；这说明当前安全策略按预期工作，没有为了演示效果强行创建缺字段任务。
