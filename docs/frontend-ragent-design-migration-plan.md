# MeetFlow 前端参考 Ragent 设计迁移方案

本文档基于对 `/home/good/ye/workhard/ragent-main/frontend` 与当前 MeetFlow `frontend/` 的代码阅读，给出一份可迁移到当前项目的前端设计方案。本文只做设计与改造规划，不修改前端业务逻辑。

## 1. 阅读范围

### 1.1 Ragent 参考项目

重点阅读文件：

- `/home/good/ye/workhard/ragent-main/frontend/src/styles/globals.css`
- `/home/good/ye/workhard/ragent-main/frontend/tailwind.config.cjs`
- `/home/good/ye/workhard/ragent-main/frontend/src/components/layout/MainLayout.tsx`
- `/home/good/ye/workhard/ragent-main/frontend/src/components/layout/Sidebar.tsx`
- `/home/good/ye/workhard/ragent-main/frontend/src/components/layout/Header.tsx`
- `/home/good/ye/workhard/ragent-main/frontend/src/pages/admin/AdminLayout.tsx`
- `/home/good/ye/workhard/ragent-main/frontend/src/pages/admin/dashboard/DashboardPage.tsx`
- `/home/good/ye/workhard/ragent-main/frontend/src/pages/admin/traces/**`
- `/home/good/ye/workhard/ragent-main/frontend/src/components/ui/**`
- `/home/good/ye/workhard/ragent-main/frontend/package.json`

### 1.2 MeetFlow 当前项目

重点阅读文件：

- `frontend/src/styles/app.css`
- `frontend/src/App.tsx`
- `frontend/src/components/**`
- `frontend/src/pages/**`
- `frontend/package.json`

## 2. Ragent 设计特征提炼

Ragent 有两套明显视觉语言：

1. 聊天主界面：浅色侧栏、对话列表、白色主内容区，偏 AI Chat 产品。
2. Admin 后台：深色渐变侧栏、浅灰工作区、白色卡片、紧凑表格、KPI 卡片，偏运维/控制台。

MeetFlow 是会议智能工作台，不是聊天产品，因此建议迁移 **Ragent Admin / Trace 控制台风格**，而不是完整迁移聊天界面。

### 2.1 字体

Ragent Tailwind 配置中定义：

```js
fontFamily: {
  display: ["'Space Grotesk'", "ui-sans-serif", "system-ui"],
  body: ["'DM Sans'", "ui-sans-serif", "system-ui"],
  mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular"]
}
```

Ragent 实际全局变量中也保留了系统字体栈：

```css
--font-sans:
  -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
  "Helvetica Neue", Arial, sans-serif;
--font-mono: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;
```

MeetFlow 当前使用：

```css
Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

迁移建议：

- 不引入远程字体，避免网络依赖和中文显示不稳定。
- 使用系统 UI 字体作为主字体，增加中文友好字体：
  `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif`
- 数字、trace_id、命令和 JSON 使用 mono 字体：
  `"SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace`

### 2.2 色彩

Ragent 主要色彩 token：

| 用途 | Ragent 色值 | 说明 |
|---|---|---|
| 页面背景 | `#FAFAFA` / `#F3F4F6` | 干净浅灰，适合后台 |
| 主文字 | `#1A1A1A` / `#0F172A` / `#111827` | 深灰，不用纯黑 |
| 次级文字 | `#4A4A4A` / `#64748B` | 表格、说明、meta |
| 弱文字 | `#999999` / `#94A3B8` | 时间、辅助标签 |
| 主蓝 | `#3B82F6` | Chat 主强调色 |
| 深蓝 | `#2563EB` | 按钮 hover / active |
| 靛紫 | `#4F46E5` / `#7C3AED` | Admin 主按钮和侧栏 logo |
| 成功 | `#10B981` | 健康、通过 |
| 警告 | `#F59E0B` | 风险、注意 |
| 错误 | `#EF4444` | 失败、真实写入警告 |
| 边框 | `#E5E5E5` / `#E2E8F0` / `#DFE6EF` | 轻边框 |

MeetFlow 当前色彩偏深色 navy + teal：

| 用途 | 当前色值 |
|---|---|
| 侧栏 | `#111827` |
| 主强调 | `#16796F` / `#237C74` / `#74D3C6` |
| 背景 | `#F7F8FB` |
| 卡片边框 | `#DFE6EF` |

迁移建议：

- 将主强调色从 teal 调整到 Ragent 蓝/靛体系，降低“单一青绿色”观感。
- 保留少量 teal 作为 MeetFlow 品牌辅助色，用于成功态或 Evidence/RAG 标签。
- 风险巡检、真实写入等场景保持红/橙状态色，避免全蓝。

推荐 MeetFlow token：

```css
:root {
  --mf-bg-page: #f3f4f6;
  --mf-bg-surface: #ffffff;
  --mf-bg-muted: #f8fafc;
  --mf-bg-subtle: #f1f5f9;

  --mf-text-primary: #0f172a;
  --mf-text-secondary: #334155;
  --mf-text-muted: #64748b;
  --mf-text-weak: #94a3b8;
  --mf-text-inverse: #ffffff;

  --mf-primary: #2563eb;
  --mf-primary-hover: #1d4ed8;
  --mf-primary-soft: #dbeafe;
  --mf-indigo: #4f46e5;
  --mf-purple: #7c3aed;
  --mf-teal: #14b8a6;

  --mf-success: #10b981;
  --mf-warning: #f59e0b;
  --mf-danger: #ef4444;
  --mf-info: #3b82f6;

  --mf-border: #e2e8f0;
  --mf-border-strong: #cbd5e1;

  --mf-sidebar-start: #1a1f2e;
  --mf-sidebar-end: #252d3d;
}
```

### 2.3 圆角、阴影与密度

Ragent 常用尺度：

| 项 | Ragent 取值 |
|---|---|
| 小圆角 | `6px` |
| 中圆角 | `8px` / `12px` |
| 大卡片 | `16px` / `20px` |
| 表格/trace 模块 | `8px` |
| 卡片阴影 | `0 1px 3px rgba(15,23,42,0.08)` |
| 浮层阴影 | `0 10px 24px rgba(0,0,0,0.1)` |
| Hover 位移 | `translateY(-2px)` 或 `translateX(2px)` |

MeetFlow 当前已有 `8px/16px/18px` 混用。迁移建议：

- 控制台密集模块：统一 `8px`。
- 页面主卡片和弹窗：最多 `12px`。
- 侧栏 logo、状态 chip 可用 `10px-12px`。
- 避免过多超大圆角，让界面更像专业后台。

### 2.4 布局

Ragent Admin 布局：

- 左侧深色渐变侧栏：`from #1a1f2e to #252d3d`。
- 顶部 sticky topbar：白色半透明 `bg-white/80 backdrop-blur`。
- 内容区：浅灰背景，最大宽度 `1600px`，左右 padding `32px`。
- 页面头：标题 + 描述 + 操作按钮，避免营销式大 Hero。
- Dashboard：KPI 四列 + 主图表 + 右侧洞察。
- Trace 页面：紧凑头卡、filter card、stat card、table card。

MeetFlow 当前布局：

- 左侧深色侧栏已存在，但视觉偏重。
- 没有独立 topbar。
- 页面内容大多是 `PageHeader` + feature grid + panel。
- CSS 是全局 class，没有 Tailwind。

迁移建议：

- 保留当前 React 状态导航，不强行引入 router。
- 视觉上迁移 Ragent Admin：深色渐变 sidebar + 浅灰工作区 + 白色模块。
- 新增一个轻量 topbar，用于显示当前页面名、环境状态、刷新按钮、dry-run/allow-write 状态提示。
- Dashboard 页面参考 Ragent 的 KPI + 趋势 + 侧边洞察布局。

## 3. 当前 MeetFlow 前端可迁移目标

### 3.1 目标体验

迁移后 MeetFlow 应呈现为：

```text
MeetFlow Console
  左侧：深色渐变导航 + 品牌 + 当前安全状态
  顶部：当前页面标题 + Console API 状态 + 快捷刷新
  主区：浅灰背景 + 白色工作模块 + KPI / 表格 / 命令结果
```

关键词：

- 专业；
- 清爽；
- 可扫描；
- 操作密度高；
- 安全状态明显；
- 不做营销落地页；
- 不使用大面积装饰渐变背景。

### 3.2 设计语言

建议采用“Ragent Admin + MeetFlow 安全控制台”的混合设计：

- 用 Ragent 的蓝/靛色作为主操作；
- 用 MeetFlow 的 teal 作为会议知识/RAG 辅助色；
- 用红色突出真实飞书写入；
- 用 amber 突出风险巡检；
- 用绿色突出健康/评测通过。

## 4. 设计 Token 迁移方案

### 4.1 CSS 变量

建议在 `frontend/src/styles/app.css` 顶部重构为 token-first：

```css
:root {
  --mf-font-sans:
    Inter, -apple-system, BlinkMacSystemFont, "Segoe UI",
    "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
  --mf-font-mono: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;

  --mf-bg-page: #f3f4f6;
  --mf-bg-surface: #ffffff;
  --mf-bg-muted: #f8fafc;
  --mf-bg-subtle: #f1f5f9;

  --mf-text-primary: #0f172a;
  --mf-text-secondary: #334155;
  --mf-text-muted: #64748b;
  --mf-text-weak: #94a3b8;
  --mf-text-inverse: #ffffff;

  --mf-primary: #2563eb;
  --mf-primary-hover: #1d4ed8;
  --mf-primary-soft: #dbeafe;
  --mf-indigo: #4f46e5;
  --mf-purple: #7c3aed;
  --mf-teal: #14b8a6;

  --mf-success: #10b981;
  --mf-warning: #f59e0b;
  --mf-danger: #ef4444;
  --mf-info: #3b82f6;

  --mf-border: #e2e8f0;
  --mf-border-strong: #cbd5e1;

  --mf-radius-sm: 6px;
  --mf-radius-md: 8px;
  --mf-radius-lg: 12px;

  --mf-shadow-card: 0 1px 3px rgba(15, 23, 42, 0.08);
  --mf-shadow-hover: 0 10px 24px rgba(15, 23, 42, 0.1);
  --mf-shadow-dialog: 0 30px 80px rgba(15, 23, 42, 0.28);
}
```

### 4.2 字号体系

参考 Ragent Admin 和 Trace 页面，MeetFlow 推荐：

| 场景 | 字号 | 字重 | 说明 |
|---|---:|---:|---|
| 页面标题 | `24px` | `600` | 当前 `34px` 偏大，可降低后台感 |
| 页面描述 | `14px` | `400` | `#64748b` |
| 模块标题 | `16px` | `600` | panel header |
| KPI 数字 | `28px` | `700` | 使用 tabular nums |
| 表格正文 | `13px` | `400` | 提高密度 |
| 表头 | `12px` | `600` | 弱色 |
| chip / badge | `11px-12px` | `500-600` | 圆角 pill |
| 命令/JSON | `12px-13px` | mono | 保持可读 |

### 4.3 状态色语义

| 状态 | 用色 | MeetFlow 场景 |
|---|---|---|
| 成功 | `#10B981` | health OK、eval passed、job success |
| 警告 | `#F59E0B` | risk warning、dry-run 提醒、配置缺项 |
| 危险 | `#EF4444` | allow-write、真实发卡、失败 job |
| 信息 | `#3B82F6` | 普通主按钮、链接、活跃导航 |
| 知识/RAG | `#14B8A6` | evidence pack、RAG 命中、资料同步 |

## 5. 组件级迁移方案

### 5.1 App Shell

当前：

- `.app-shell` 为 `grid-template-columns: 276px 1fr`。
- `.sidebar` 深色。
- `.content` 直接承载页面。

建议：

```text
.app-shell
  .sidebar
  .main-shell
    .topbar
    .content
```

不需要立刻引入 `react-router-dom`；当前页面 state 切换可以保留。

### 5.2 Sidebar

参考 Ragent Admin：

- 背景：`linear-gradient(180deg, #1a1f2e 0%, #252d3d 100%)`
- 宽度：`264px` 或 `276px`
- 品牌 logo：蓝/靛渐变，不再使用纯 teal
- 分组标题：`10px uppercase` 或中文小标题，颜色 `rgba(255,255,255,0.42)`
- active item：`bg-indigo-500/20` + 左侧 `3px` indicator
- hover：`rgba(255,255,255,0.1)`

MeetFlow 导航建议分组：

```text
总览
  Dashboard
核心流程
  M3 会前
  真实联调
质量与运维
  Agent 评测
  Jobs / Health
```

### 5.3 Topbar

参考 Ragent Admin topbar：

- sticky top；
- 高度 `64px`；
- 白色半透明；
- `border-bottom: 1px solid #e2e8f0`；
- 左侧当前页面标题；
- 右侧 API 状态、环境、刷新按钮。

MeetFlow topbar 可显示：

- 当前页面；
- Console API status；
- `dry-run default` 安全提示；
- 当前时间；
- 刷新按钮。

### 5.4 Page Header

当前 `PageHeader` 有接近 hero 的效果。建议改为更后台化：

- 使用 `.admin-page-header`，不要大面积卡片；
- H1 `24px / 600`；
- 描述 `14px / #64748b`；
- 操作按钮右对齐；
- 页面顶部不要做营销式 Hero。

### 5.5 MetricCard

参考 Ragent `admin-stat-card`：

- 卡片 `border #e2e8f0`；
- `border-radius: 12px`；
- `box-shadow: 0 1px 3px rgba(15,23,42,0.08)`；
- icon 圆形浅色底；
- 数字 `28px / 700`；
- hover 轻微 `translateY(-1px)`。

MeetFlow KPI 建议：

- Health：绿色；
- M3/M4 已生成报告：蓝色；
- Risk 命中：amber；
- Failed jobs：红色。

### 5.6 Panel / Form Panel

参考 Ragent `ui-card`：

- `border-radius: 12px`；
- header 与 content 分区；
- 表单控件高度 `36px-40px`；
- label `13px #64748b`；
- 操作按钮使用 icon + text；
- dangerous action 使用红色按钮，不和主按钮混淆。

### 5.7 Table

参考 Ragent `ui-table` / trace table：

- 表格字体 `13px`；
- 表头高度 `44px`；
- 行高 `48px`；
- 表头背景 `#F9FAFB`；
- 偶数行 `#F8FAFC66`；
- hover `#F9FAFB`；
- 表格容器圆角 `8px`。

### 5.8 JSON / Command Result

当前 JSON 预览为深色背景，建议保留，但更接近 Ragent trace：

- JSON code panel：`#0F172A` 背景；
- 文字 `#E2E8F0`；
- command chip：浅灰背景 + mono；
- 成功/失败 callout 用状态色左边条。

### 5.9 Dialog

真实写入确认弹窗应强化：

- 背景遮罩：`rgba(15,23,42,0.45)`；
- 弹窗半径 `12px`；
- 危险 icon：红色浅底；
- 主按钮：红色；
- 取消按钮：outline / secondary；
- 列出目标群、命令、`allow_write=true`、幂等键。

## 6. 页面级迁移方案

### 6.1 DashboardPage

目标：从“功能入口卡片”升级为“会议 Agent 运行态总览”。

建议结构：

```text
顶部：页面标题 + 刷新
KPI：Health / Eval Score / Recent Jobs / Latest Report
主区左：M3/M4/M5 最新报告卡片
主区右：安全边界卡片 + 最近风险/失败 Job
底部：最近 Jobs 表格
```

视觉参考：

- Ragent Dashboard KPI 四列；
- Ragent AI 性能圆环可改造成 eval score；
- Ragent insights 可改造成“联调建议 / 风险提示”。

### 6.2 M3ConsolePage

目标：更像受控 workflow form。

建议结构：

```text
左侧 sticky 流程说明：health -> dry-run -> allow-write
右侧表单：date / title / doc / minute / provider
底部结果：命令、report_path、JSON
```

样式：

- doc/minute 输入使用宽字段；
- `allow_write` 使用红色 danger check-row；
- Evidence Pack 标签使用 teal。

### 6.3 LiveFlowPage

目标：突出真实联调高风险和四终端状态。

建议结构：

```text
顶部安全警告条：真实飞书写入只允许测试群
四步流程卡：SDK callback / worker / send D3 card / watch logs
M4 表单和 M5 表单并排
服务状态表格
回调日志结果
```

样式：

- 四终端步骤卡使用 `StepList` + 状态 badge；
- `allow_write` 区域红色边框；
- worker / callback 状态用绿色/灰色 pill。

### 6.4 EvaluationPage

目标：参考 Ragent Trace/Quality 页面。

建议结构：

```text
KPI：score / safety_score / passed / total cases
评测表格：case_id / workflow / score / safety / status
报告路径：mono chip + copy button
```

### 6.5 JobsHealthPage

目标：做成运维页面。

建议结构：

```text
顶部：storage/migration/service health KPI
服务控制 panel
Jobs table
Migration / latest report cards
```

视觉参考：

- Ragent trace filter + table；
- status chip 使用统一状态色。

## 7. 技术迁移路径

### 7.1 推荐路径：CSS Token First，低风险迁移

当前 MeetFlow 前端没有 Tailwind，也没有 Radix/shadcn。为了不扩大依赖，建议先不引入 Tailwind，直接重构 `app.css`：

1. 新增 `--mf-*` 设计变量；
2. 改造 `body` / `.app-shell` / `.sidebar` / `.content`；
3. 新增 `.topbar`；
4. 调整 `.page-hero` 为后台 header；
5. 统一 `.panel`、`.metric-card`、`.feature-card`、`.table-wrap`；
6. 调整按钮、badge、alert、callout、dialog；
7. 最后逐页微调 JSX className。

优点：

- 不改构建链路；
- 不引入大量依赖；
- diff 可控；
- 更适合当前项目短期演示。

### 7.2 可选路径：Tailwind + shadcn 化

如果后续时间充足，可以迁移到 Ragent 的 Tailwind 体系：

新增依赖：

- `tailwindcss`
- `postcss`
- `autoprefixer`
- `class-variance-authority`
- `clsx`
- `tailwind-merge`
- Radix UI 组件

但这会影响构建、组件写法和样式策略。当前 D8/演示阶段不建议作为第一步。

## 8. 建议改造步骤

### 阶段 1：设计 token 与基础布局

修改：

- `frontend/src/styles/app.css`
- `frontend/src/App.tsx`

内容：

- 加入 `--mf-*` token；
- sidebar 改为 Ragent Admin 渐变；
- content 背景改为 `#f3f4f6`；
- 增加 topbar；
- 调整页面宽度和 padding。

验收：

- 页面不横向溢出；
- 左侧导航可读；
- 移动端仍可用；
- 不影响 API 调用。

### 阶段 2：基础组件统一

修改：

- `frontend/src/components/PageHeader.tsx`
- `frontend/src/components/MetricCard.tsx`
- `frontend/src/components/FeatureCard.tsx`
- `frontend/src/components/DataTable.tsx`
- `frontend/src/components/StatusBadge.tsx`
- `frontend/src/components/CommandResultPanel.tsx`
- `frontend/src/components/ConfirmWriteDialog.tsx`

内容：

- 统一 card/header/table/button/badge/dialog 视觉；
- 所有按钮保持 icon + text；
- 真实写入按钮保持 danger。

验收：

- Dashboard、M3、Live、Eval、Jobs 页面视觉一致；
- 按钮文本不溢出；
- 表格在窄屏可横向滚动。

### 阶段 3：页面级精修

修改：

- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/pages/M3ConsolePage.tsx`
- `frontend/src/pages/LiveFlowPage.tsx`
- `frontend/src/pages/EvaluationPage.tsx`
- `frontend/src/pages/JobsHealthPage.tsx`

内容：

- Dashboard 变成 KPI + 报告 + 运行态；
- LiveFlow 增加四终端步骤区；
- Evaluation 参考 Trace 页面做紧凑表格；
- JobsHealth 更像运维控制台。

验收：

- 每页首屏能看到核心状态；
- 不需要滚很久才能执行主操作；
- 真实写入风险提示醒目。

### 阶段 4：验证与截图

命令：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan/frontend
npm run build
npm run dev -- --host 127.0.0.1 --port 5173
```

建议用 Playwright 或浏览器检查：

- 1440px 桌面；
- 1024px 平板；
- 390px 移动端；
- Dashboard；
- M3；
- LiveFlow；
- Evaluation；
- JobsHealth；
- 弹窗；
- 表格空态；
- 错误态。

## 9. 具体 CSS 改造草案

以下是可作为下一步实现参考的样式方向，不建议整段一次性替换，应按阶段迁移。

```css
:root {
  --mf-font-sans:
    Inter, -apple-system, BlinkMacSystemFont, "Segoe UI",
    "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
  --mf-font-mono: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;
  --mf-bg-page: #f3f4f6;
  --mf-bg-surface: #ffffff;
  --mf-bg-muted: #f8fafc;
  --mf-text-primary: #0f172a;
  --mf-text-secondary: #334155;
  --mf-text-muted: #64748b;
  --mf-primary: #2563eb;
  --mf-primary-hover: #1d4ed8;
  --mf-primary-soft: #dbeafe;
  --mf-success: #10b981;
  --mf-warning: #f59e0b;
  --mf-danger: #ef4444;
  --mf-border: #e2e8f0;
  --mf-radius-md: 8px;
  --mf-radius-lg: 12px;
  --mf-shadow-card: 0 1px 3px rgba(15, 23, 42, 0.08);
  --mf-shadow-hover: 0 10px 24px rgba(15, 23, 42, 0.1);
}

body {
  font-family: var(--mf-font-sans);
  color: var(--mf-text-primary);
  background: var(--mf-bg-page);
}

.app-shell {
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr);
  min-height: 100vh;
  background: var(--mf-bg-page);
}

.sidebar {
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  background: linear-gradient(180deg, #1a1f2e 0%, #252d3d 100%);
}

.content {
  min-width: 0;
  padding: 32px;
  background: var(--mf-bg-page);
}

.panel,
.metric-card,
.feature-card,
.form-panel {
  border: 1px solid var(--mf-border);
  border-radius: var(--mf-radius-lg);
  background: var(--mf-bg-surface);
  box-shadow: var(--mf-shadow-card);
}

.button {
  border-radius: var(--mf-radius-md);
  background: var(--mf-primary);
  color: #ffffff;
  font-weight: 600;
}

.button:hover {
  background: var(--mf-primary-hover);
}

.button--danger {
  background: var(--mf-danger);
}
```

## 10. 风险与边界

- 不建议直接复制 Ragent 全套 Tailwind/shadcn 组件，否则会把当前简单前端变成大规模依赖迁移。
- 不建议照搬 Ragent Chat 页侧栏，因为 MeetFlow 不是聊天产品。
- 不建议继续扩大 teal 作为唯一主色；当前页面已经偏 teal，迁移目标应加入蓝/靛/状态色。
- 不建议在核心工具台里加入大 hero、装饰光斑、过重渐变背景。
- 真实写入相关按钮必须继续使用红色 danger 语义，不要被主色弱化。
- 所有新增视觉应保持 text overflow、表格滚动和移动端布局可用。

## 11. 最终建议

第一版迁移只做 CSS 与少量布局组件改造，不动 API 和业务逻辑：

1. 先把 `app.css` token 化；
2. 迁移 sidebar、content、card、button、badge、table；
3. 加 topbar；
4. 精修 Dashboard 和 LiveFlow；
5. 跑 `npm run build` 和桌面/移动端截图检查。

这样可以在较低风险下，让当前 MeetFlow 前端接近 Ragent Admin 的美观度，同时保持 MeetFlow 自己的“会议 Agent 控制台”定位。
