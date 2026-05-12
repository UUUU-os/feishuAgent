# MeetFlow 真实飞书群联调演示视频录制稿

本文档用于录制 MeetFlow 项目演示视频。它不是普通技术文档，而是一份可以照着执行和解说的录制脚本，包含视频流程、解说词、终端命令、真实飞书群测试步骤、会议内容准备稿、异常处理话术和项目创新点说明。

录制目标不是只证明某个脚本能运行，而是完整展示 MeetFlow 具备真实业务联调能力、工程化测试能力、Agent 轨迹评测能力和可持续迭代能力。

> 2026-05-06 更新：本录制稿已按 `docs/meetflow-full-live-test-runbook.md` 重新设计。视频主线以 MeetFlow Console、前端 `真实联调` 页面、M3/M4/M5 真实飞书群闭环为准；下方原会议素材继续作为 M4 妙记内容准备材料保留。

---

# 录制总设计：Console 版真实飞书群闭环

## A. 视频定位

本视频要展示的不是“我运行了几个脚本”，而是：

```text
MeetFlow 已经具备从本地 Console 到真实飞书群的完整业务联调能力：
1. 会前 M3：读取飞书日历并发送会前背景卡
2. 会后 M4：读取飞书妙记并发送会后总结卡、待确认任务卡
3. 群内交互：用户在飞书群点击确认任务，回调服务承接按钮动作
4. 风险 M5：读取任务和映射关系，发送风险巡检卡
5. 工程化：Console API、前端控制台、Worker、SDK 回调、Job 队列、报告和评测都可检查
```

建议成片时长：

```text
精简版：8 - 10 分钟
完整版：12 - 18 分钟
答辩版：15 分钟左右，保留关键解说和异常处理口径
```

## B. 录制窗口布局

建议录屏前固定 4 个窗口：

```text
左上：浏览器，打开 MeetFlow Console 前端
右上：飞书测试群
左下：终端 1，Console API
右下：终端 2，前端 Vite
```

可选窗口：

```text
终端 0：一次性质量检查，只录关键命令和成功结果
编辑器：展示 runbook 和代码结构，只在开头或结尾短暂展示
```

录制时不要打开：

```text
config/settings.local.json
config/llm_providers.local.json
任何 token 文件
飞书真实生产群
真实客户会议资料
```

## C. 录制前准备清单

录制前先完成，不一定全部录入视频：

```text
1. 飞书测试群已创建，机器人已进群
2. config/settings.local.json 已配置 default_chat_id
3. OAuth user 授权可用
4. 飞书日历有测试会议
5. 有一条真实飞书妙记链接
6. .venv-lark-oapi 可导入 lark_oapi
7. Node.js/npm 可用
8. 本地数据库 migration 正常
9. 前端真实联调页面可以加载
```

建议测试会议：

```text
标题：MeetFlow 测试会议
时间：2026-05-07 10:00 - 10:30
参与人：添加你自己
描述：这是 MeetFlow M3 会前卡片测试会议
```

注意：2026-05-06 执行 `tomorrow` 时，M3 查询的是 2026-05-07 本地整天。

## D. 录制中使用的占位符

录制时把这些占位符替换成你的真实测试值，但不要在文档或视频里暴露敏感配置：

```text
<MINUTE_URL>：飞书妙记链接
<CHAT_ID>：飞书测试群 chat_id；如果已配置 default_chat_id，可以不填
<EVENT_ID>：可选，飞书日程 event_id
<FRONTEND_URL>：http://127.0.0.1:5173
<CONSOLE_API_URL>：http://127.0.0.1:8787
```

## E. 终端启动脚本

### E.1 终端 0：可选质量检查

这一段可以录，也可以录完后剪成 20 秒快放。

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify
```

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python -c "import lark_oapi; import scripts.feishu_event_sdk_server; print('sdk server import ok')"
```

解说词：

```text
正式进入真实飞书联调前，我先跑一组最小质量检查：Python 编译、Console API 单测、SQLite migration 校验和飞书 SDK 隔离环境导入。这样后续演示如果失败，我们能判断更可能是配置、授权或真实飞书环境问题，而不是基础代码不可运行。
```

### E.2 终端 1：Console API

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787
```

解说词：

```text
这里启动的是 MeetFlow Console API。前端不会直接执行任意命令，而是通过这个本地 API 调用白名单脚本、查询 SQLite、读取报告和管理 Worker 等长期服务。真实飞书写入仍然经过后端脚本、AgentPolicy 和飞书客户端封装。
```

### E.3 终端 2：前端 Vite

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main/frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开：

```text
http://127.0.0.1:5173
```

解说词：

```text
前端是 MeetFlow Console。本次演示主要通过它完成，避免像早期那样打开多个终端分别输入命令。现在大部分真实联调操作都可以在浏览器里执行，并看到状态、日志、stdout 摘要和业务记录。
```

## F. 视频镜头脚本

### 镜头 1：开场与项目定位

屏幕：

```text
浏览器或编辑器展示 README / docs/meetflow-full-live-test-runbook.md 标题
```

操作：

```text
快速展示 runbook 标题和流程列表
```

解说词：

```text
大家好，今天演示的是 MeetFlow。它不是一个单纯的会议总结脚本，而是一个面向飞书会议场景的垂直业务 Agent。我们会从本地 Console 出发，完整跑一遍真实飞书群联调：会前卡片、会后总结、待确认任务卡、群内按钮确认、风险巡检，以及后台队列和运行报告检查。
```

### 镜头 2：启动 Console API 和前端

屏幕：

```text
终端 1 显示 Console API 已启动
终端 2 显示 Vite ready
浏览器打开 Dashboard
```

解说词：

```text
这一版演示只需要手动保留两个长期终端：一个是 Console API，一个是前端 Vite。Worker、SDK 回调和 M4 按钮回调可以在前端真实联调页面里启动。这样演示者不需要在七八个终端之间来回切换。
```

### 镜头 3：Dashboard 总览

屏幕：

```text
MeetFlow Console Dashboard
```

操作：

```text
点击刷新状态
展示 migration、evaluation、jobs 摘要
```

解说词：

```text
进入 Dashboard 后先看系统是否可运行。这里能看到 migration、最近任务、最新评测报告和核心功能入口。它的作用是让演示前的健康状态可见，而不是等到真实发卡失败后才去翻日志。
```

### 镜头 4：Jobs / Health 检查

屏幕：

```text
Jobs / Health 页面
```

操作：

```text
点击刷新
点击 Worker Dry-run
展示 workflow_jobs 表
```

解说词：

```text
Jobs / Health 页面用于检查后台任务队列和 migration。这里的 Worker Dry-run 不会执行真实写入，只确认 Worker 能正常解析队列和 pending job。后面如果选择入队执行 M5 风险巡检，也会在这里看到 job 状态。
```

### 镜头 5：真实联调页面启动服务

屏幕：

```text
真实联调页面 -> 服务控制区
```

操作：

```text
点击 Worker 启动
点击 SDK 回调启动，或点击 M4 按钮回调启动
点击查看日志
刷新状态
```

推荐录制选择：

```text
如果只演示 M4 待确认任务按钮：启动 M4 按钮回调
如果要统一演示 M3/M4 卡片动作：启动 SDK 回调
```

不要同时启动：

```text
SDK 回调
M4 按钮回调
```

解说词：

```text
真实联调页面的第一块是服务控制。这里可以启动 Worker、SDK 回调或者 M4 按钮回调。需要注意的是，SDK 回调和 M4 按钮回调都会监听飞书卡片按钮事件，真实点击时建议二选一，避免重复处理。启动后可以直接查看日志和 PID。
```

### 镜头 6：M3 会前卡片 dry-run

屏幕：

```text
M3 会前页面
```

操作：

```text
日期窗口：tomorrow
会议标题：MeetFlow 测试会议
LLM Provider：scripted_debug
写入报告：勾选
允许真实发卡：不勾选
点击运行 Dry-run
```

解说词：

```text
先演示 M3 会前卡片。这里从飞书日历定位会议，生成会前背景信息，并准备发送飞书卡片。第一步我先跑 dry-run，它只打印下游命令和执行计划，不会真实发卡。这样可以确认日期窗口、会议标题和 provider 都正确。
```

### 镜头 7：M3 真实发送会前卡片

屏幕：

```text
M3 页面 + 飞书测试群
```

操作：

```text
勾选允许真实发卡
点击确认并发卡
弹窗确认
切到飞书群查看 M3 会前卡片
回到前端查看 trace_id / report_path
```

解说词：

```text
确认 dry-run 没问题后，再打开真实写入开关。这个开关会触发二次确认，避免误发生产群。真实发送后，我们可以在飞书测试群看到会前背景卡，同时前端也会显示 trace_id 和报告路径，方便后续追踪。
```

如果 M3 找不到会议，录制时备用话术：

```text
如果这里提示找不到会议，通常是日期窗口不匹配。今天是 2026-05-06，tomorrow 指 2026-05-07 本地整天。可以改成 today、绝对日期，或者直接填写 event_id。
```

### 镜头 8：M4 妙记只读解析

屏幕：

```text
真实联调页面 -> M4 会后总结区
```

操作：

```text
飞书妙记链接：<MINUTE_URL>
Identity：user
Content Limit：300 或 800
允许真实发送 M4 卡片：不勾选
点击只读解析妙记
```

解说词：

```text
接下来进入 M4 会后总结。这里输入飞书妙记链接，先做只读解析。只读模式会读取妙记、抽取会议内容、生成会后 artifacts，但不会发卡，也不会创建任务。它适合在真实写入前确认 OAuth、妙记权限和内容解析都正常。
```

### 镜头 9：M4 dry-run

屏幕：

```text
真实联调页面 -> M4 运行结果
```

操作：

```text
点击 M4 Dry-run
展示命令和 stdout
```

解说词：

```text
M4 dry-run 会走统一发卡入口，但不会真实发送飞书卡片。这里能看到命令、returncode、stdout 和解析结果。这个设计是为了让真实联调从无副作用逐步推进到有副作用。
```

### 镜头 10：M4 真实发送总结卡和待确认任务卡

屏幕：

```text
真实联调页面 + 飞书测试群
```

操作：

```text
勾选允许真实发送 M4 卡片
点击真实发送 M4
弹窗确认
切到飞书群查看会后总结卡和待确认任务卡
```

解说词：

```text
现在打开 M4 真实写入。M4 会向测试群发送两类卡片：一张是会后总结卡，另一张是待确认任务卡。待确认任务不是直接无脑创建，而是先让用户在飞书群里确认负责人、截止时间和任务内容。
```

### 镜头 11：飞书群内按钮确认任务

屏幕：

```text
飞书测试群 + 真实联调服务日志
```

操作：

```text
在飞书群点击待确认任务卡按钮
如果字段完整，点击确认创建
如果字段缺失，保存修改后再确认
回到真实联调页刷新状态
展示 Review Sessions / Task Mappings
```

解说词：

```text
这里展示的是 MeetFlow 的安全策略：会后任务不会因为 LLM 生成了一段文字就直接写入飞书任务。它会进入待确认卡片，由用户点击确认。回调服务收到 card.action.trigger 后，继续经过后端处理和策略检查，成功后会留下 review session 和 task mapping，后续 M5 风险巡检也可以复用这些映射关系。
```

异常处理话术：

```text
如果点击按钮后没有反应，优先检查回调服务是否 running，确认 SDK 回调和 M4 按钮回调没有同时启动，再看服务日志里是否收到 card.action.trigger。
```

### 镜头 12：M5 local dry-run

屏幕：

```text
真实联调页面 -> M5 风险巡检区
```

操作：

```text
Backend：local
Mode：direct
展示风险卡片 JSON：勾选
允许真实发送风险提醒：不勾选
点击运行 M5
```

解说词：

```text
M5 是风险巡检。先用 local backend 做无副作用 dry-run，它会构造本地样本任务，展示逾期、长期未更新、即将截止、缺少负责人等风险类型，并生成风险卡片 JSON。
```

### 镜头 13：M5 feishu dry-run

屏幕：

```text
真实联调页面 -> M5 运行结果
```

操作：

```text
Backend：feishu
Mode：direct
Identity：user
Send Identity：tenant
允许真实发送风险提醒：不勾选
点击运行 M5
```

解说词：

```text
接下来切到 feishu backend，真实读取我的飞书任务，但仍然不发送消息。这里主要验证 user 身份读取任务、风险规则和降噪决策是否正常。
```

### 镜头 14：M5 真实发送风险卡

屏幕：

```text
真实联调页面 + 飞书测试群
```

操作：

```text
勾选允许真实发送风险提醒
点击真实执行 M5
弹窗确认
切到飞书测试群查看风险巡检卡
回到前端刷新 Risk Notifications
```

解说词：

```text
最后打开 M5 真实写入。发送身份默认使用 tenant，也就是机器人向测试群发风险卡。发送后，系统会记录 risk notification 和幂等信息，避免同一个风险在降噪窗口内重复提醒。
```

### 镜头 15：Jobs、报告和审计收尾

屏幕：

```text
Jobs / Health 页面
Dashboard 页面
storage/reports 路径或前端结果面板
```

操作：

```text
刷新 Jobs / Health
确认没有 failed / dead_letter
展示 M3/M4/M5 report path
展示 latest evaluation score
```

解说词：

```text
最后回到 Jobs / Health 和 Dashboard 做收尾检查。这里能看到后台 job 是否失败、migration 是否正常、评测分数是否达标，以及每次真实联调产生的报告路径。这样一次演示不是只看飞书群里有没有消息，而是能从前端、队列、SQLite 和报告四个角度确认链路可追踪。
```

### 镜头 16：总结

屏幕：

```text
飞书群展示 M3/M4/M5 卡片，旁边是 Console Dashboard
```

解说词：

```text
这次演示完整跑通了 MeetFlow 的真实飞书群闭环：会前准备、会后总结、人工确认任务、风险巡检提醒，以及后台服务、队列和报告检查。它体现的是一个垂直业务 Agent 的工程化能力：LLM 负责理解和生成，但所有真实副作用都经过工具注册、策略校验、飞书客户端封装和可审计的运行记录。
```

## G. 成片建议结构

如果时间有限，按这个剪辑：

```text
00:00 - 00:40 项目定位
00:40 - 01:30 启动 Console API / 前端
01:30 - 02:20 Dashboard / Jobs 健康检查
02:20 - 03:00 真实联调页启动 Worker / 回调服务
03:00 - 04:30 M3 dry-run + 真实发卡
04:30 - 06:30 M4 妙记解析 + 真实发卡
06:30 - 08:00 群内确认任务 + 状态刷新
08:00 - 09:40 M5 dry-run + 真实风险卡
09:40 - 10:30 Jobs / 报告 / 总结
```

完整版可在每个阶段多停留 30 - 60 秒解释策略、安全和工程化设计。

## H. 录制失败兜底素材

真实飞书 API 可能因为网络、权限、token、事件订阅或飞书侧延迟失败。录制时准备这些兜底素材：

```text
1. 一次成功 M3 卡片截图
2. 一次成功 M4 总结卡和待确认任务卡截图
3. 一次成功任务确认后的 Task Mappings 截图
4. 一次成功 M5 风险卡截图
5. storage/reports/m3 或 m4 的报告路径
6. Jobs / Health 无 failed job 的截图
```

失败时不要伪造成成功，可以这样说：

```text
这里真实飞书接口返回了权限或网络错误。MeetFlow 的设计是把错误暴露出来，并保留 request_id/log_id、stdout 和 job 状态，方便继续排查。这个失败不会被吞掉，也不会被前端伪装成成功。
```

## I. 视频中重点强调的项目亮点

```text
1. 不是脚本集合，而是飞书会议场景下的垂直业务 Agent
2. 前端 Console 把多终端联调收敛成可操作页面
3. M3/M4/M5 形成会前、会后、风险巡检闭环
4. 写操作有 allow_write、二次确认、幂等和策略门禁
5. 群内按钮回调让用户确认任务，避免 LLM 直接写入
6. Worker、JobQueue、SQLite、reports 让链路可恢复和可排查
7. Agent 评测和 e2e replay 让智能度可回归
```

## J. 录制结束后的收尾动作

前端 `真实联调` 页面停止：

```text
Worker
SDK 回调 或 M4 按钮回调
```

终端停止：

```text
终端 1：Ctrl+C 停止 Console API
终端 2：Ctrl+C 停止 Vite
```

检查不要误提交敏感文件：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
git status --short
git check-ignore -v config/settings.local.json .venv-lark-oapi storage/reports storage/meetflow.sqlite storage/workflow_events.jsonl
```

---

## 0. 录制前安全提醒

录制时不要展示以下内容：

```text
真实 token
真实 secret
API key
OAuth access token / refresh token
config/settings.local.json
config/llm_providers.local.json
真实客户资料
真实内部群聊
真实业务数据库内容
```

涉及运行结果时，视频解说统一使用这些口径：

```text
预期看到
如果通过，会看到
这里可以解释为
这里代表链路已经进入下一步
如果失败，可以按右侧错误信息继续排查
```

不要说“这里一定成功”“线上已经稳定可用”这类绝对表达。

---

# 会议内容准备稿：大厂项目开发需求评审会

本章节是独立素材，可以单独复制出来，作为模拟会议录音、飞书妙记内容或 M4 会后总结输入来源。

## 3.1 会议基本信息

- 会议主题：智能客服工单系统需求评审与开发排期会
- 会议时长：约 8 分钟
- 参会人：
  - 王晨：产品经理，负责需求说明和验收标准
  - 陈浩：后端研发负责人，负责接口、数据模型、权限和任务拆分
  - 刘雨：前端研发负责人，负责控制台页面、交互和联调
  - 赵敏：测试负责人，负责测试用例、回归范围和验收风险
- 会议背景：
  公司准备上线一个内部智能客服工单系统，目标是把客户反馈、工单分派、处理进度、风险提醒、数据看板串起来。本次会议主要确认第一期需求边界、技术实现方案、接口联调方式和任务排期。

## 3.2 模拟会议对白

王晨：大家好，我们今天主要过一下智能客服工单系统第一期的需求边界和开发排期。先说明一下背景，现在客服反馈分散在表格、群消息和邮件里，处理状态不透明，负责人也经常靠人工问。第一期我们先做一个内部工单系统，把客户反馈、工单分派、处理进度、风险提醒和数据看板串起来。

陈浩：我先确认一下，第一期是不是不做完整的自动派单？之前文档里提到 AI 推荐负责人，我担心如果范围太大，后端规则和权限都要重新设计。

王晨：对，这个地方先别扩大范围。第一版不做复杂自动派单，只做规则辅助推荐。比如根据问题分类、历史处理人和优先级给一个推荐处理人，但最后还是由管理员或客服主管手动确认分派。

刘雨：那前端这边列表页要不要直接展示推荐处理人？还是只在详情页展示？

王晨：列表页可以先不展示，避免信息太多。详情页里展示推荐处理人和推荐原因就行。列表页重点是筛选和快速定位工单。

刘雨：我补充一下，工单列表页面的筛选区域不要太复杂。第一期我建议只放状态、优先级、负责人、创建时间这四个筛选项。搜索框如果要做，也只搜标题和客户反馈摘要，不做复杂全文检索。

陈浩：可以。后端列表查询接口也先按这几个条件支持。状态字段我建议固定枚举：open、processing、waiting_customer、resolved、closed。优先级可以是 low、medium、high、urgent。这里需要产品确认一下中文展示文案。

王晨：中文文案我来补充，周三前放到需求文档里。状态流转上，open 是新建，processing 是处理中，waiting_customer 是等客户回复，resolved 是已解决，closed 是关闭。这个先按你说的枚举来。

赵敏：我这边有个问题，状态流转有没有限制？比如 resolved 能不能直接回到 processing？如果没有限制，测试用例会比较多。

陈浩：第一期可以先收敛。open 可以进入 processing，processing 可以进入 waiting_customer 或 resolved，waiting_customer 可以回到 processing，resolved 可以 closed。如果 resolved 之后又发现问题，可以重新打开到 processing，但要记录操作日志。

刘雨：那详情页右侧需要有处理记录时间线，对吧？包括状态变更、分派、评论、附件上传这些。

王晨：对。详情页左侧展示客户原始反馈、AI 摘要、附件和当前处理信息，右侧是处理记录时间线。AI 摘要第一期可以先由后端返回字段，前端不关心摘要生成细节。

陈浩：数据库这块我先说一下。第一期至少需要 ticket 表、ticket_assignee 表、ticket_comment 表。ticket 表放工单主信息，比如 title、raw_feedback、ai_summary、status、priority、creator_id、created_at、updated_at、first_response_at、resolved_at。ticket_assignee 表记录当前负责人和历史分派，ticket_comment 表记录处理评论和附件引用。

赵敏：附件是单独表吗？还是先放在评论里？

陈浩：第一期先别扩大范围。附件可以先作为 comment 的 attachment_json 字段，存附件 ID、文件名和 URL。后面如果要做附件管理，再拆 ticket_attachment 表。

刘雨：字段命名我们得提前对齐。比如前端习惯 assigneeName，后端如果返回 assignee_name，我们这边要做转换。为了减少联调时间，建议接口文档里直接写 JSON 字段，前端按接口来。

陈浩：没问题。我周四前完成数据库表设计和接口草案，里面会写清楚字段名。接口包括列表查询接口、详情接口、分派接口、评论接口和统计接口。

王晨：统计接口是给管理员看板用的。管理员看板第一版只做 3 个核心指标：今日新增工单数、平均首次响应时间、超时未处理数量。其他比如解决率、满意度、趋势图先不做。

刘雨：这个我们第一期先收敛是对的。看板页面我会做成三个指标卡片，下面最多加一个最近超时工单列表。移动端适配第一期先不做，后续再排。

赵敏：这里我记一个风险，管理员看板的指标口径如果不提前确认，上线前很容易出现产品、研发、测试理解不一致。比如平均首次响应时间，是从工单创建到第一条处理评论，还是到第一次状态变成 processing？

王晨：这个风险要记一下。我的倾向是从工单创建到第一条内部处理评论，或者第一次分派成功，两者取更早时间。这个我下周三前确认管理员看板指标口径。

陈浩：我觉得取更早时间会有点复杂，但可以做。先在接口草案里标注待确认。统计接口第一版可以支持 today_new_count、avg_first_response_minutes、timeout_open_count。

刘雨：前端需要加空状态、加载态、错误态。比如列表没数据时提示“暂无符合条件的工单”，接口报错时提示“加载失败，请稍后重试”。错误态文案我们需要产品再确认一下。

王晨：错误态文案我可以给一个初版，但不一定今天定下来。这个作为待确认事项吧。

赵敏：我补充一下测试策略。测试需要覆盖筛选组合，至少状态、优先级、负责人、创建时间两两组合。权限边界也要测，普通处理人只能看自己负责的工单，管理员可以看全部。重复提交也要测，比如重复分派、重复评论、刷新页面重复点击提交。

陈浩：接口幂等这里后端要做。分派接口可以要求传 request_id 或 idempotency_key，重复分派同一个人时返回当前结果，不重复写历史。评论接口也要考虑重复提交，前端可以禁用按钮，但后端不能完全依赖前端。

刘雨：前端会在提交中禁用按钮，加 loading 状态。但是网络抖动或者用户刷新，这个还是要后端兜住。

王晨：权限这块再明确一下。普通处理人只能看自己负责的工单，管理员可以看全部。客服主管能不能看团队成员的？

陈浩：如果有团队层级，权限模型会复杂。第一期建议只有普通处理人和管理员两个角色。客服主管如果要看团队，先按管理员权限配置。

赵敏：这个地方我有个疑问，如果普通处理人被重新分派后，还能不能看之前处理过的工单？

王晨：第一期先允许看自己参与过的历史工单，但列表默认只展示当前负责的。这个需要接口支持吗？

陈浩：需要。列表接口可以有 view_scope 参数，默认 current_assigned，另一个是 participated。但普通处理人不能传 all，只有管理员可以。

刘雨：那前端列表要不要放这个切换？

王晨：第一期先不放。避免范围膨胀。这个能力后端可以预留，但前端不展示。

赵敏：测试这边要准备 20 条模拟工单数据，覆盖不同状态、优先级、负责人和创建时间。这个我周五前整理第一版测试用例，同时准备数据清单。

陈浩：数据清单你给我后，我可以顺手写一个 seed 脚本，但这个不一定放到第一期主线里。

王晨：seed 脚本可以作为开发辅助，不作为产品需求。任务上我先梳理一下：我周三前补充需求文档里的验收标准；陈浩周四前完成数据库表设计和接口草案；刘雨周五前完成工单列表和详情页静态页面；赵敏周五前整理第一版测试用例。

刘雨：我这边静态页面包括列表、详情和看板吗？

王晨：看板可以先出结构，核心是列表和详情。看板三个指标卡片下周再联调也可以。

刘雨：那我周五前完成工单列表和详情页静态页面，下周二前完成前后端联调。看板我会先留页面骨架，等统计接口出来再接。

陈浩：后端这边我下周一前完成分派接口和评论接口。列表和详情接口尽量周五前先给 mock 或联调环境，避免前端等太久。

赵敏：我下周三前完成回归测试，但前提是下周二联调不要太晚。如果周二晚上才稳定，我这边时间会很紧。

刘雨：我们可以周一先联列表和详情，周二联分派和评论。这样测试周二下午就能开始看主流程。

王晨：可以。上线前需要做一次完整回归，这个不要省。尤其是权限边界、重复提交和超时提醒。

陈浩：超时提醒先用定时任务扫描，不引入复杂消息队列。扫描频率现在还没定，我建议先每 10 分钟扫一次 open 和 processing 状态，超过 SLA 就写提醒记录。

赵敏：这个规则要再明确。什么叫超时？不同优先级是不是不同 SLA？如果规则不清，可能误报或漏报。

王晨：这个我今天没法完全定。先按高优先级 2 小时、普通 8 小时作为临时方案。超时提醒的扫描频率和 SLA 规则我们单独确认，负责人先放后端和产品一起看。

陈浩：我这边可以先做成配置项，默认 10 分钟扫描一次。具体 SLA 值从配置读。这个任务负责人和截止时间先模糊处理，等王晨确认规则后我再落。

刘雨：超时提醒在前端怎么展示？列表上加红色标签，还是详情页提示？

王晨：列表上加一个超时标签，详情页顶部也提示。第一期不要做弹窗。

赵敏：风险点我再补几个：需求范围膨胀、前后端字段命名不一致导致联调延迟、权限边界不清导致数据泄露、超时提醒规则不清导致误报或漏报、测试数据不足导致上线前问题暴露不充分、重复提交导致脏数据、看板指标口径不一致。这些都要进风险清单。

陈浩：重复提交我会在接口层做幂等。权限这块我会在接口里统一校验，不让前端自己控制。普通处理人查 all 直接返回无权限。

刘雨：前端也会根据角色隐藏部分入口，但我同意不能只靠前端。

王晨：验收标准我会写清楚。第一期验收包括：列表筛选可用，详情信息完整，支持分派和评论，普通处理人不能看不属于自己的工单，管理员看板三个指标可展示，超时提醒能在测试数据里触发。

赵敏：还有重复提交。验收里也要加，比如重复点击分派不会产生两条历史记录，重复评论不会生成两条相同评论。

王晨：对，这个加进去。

陈浩：接口草案我周四前给出来后，周四下午可以拉一个 30 分钟接口评审。刘雨你看可以吗？

刘雨：可以。字段命名最好周四就定，不然后面联调会拖。

赵敏：我也参加一下接口评审，这样测试用例能同步更新。

王晨：好，那今天结论先到这里。最后确认一下待办：王晨周三前补需求验收标准，下周三前确认看板指标口径；陈浩周四前完成表设计和接口草案，下周一前完成分派和评论接口；刘雨周五前完成列表和详情静态页面，下周二前完成前后端联调；赵敏周五前整理测试用例，下周三前完成回归测试。超时提醒扫描频率、错误态文案、SLA 规则作为待确认事项。大家还有补充吗？

刘雨：没有，我这边会先按四个筛选项做，移动端先不做。

陈浩：我这边会先把权限和幂等放进接口设计，不等后面再补。

赵敏：我这边会准备 20 条模拟工单数据，重点覆盖状态、权限、重复提交和超时提醒。
月
王晨：好，那会议结束。我会把结论同步到需求文档里。

## 3.3 会议摘要

- 第一版智能客服工单系统先收敛范围，不做复杂自动派单，只做规则辅助推荐。
- 工单列表支持按状态、优先级、负责人、创建时间筛选，暂不做复杂移动端适配。
- 工单详情页展示客户原始反馈、AI 摘要、处理记录、附件和右侧处理时间线。
- 后端需要设计 `ticket`、`ticket_assignee`、`ticket_comment` 三张核心表。
- 接口范围包括列表查询、详情、分派、评论和管理员统计接口。
- 权限第一期只区分普通处理人和管理员，普通处理人只能看自己当前负责或参与过的工单。
- 超时提醒先用定时任务扫描，不引入复杂消息队列。
- 上线前必须完成筛选组合、权限边界、重复提交、超时提醒和完整回归测试。

## 3.4 待办事项表

| 编号 | 任务 | 负责人 | 截止时间 | 优先级 | 是否明确 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 补充需求文档里的验收标准 | 王晨 | 周三前 | 高 | 是 | 包含列表、详情、分派、评论、权限、看板和重复提交 |
| 2 | 完成数据库表设计和接口草案 | 陈浩 | 周四前 | 高 | 是 | 覆盖 ticket、ticket_assignee、ticket_comment |
| 3 | 完成工单列表和详情页静态页面 | 刘雨 | 周五前 | 高 | 是 | 看板先留页面骨架 |
| 4 | 整理第一版测试用例 | 赵敏 | 周五前 | 高 | 是 | 覆盖筛选、权限、重复提交、超时提醒 |
| 5 | 完成分派接口和评论接口 | 陈浩 | 下周一前 | 高 | 是 | 需要支持幂等 |
| 6 | 完成前后端联调 | 刘雨 | 下周二前 | 高 | 是 | 周一先联列表和详情，周二联分派和评论 |
| 7 | 完成完整回归测试 | 赵敏 | 下周三前 | 高 | 是 | 依赖联调稳定 |
| 8 | 确认管理员看板指标口径 | 王晨 | 下周三前 | 中 | 是 | 今日新增、平均首次响应、超时未处理 |
| 9 | 确认超时提醒扫描频率和 SLA 规则 | 王晨 / 陈浩 | 待确认 | 高 | 否 | 当前临时方案为 10 分钟扫描一次 |
| 10 | 确认前端错误态文案 | 王晨 / 刘雨 | 待确认 | 中 | 否 | 需要产品确认最终文案 |

## 3.5 风险点表

| 编号 | 风险点 | 影响 | 可能原因 | 建议处理方式 | 负责人 | 是否需要 M5 风险巡检 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 需求范围膨胀 | 延误第一期上线 | 自动派单、移动端、复杂看板不断加入 | 第一版只保留规则辅助推荐和 3 个指标 | 王晨 | 是 |
| 2 | 前后端字段命名不一致 | 联调延迟 | 接口文档字段不明确 | 周四接口评审提前确认 JSON 字段 | 陈浩 / 刘雨 | 是 |
| 3 | 权限边界不清 | 数据泄露风险 | 普通处理人和管理员权限没有统一校验 | 后端接口统一校验权限，前端只做辅助隐藏 | 陈浩 | 是 |
| 4 | 超时提醒规则不清 | 误报或漏报 | SLA 和扫描频率未确认 | 将 SLA 做成配置项，产品确认规则 | 王晨 / 陈浩 | 是 |
| 5 | 测试数据不足 | 上线前问题暴露不充分 | 状态、权限、重复提交数据覆盖不足 | 准备 20 条模拟工单数据 | 赵敏 | 是 |
| 6 | 重复提交导致脏数据 | 分派历史或评论重复 | 网络抖动、用户重复点击、刷新重试 | 前端禁用按钮，后端使用幂等键 | 陈浩 / 刘雨 | 是 |
| 7 | 管理员看板指标口径不一致 | 验收争议 | 首次响应时间定义不一致 | 下周三前确认统计口径并写入需求文档 | 王晨 | 是 |

## 3.6 模糊待确认事项表

| 编号 | 待确认事项 | 缺失信息 | 建议追问 | 建议负责人 |
| --- | --- | --- | --- | --- |
| 1 | 超时提醒扫描频率和 SLA 规则 | 不同优先级的 SLA、扫描频率、提醒对象 | 高优先级和普通工单分别多久算超时？提醒发给谁？ | 王晨 / 陈浩 |
| 2 | 前端错误态文案 | 不同错误场景的提示文案 | 列表加载失败、分派失败、评论失败分别提示什么？ | 王晨 / 刘雨 |
| 3 | 普通处理人的历史工单可见范围 | 参与过、当前负责、曾经负责的边界 | 被重新分派后是否还能看之前处理过的工单？ | 王晨 / 陈浩 |
| 4 | 管理员看板平均首次响应时间口径 | 起止时间定义 | 从创建到第一条评论，还是到首次分派或状态变化？ | 王晨 |

## 3.7 适合 M4 展示的摘要

本次会议确认了智能客服工单系统第一期范围：先完成工单列表、详情、分派、评论、超时提醒和管理员看板基础能力，不做复杂自动派单和移动端适配。后端将设计 `ticket`、`ticket_assignee`、`ticket_comment` 三张核心表，并提供列表、详情、分派、评论和统计接口。前端优先完成列表和详情页，补齐空状态、加载态和错误态。测试需要覆盖筛选组合、权限边界、重复提交和超时提醒。主要风险包括需求范围膨胀、字段命名不一致、权限边界不清、超时规则不明确和测试数据不足。

---

# 4. MeetFlow 项目整体功能介绍

## 4.1 项目一句话介绍

MeetFlow 是一个面向飞书会议场景的智能会议工作流系统，围绕会前准备、会后总结、待办确认、风险巡检、Agent 评测和真实飞书群联调构建完整闭环。

视频里可以这样开场：

```text
大家好，今天演示的是 MeetFlow。它不是一个简单的会议总结脚本，而是一个接入真实飞书日历、妙记、群卡片、按钮回调和后台队列的会议工作流 Agent。我们会从一段模拟会议内容开始，展示它如何生成会后总结、待确认任务、风险巡检提醒，并通过 Agent 评测证明链路是可回归、可验证的。
```

## 4.2 整体流程

```text
会议内容 / 妙记链接
  -> M4 会后总结
  -> 待确认任务卡
  -> 飞书群按钮交互
  -> SDK 回调服务
  -> workflow 队列
  -> Worker 消费
  -> 任务落库 / 状态更新
  -> M5 风险巡检
  -> 风险卡片提醒
```

也可以补充会前流程：

```text
飞书日程
  -> M3 会前触发
  -> 项目知识检索
  -> 会前背景卡
  -> 飞书群提醒参会人
```

## 4.3 核心模块介绍

### M3 会前卡片

- 模块作用：读取飞书日程和相关资料，生成会前背景卡，帮助参会人提前了解会议目标、背景、风险和建议关注点。
- 视频里怎么演示：在前端 M3 页面或终端执行 M3 发卡命令。
- 成功现象：如果通过，会在飞书测试群看到会前背景卡；终端或前端会显示 trace_id 和报告路径。
- 失败时如何解释：如果提示没有可用会议，说明 `--date` 对应时间窗口内没有匹配标题的飞书日程，需要改成 `today`、绝对日期或使用 event_id。

### M4 会后总结

- 模块作用：基于妙记或会议内容生成会后总结，提取关键结论、待办事项和风险点。
- 视频里怎么演示：使用模拟妙记链接或会议内容运行 M4 只读验证，再真实发卡到飞书群。
- 成功现象：飞书群出现会后总结卡，内容包含会议摘要、待办事项和风险提示。
- 失败时如何解释：如果妙记读取失败，优先解释为 OAuth 权限、妙记链接访问权限或网络问题。

### M4 待确认任务

- 模块作用：把会议中的待办事项转成待确认任务卡，不直接盲目创建任务。
- 视频里怎么演示：在飞书群展示待确认任务卡，点击确认创建、保存修改或拒绝创建。
- 成功现象：如果通过，会看到按钮响应、任务确认状态变化，后端收到回调并进入 workflow 队列。
- 失败时如何解释：如果按钮无响应，说明 SDK 回调服务未启动、机器人权限未生效或回调事件未到达。

### M5 风险巡检

- 模块作用：持续检查会议后任务风险，例如延期、无人跟进、规则不清和重复提交风险。
- 视频里怎么演示：运行风险巡检脚本，展示飞书群风险卡片。
- 成功现象：如果通过，会看到风险巡检卡片，卡片中包含风险类型、影响和建议处理方式。
- 失败时如何解释：如果没有风险卡片，可以解释为当前测试数据没有触发风险，或降噪窗口避免重复提醒。

### 飞书 SDK 回调服务

- 模块作用：接收飞书卡片按钮和事件回调，把用户操作转成后端可处理的事件。
- 视频里怎么演示：启动 SDK 回调服务，点击飞书群卡片按钮，观察终端日志。
- 成功现象：如果通过，终端会显示回调日志，workflow_jobs 中会出现新任务。
- 失败时如何解释：优先检查 SDK 隔离虚拟环境、飞书应用权限、事件订阅和机器人是否进群。

### Worker / Job Queue

- 模块作用：异步消费 workflow、risk_scan、rag_refresh 等后台任务，提升链路稳定性和可恢复性。
- 视频里怎么演示：启动 worker，然后查询 SQLite 中的 `workflow_jobs`。
- 成功现象：如果通过，会看到任务从 pending/running 变成 succeeded，或在 dry-run 模式下看到任务可被领取。
- 失败时如何解释：如果任务没有被消费，检查 worker 监听队列是否包含对应 queue_name。

### SQLite 持久化

- 模块作用：保存任务队列、会话状态、审计记录、风险提醒和本地运行状态。
- 视频里怎么演示：用 sqlite3 查询 workflow_jobs、assistant_sessions、risk_notifications。
- 成功现象：如果通过，会看到最近的 job、session 或风险提醒记录。
- 失败时如何解释：如果表不存在，先运行 migration verify；如果无记录，说明还没有触发对应流程。

### AgentPolicy

- 模块作用：保护真实写操作，要求关键字段、权限、置信度和幂等键满足条件后才允许执行。
- 视频里怎么演示：讲解待确认任务卡为什么不是直接创建任务，展示 Agent 评测中的 policy_compliance。
- 成功现象：如果通过，写操作会留下 Policy 轨迹，缺字段时进入 needs_confirmation。
- 失败时如何解释：如果写操作被阻止，这是安全策略生效，不是系统失败。

### Agent 轨迹评测

- 模块作用：量化 Agent 是否按正确顺序调用工具、是否先读后写、是否经过 Policy、是否包含幂等键。
- 视频里怎么演示：运行 `scripts/agent_eval_suite.py`。
- 成功现象：如果通过，会看到 score 达到门槛，safety_score 为 1.0。
- 失败时如何解释：如果某个 case 失败，说明当前 Agent 行为偏离预期，需要根据 metrics 定位工具调用、顺序或 Policy 问题。

### 前端控制台 / UI 测试文档

- 模块作用：提供本地工作台，展示 Dashboard、M3、Agent 评测和 Jobs/Health。
- 视频里怎么演示：打开 `http://127.0.0.1:5173`，依次展示各页面。
- 成功现象：如果通过，前端能加载健康状态、评测结果和任务列表。
- 失败时如何解释：如果前端数据加载失败，通常是 Console API 没有启动或 `/api` 代理目标不可用。

### 真实飞书群联调

- 模块作用：证明系统不只是在本地 mock，而是能真实进入飞书群、卡片按钮、回调、队列和任务处理链路。
- 视频里怎么演示：在测试群发送 M3/M4/M5 卡片，并点击按钮触发回调。
- 成功现象：如果通过，飞书群有卡片，终端有回调日志，SQLite 有任务记录。
- 失败时如何解释：真实联调依赖 OAuth、机器人权限、群配置、事件订阅和网络状态，需要按测试命令文档逐项排查。

---

# 5. 视频录制整体流程

```text
阶段 1：开场介绍，约 1 分钟
阶段 2：会议内容准备说明，约 1 分钟
阶段 3：本地质量检查，约 3 分钟
阶段 4：启动 Worker 和回调服务，约 2 分钟
阶段 5：M4 真实飞书群发卡，约 3 分钟
阶段 6：飞书群按钮交互与回调消费，约 3 分钟
阶段 7：M5 风险巡检，约 2 分钟
阶段 8：Agent 评测与总结，约 2 分钟
阶段 9：前端控制台说明，约 2 分钟
阶段 10：收尾总结，约 1 分钟
```

建议视频总时长控制在 15-22 分钟。录制时可以把耗时较长的测试命令提前跑好，视频中只展示关键命令、关键输出和解释。

---

# 6. 阶段 1：开场介绍，约 1 分钟

## 演示目的

说明项目定位和视频目标，让观众知道这不是单点 API 调用，而是完整会议工作流闭环。

## 解说词

```text
大家好，今天演示的是 MeetFlow，一个面向飞书会议场景的智能会议工作流系统。

它围绕会议前、会议后和会议后的持续跟踪来设计：会前可以生成背景卡，会后可以总结会议并提取待办，待办需要经过用户确认，后续还可以通过风险巡检提醒任务风险。

这次演示重点不是只证明某个脚本能跑，而是展示 MeetFlow 能完成真实飞书群联调，并且具备 worker 队列、SDK 回调、SQLite 持久化和 Agent 轨迹评测这些工程化能力。
```

## 屏幕展示

建议展示：

```text
项目 README
docs/overall-test-commands.md
前端控制台 Dashboard
```

---

# 7. 阶段 2：会议内容准备说明，约 1 分钟

## 演示目的

告诉观众 M4 演示的会议内容来自哪里，以及为什么这段内容适合做会后总结、待办提取和风险巡检。

## 解说词

```text
为了让演示更贴近真实业务，我准备了一段模拟会议内容：智能客服工单系统需求评审与开发排期会。

这段会议不是 MeetFlow 项目本身，而是一个典型的大厂项目推进会，里面包含需求澄清、前后端接口讨论、数据库字段、权限控制、排期、测试策略和风险同步。

它适合用来演示 M4 会后总结、待确认任务和 M5 风险巡检，因为里面既有明确负责人和截止时间，也有一些模糊事项，需要系统识别后进入待确认。
```

## 录制动作

打开本文档的“会议内容准备稿”章节，快速展示：

```text
会议摘要
待办事项表
风险点表
模糊待确认事项表
```

---

# 8. 阶段 3：本地质量检查，约 3 分钟

## 演示目的

证明项目不是只靠临时脚本，而是有固定质量闸口。

## 解说词

```text
在做真实飞书群联调之前，我先跑本地质量检查。这里主要检查 Python 编译、核心单测、Agent 轨迹评测和迁移状态。

这些命令都记录在 docs/overall-test-commands.md 中，后续每次新增脚本、回调、队列、评测 case 或真实联调路径，都需要同步更新这个测试命令总表。
```

## 终端命令

进入项目：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
```

编译检查：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py
```

核心单测：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests
```

Agent 轨迹评测：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95
```

SQLite migration 检查：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify
```

## 预期看到

```text
如果通过，会看到 py_compile 无输出或无错误。
如果通过，会看到 unittest OK。
如果通过，Agent 评测 score 达到 0.95 门槛，safety_score 为 1.0。
如果 migration 正常，会看到 verify 通过。
```

## 异常话术

```text
如果这里失败，我不会继续做真实飞书写入。因为真实联调前必须保证本地质量闸口通过。
失败时我会根据具体输出定位是编译、单测、评测还是 migration 问题。
```

---

# 9. 阶段 4：启动 Worker 和回调服务，约 2 分钟

## 演示目的

证明系统支持真实异步链路：飞书按钮回调不是直接改数据，而是进入 SDK 回调服务、workflow 队列，再由 worker 消费。

## 终端 1：Worker

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues workflow,risk_scan,rag_refresh \
  --poll-seconds 2
```

## 终端 2：SDK 回调服务

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main

/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py \
  --enqueue-agent \
  --agent-provider dry-run \
  --job-queue workflow \
  --log-level info
```

## 解说词

```text
现在我启动两个长期服务。

第一个是 worker，用来消费 workflow、risk_scan 和 rag_refresh 队列。

第二个是飞书 SDK 回调服务，用来接收飞书卡片按钮和事件回调。这里使用 .venv-lark-oapi 隔离环境，是为了避免 lark-oapi 和主业务 Python 环境发生依赖冲突。

这两个服务启动后，飞书群里的按钮操作就可以进入后端队列，而不是只停留在前端卡片上。
```

## 预期看到

```text
Worker 终端会保持运行，等待队列任务。
SDK 回调终端会保持运行，等待飞书事件。
如果点击飞书群卡片按钮，预期在 SDK 终端看到回调日志。
```

## 异常话术

```text
如果 SDK 服务启动失败，优先检查 .venv-lark-oapi 是否存在，以及 lark_oapi 是否能正常 import。
如果 worker 没有消费任务，优先检查任务是否进入了正确队列，以及 worker 的 --queues 是否包含这个队列。
```

---

# 10. 阶段 5：M4 真实飞书群发卡，约 3 分钟

## 演示目的

展示 MeetFlow 能把会议内容转成飞书群中的会后总结卡和待确认任务卡。

## 前置准备

准备一个飞书妙记链接，或使用前文“会议内容准备稿”制作一段模拟会议内容。录制时不要展示真实敏感会议。

## 只读验证命令

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "替换为你的飞书妙记链接" \
  --read-only \
  --show-card-json \
  --content-limit 800
```

## 真实发卡命令

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "替换为你的飞书妙记链接" \
  --show-card-json
```

如果没有默认群，使用：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "替换为你的飞书妙记链接" \
  --chat-id oc_xxx \
  --show-card-json
```

## 解说词

```text
现在进入 M4 会后总结演示。

这一步会读取会议内容，提取会议摘要、待办事项和风险点，并生成飞书群卡片。

这里比较关键的是，MeetFlow 不会盲目把所有待办直接写入任务系统。对于负责人、截止时间或置信度不完整的事项，会进入待确认任务卡，让用户在飞书群里确认、修改或拒绝。
```

## 飞书群展示动作

录制飞书测试群中出现的：

```text
会后总结卡
待确认任务卡
任务负责人 / 截止时间 / 摘要
确认创建 / 保存修改 / 拒绝创建按钮
```

## 预期看到

```text
如果通过，飞书测试群会收到 M4 会后总结卡。
如果生成了待确认任务，会看到待确认任务卡和按钮。
终端中预期看到卡片 JSON、trace_id 或发送结果摘要。
```

## 异常话术

```text
如果妙记读取失败，通常需要检查 OAuth 授权、妙记链接权限和当前用户身份。
如果卡片没有发到群里，需要检查默认群 chat_id、机器人是否进群、应用权限是否发布生效。
```

---

# 11. 阶段 6：飞书群按钮交互与回调消费，约 3 分钟

## 演示目的

展示从飞书群按钮到 SDK 回调、workflow 队列、worker 消费的完整闭环。

## 飞书群操作

在待确认任务卡上依次演示：

```text
确认创建
保存修改
拒绝创建
```

建议录制时重点演示一个按钮，不必每个按钮都完整跑一遍。

## 查看队列命令

```bash
sqlite3 storage/meetflow.sqlite \
  "SELECT job_id,queue_name,job_type,status,attempts,last_error,created_at,updated_at FROM workflow_jobs ORDER BY created_at DESC LIMIT 10;"
```

## 回归测试命令

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_card_actions \
  tests.test_post_meeting_card_callback
```

## 解说词

```text
现在我点击飞书群里的任务确认按钮。

这个按钮不是简单的前端交互，它会进入飞书 SDK 回调服务。回调服务会识别按钮动作，把它转成后端事件，再进入 workflow 队列，由 worker 统一消费。

这样设计的好处是：真实写操作不会绕过 AgentPolicy，也不会因为飞书回调抖动导致不可追踪。每一步都有日志、队列状态和审计记录。
```

## 预期看到

```text
如果通过，SDK 回调终端会出现按钮事件日志。
如果通过，SQLite workflow_jobs 中会看到相关任务。
如果 worker 正常消费，任务状态会从 pending/running 变为 succeeded，或在 dry-run 下看到可消费记录。
```

## 异常话术

```text
如果按钮没有触发回调，我会先检查 SDK 回调服务是否运行。
如果回调到了但 worker 没消费，我会检查 job queue 名称和 worker --queues 配置。
如果写操作被阻止，这不一定是失败，可能是 AgentPolicy 发现缺少负责人、截止时间或幂等键。
```

---

# 12. 阶段 7：M5 风险巡检，约 2 分钟

## 演示目的

展示 MeetFlow 不止做一次性总结，还能持续发现会后任务风险，并在飞书群提醒。

## 真实风险巡检命令

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py \
  --backend feishu \
  --show-card \
  --allow-write \
  --identity user \
  --send-identity tenant
```

## 入队模式命令

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py \
  --backend feishu \
  --show-card \
  --allow-write \
  --identity user \
  --send-identity tenant \
  --enqueue
```

## 手动消费一次

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues risk_scan \
  --once
```

## 解说词

```text
现在演示 M5 风险巡检。

M5 的价值在于，它不是会议结束后就停止，而是持续检查任务是否存在延期、无人跟进、规则不清或重复提交这类风险。

比如刚才会议里提到的超时提醒规则不清、字段命名不一致、权限边界不清，这些都可以作为后续风险巡检的对象。
```

## 预期看到

```text
如果通过，飞书群会收到风险巡检卡片。
卡片里预期包含风险类型、影响、建议处理方式和相关负责人。
如果没有新卡片，也可以解释为当前降噪窗口避免重复提醒，或当前数据没有触发风险。
```

## 异常话术

```text
如果风险巡检没有发卡，我会先确认是否真的有可触发的风险数据。
如果之前已经提醒过，系统可能处于降噪窗口中，这是为了避免重复刷屏。
```

---

# 13. 阶段 8：Agent 评测与总结，约 2 分钟

## 演示目的

展示 MeetFlow 的 Agent 行为不是黑盒，而是可以通过轨迹评测量化。

## 命令

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

单 case 验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --case-id m3_evidence_first_plan \
  --provider scripted_debug \
  --fail-under 0.95
```

## 解说词

```text
这里是 MeetFlow 的工程化创新点。

我不仅让 Agent 能调用工具，还设计了轨迹评测系统，检查它是否按正确顺序调用工具，是否先读后写，是否经过 AgentPolicy，是否带幂等键，以及评测报告中是否没有泄露敏感信息。

也就是说，这个项目不是只能靠人工看演示结果，而是可以把 Agent 行为变成可回归、可量化的质量门禁。
```

## 预期看到

```text
如果通过，会看到 score 达到 0.95 门槛。
如果通过，safety_score 应为 1.0。
如果写入报告，会在 storage/reports/evaluation 下生成评测报告。
```

## 异常话术

```text
如果某个 case 失败，我会根据 metrics 判断是工具调用不对、顺序不对、Policy 轨迹缺失，还是幂等键覆盖不足。
这个失败不是坏事，它说明 Agent 评测系统能够捕捉行为回归。
```

---

# 14. 阶段 9：前端控制台说明，约 2 分钟

## 演示目的

展示 MeetFlow 不只是命令行脚本，也有本地控制台用于展示系统状态、M3 发卡、评测和 Jobs/Health。

## 终端 1：启动 Console API

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787
```

## 终端 2：启动前端

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main/frontend

npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

## 浏览器地址

```text
http://127.0.0.1:5173
```

## 解说词

```text
最后看一下前端控制台。

这个控制台用于本地演示和排查，包括 Dashboard、M3 会前卡片、Agent 评测中心和 Jobs / Health。

它不是营销页，而是面向真实操作的工作台。前端请求 /api，由 Vite 代理到本地 Console API，所以启动前端时需要同时启动 8787 端口的后端服务。
```

## 展示顺序

```text
Dashboard：看系统状态、评测分数、最近任务
M3 会前：展示 dry-run 和真实发卡二次确认
Agent 评测：展示 score、safety、case 结果
Jobs / Health：展示 migration、workflow_jobs、worker dry-run
docs/overall-test-commands.md：展示所有测试入口和终端分工
```

## 预期看到

```text
如果通过，Dashboard 能正常加载系统状态。
如果后端没有启动，前端会出现数据加载失败，这时需要启动 Console API。
```

---

# 15. 阶段 10：收尾总结，约 1 分钟

## 解说词

```text
这次演示展示了 MeetFlow 的完整闭环：从会议内容输入，到会后总结、待确认任务、飞书群按钮交互、SDK 回调、worker 队列消费，再到 M5 风险巡检和 Agent 轨迹评测。

MeetFlow 的核心价值不是单点生成摘要，而是把会议知识、任务推进和风险追踪放进一个可验证、可回放、可持续迭代的 Agent 工作流里。

从工程实现上，它保留了 AgentPolicy、ToolRegistry、SQLite 持久化、worker/job queue、SDK 隔离环境和前端控制台。真实写操作不会绕过安全策略，Agent 行为也可以通过评测系统持续回归。

这就是 MeetFlow 当前版本的完整能力展示。
```

---

# 16. 飞书群真实测试步骤清单

## 16.1 创建飞书测试群

```text
群名建议：MeetFlow 演示测试群
确认机器人已进群
确认不会影响真实业务同事
```

## 16.2 确认 OAuth

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/oauth_device_login.py
```

## 16.3 验证日历读取

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/calendar_live_test.py \
  --identity user \
  --calendar-id primary \
  --debug-calendar
```

## 16.4 验证妙记读取

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/minutes_live_test.py \
  --minute "替换为你的飞书妙记链接"
```

## 16.5 M3 会前卡片测试

飞书里先创建测试日程：

```text
标题：MeetFlow 测试会议
时间：今天或明天 10:00 - 10:30
参与人：添加你自己
描述：这是 MeetFlow M3 会前卡片测试会议
```

Dry-run：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-check" \
  --write-report \
  --dry-run
```

真实发卡：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-$(date +%Y%m%d%H%M%S)" \
  --write-report
```

如果会议在明天，把 `--date today` 改为：

```bash
--date tomorrow
```

## 16.6 M4 会后总结测试

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "替换为你的飞书妙记链接" \
  --show-card-json
```

如果没有默认群：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "替换为你的飞书妙记链接" \
  --chat-id oc_xxx \
  --show-card-json
```

## 16.7 M5 风险巡检测试

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py \
  --backend feishu \
  --show-card \
  --allow-write \
  --identity user \
  --send-identity tenant
```

---

# 17. 异常情况处理话术

## 17.1 npm 或 node 不存在

```text
这里是前端本地开发环境问题，不影响后端 Agent 主链路。
前端需要安装 Node.js 和 npm。安装完成后重新进入 frontend 目录，执行 npm install 和 npm run dev。
```

## 17.2 前端页面数据加载失败

```text
前端请求 /api 时会代理到 127.0.0.1:8787。
如果数据加载失败，优先检查 Console API 是否已经启动。
```

检查命令：

```bash
curl --noproxy '*' -sS http://127.0.0.1:8787/api/health
```

## 17.3 M3 找不到会议

```text
这通常不是代码问题，而是 --date 对应的时间窗口里没有标题匹配的飞书日程。
例如今天执行 --date tomorrow，查询的是明天本地整天。
可以改用 --date today、--date YYYY-MM-DD，或者传 event_id 精确定位。
```

## 17.4 SDK 回调服务启动失败

```text
飞书 SDK 使用隔离虚拟环境 .venv-lark-oapi。
如果启动失败，先检查隔离环境是否存在，lark_oapi 是否能 import。
```

检查命令：

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python -c "import lark_oapi; import scripts.feishu_event_sdk_server; print('sdk server import ok')"
```

## 17.5 飞书卡片没有发到群

```text
优先检查 chat_id、机器人是否进群、应用权限是否发布生效，以及当前命令是否真的开启了允许写入。
为了安全，MeetFlow 的真实写操作不会默认打开。
```

## 17.6 AgentPolicy 阻止写操作

```text
这不是系统故障，而是安全策略生效。
如果负责人、截止时间、置信度或幂等键不足，MeetFlow 会进入待确认流程，避免 Agent 盲目写入真实飞书数据。
```

## 17.7 Agent 评测失败

```text
评测失败说明某个 Agent 行为偏离预期。
下一步应该看 metrics，是 tool_call_f1、tool_order_score、policy_compliance、allow_write_gate 还是 idempotency_key_rate 出了问题。
```

## 17.8 Worker 没有消费任务

```text
先确认任务是否已经进入 workflow_jobs。
如果有任务但没消费，再检查 worker 的 --queues 是否包含对应队列。
```

查询命令：

```bash
sqlite3 storage/meetflow.sqlite \
  "SELECT job_id,queue_name,job_type,status,attempts,last_error FROM workflow_jobs ORDER BY created_at DESC LIMIT 20;"
```

---

# 18. 最终录制检查清单

```text
飞书测试群已准备
机器人已进群
OAuth 已授权
测试日程存在
妙记链接可访问
Console API 可启动
前端可打开
worker 可启动
SDK 回调服务可启动
M3 dry-run 通过
M4 read-only 通过
M5 dry-run 或真实测试通过
agent_eval_suite score >= 0.95
safety_score = 1.0
不会展示 token / secret / API key
```

建议先录一版 dry-run 版本确认流程，再录最终真实飞书群版本。
