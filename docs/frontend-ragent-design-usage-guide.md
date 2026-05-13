# MeetFlow Ragent 风格前端使用说明

本文档说明当前 MeetFlow Console 在参考 Ragent Admin / Trace 控制台风格改造后的使用方式、页面检查点和本地启动命令。此次改造只调整前端布局与视觉，不改变后端 API、飞书写入、安全策略或 CLI 链路。

## 1. 已落地的前端变化

| 模块 | 改造内容 | 影响范围 |
|---|---|---|
| 全局设计 token | 在 `frontend/src/styles/app.css` 新增 `--mf-*` 字体、颜色、圆角、阴影变量 | 所有页面 |
| 主布局 | `frontend/src/App.tsx` 改为深色渐变侧栏 + 浅灰工作区 + sticky topbar | Dashboard、M3、真实联调、评测、Jobs |
| 导航结构 | 左侧导航按“总览 / 核心流程 / 质量与运维”分组 | 入口更清晰 |
| 安全提示 | 顶部固定展示“默认 dry-run / 真实写入需二次确认” | 演示时持续提醒安全边界 |
| 控制台组件视觉 | 统一 card、panel、form、table、button、badge、dialog、JSON 结果区样式 | 不改变组件数据流 |
| 响应式布局 | 1120px 和 820px 断点下自动收敛网格、表单和导航 | 平板和窄屏可用 |

## 2. 本地启动方式

### 2.1 启动 Console API

前端所有 `/api/...` 请求通过 Vite proxy 指向 `http://127.0.0.1:8787`，所以需要先启动后端 Console API：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 scripts/meetflow_console_server.py --host 127.0.0.1 --port 8787
```

健康检查：

```bash
curl --noproxy '*' -sS http://127.0.0.1:8787/api/health
```

### 2.2 启动前端开发服务

当前仓库前端入口仍是 Vite：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan/frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开：

```text
http://127.0.0.1:5173
```

如果是第一次在机器上运行前端，先执行：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan/frontend
npm install
```

### 2.3 构建静态资源

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan/frontend
npm run build
```

构建成功后，也可以只启动 Console API，由 `scripts/meetflow_console_server.py` 服务 `frontend/dist`：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 scripts/meetflow_console_server.py --host 127.0.0.1 --port 8787 --static-dir frontend/dist
```

然后打开：

```text
http://127.0.0.1:8787
```

## 3. 页面检查清单

### Dashboard

- 左侧侧栏应为深色渐变，导航分组清晰。
- 顶部 topbar 应显示当前页面名和安全提示。
- KPI、FeatureCard、最近任务表应为白色卡片，边框和阴影轻量。
- 如果 Console API 未启动，应显示错误提示，不应出现页面崩溃。

### M3 会前

- 表单、真实写入确认、命令结果区应保持统一卡片样式。
- 前端 M3 入口固定包装 `python3 scripts/card_send_live.py m3`，不要改成其他会前脚本。
- `doc` 会透传为 `--doc`，`minute` 会透传为 `--minute`，两者会进入会前 RAG / Evidence Pack。
- `LLM Provider` 真实演示推荐 `settings`，它会使用 `config/settings.local.json` 中的 LLM 配置。
- 真实发卡仍需要用户主动勾选/确认 `allow_write`，前端视觉只增强，不放宽安全边界。

### 真实联调

- M4/M5 表单、服务控制、运行记录表保持双列或多列表达。
- 窄屏下应自动变成单列，不应横向撑破页面。
- 真实写入按钮保持红色 danger 语义。

### Agent 评测

- 评测表单和报告展示应保持控制台密度，不做营销式大 Hero。
- JSON / 命令输出区应使用深色 mono 面板，长文本可换行或滚动。

### Jobs / Health

- migration、worker dry-run、jobs 表格应集中展示。
- 表格在窄屏下可横向滚动。

## 4. 安全边界

本次前端改造不改变以下规则：

- 前端只调用 `core/console_api.py` 暴露的白名单 HTTP API。
- 前端不直接执行任意 shell 命令。
- 前端不直接调用 `FeishuClient.send_*` 或 `FeishuClient.create_*`。
- 前端不保存或展示 token、secret、refresh token、API key。
- 真实飞书写入必须显式确认，并优先使用测试群。
- 真实写入链路继续由后端脚本、AgentPolicy、幂等键和 Console API 约束。

## 5. 验证命令

Python 后端接口基础检查：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 -m py_compile scripts/meetflow_console_server.py core/console_api.py
python3 -m unittest tests.test_console_api
```

前端构建检查：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan/frontend
npm run build
```

如果当前环境没有 `node` / `npm`，需要先安装 Node.js 与 npm，或切换到已有前端工具链的环境再执行构建。

## 6. 排查指南

| 现象 | 可能原因 | 处理方式 |
|---|---|---|
| 页面打开但数据加载失败 | Console API 未启动 | 先运行 `python3 scripts/meetflow_console_server.py --host 127.0.0.1 --port 8787` |
| `npm run dev` 不存在或失败 | 当前机器未安装 npm / Node.js | 安装 Node.js/npm，或在已有工具链环境中运行 |
| 页面样式没有变化 | 仍在看旧的 `frontend/dist` | 使用 Vite dev server，或重新 `npm run build` |
| API 请求 404 | 不是通过 Vite proxy 或 Console API 地址不对 | 确认打开 `http://127.0.0.1:5173`，并确认后端监听 8787 |
| 真实写入按钮不可用 | 未开启确认或缺少必要参数 | 补齐测试群 `chat_id`、妙记链接、幂等后缀等参数后再确认 |

## 7. 后续可继续增强

- 把 Dashboard KPI 改成更接近 Ragent trace 的趋势与质量摘要。
- 在真实联调页增加四终端状态时间线。
- 增加 Console API 在线状态心跳，显示在 topbar。
- 为长命令输出增加复制按钮和 trace_id 快速定位。
- 增加 Playwright 截图检查，覆盖 1440px、1024px、390px 三类视口。
