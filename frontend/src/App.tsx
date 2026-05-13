import { Activity, BarChart3, CalendarClock, ClipboardList, RadioTower, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { DashboardPage } from "./pages/DashboardPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { JobsHealthPage } from "./pages/JobsHealthPage";
import { LiveFlowPage } from "./pages/LiveFlowPage";
import { M3ConsolePage } from "./pages/M3ConsolePage";

type PageKey = "dashboard" | "m3" | "live" | "evaluation" | "jobs";

type NavItem = { key: PageKey; label: string; description: string; icon: typeof Activity };

const navGroups: Array<{ title: string; items: NavItem[] }> = [
  {
    title: "总览",
    items: [{ key: "dashboard", label: "Dashboard", description: "系统总览", icon: Activity }]
  },
  {
    title: "核心流程",
    items: [
      { key: "m3", label: "M3 会前", description: "生成背景卡", icon: CalendarClock },
      { key: "live", label: "真实联调", description: "M4 / M5 / 回调", icon: RadioTower }
    ]
  },
  {
    title: "质量与运维",
    items: [
      { key: "evaluation", label: "Agent 评测", description: "质量门禁", icon: BarChart3 },
      { key: "jobs", label: "Jobs / Health", description: "队列与服务", icon: ClipboardList }
    ]
  }
];

export default function App() {
  const [page, setPage] = useState<PageKey>("dashboard");
  const currentPage = navGroups.flatMap((group) => group.items).find((item) => item.key === page);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark">MF</span>
          <div>
            <strong>MeetFlow</strong>
            <small>Console</small>
          </div>
        </div>
        <div className="sidebar__summary">
          <Sparkles size={16} />
          <span>会议知识闭环 Agent 的本地驾驶舱</span>
        </div>
        <nav>
          {navGroups.map((group) => (
            <div className="nav-group" key={group.title}>
              <p className="nav-group__title">{group.title}</p>
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.key}
                    className={page === item.key ? "nav-item nav-item--active" : "nav-item"}
                    onClick={() => setPage(item.key)}
                  >
                    <span className="nav-item__indicator" />
                    <Icon size={18} />
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar__copy">
            <span className="topbar__eyebrow">MeetFlow Console</span>
            <strong>{currentPage?.label ?? "Dashboard"}</strong>
          </div>
          <div className="topbar__meta">
            <span className="topbar__pill">
              <ShieldCheck size={14} />
              默认 dry-run
            </span>
            <span className="topbar__pill topbar__pill--danger">真实写入需二次确认</span>
          </div>
        </header>
        <main className="content">
          {page === "dashboard" ? <DashboardPage /> : null}
          {page === "m3" ? <M3ConsolePage /> : null}
          {page === "live" ? <LiveFlowPage /> : null}
          {page === "evaluation" ? <EvaluationPage /> : null}
          {page === "jobs" ? <JobsHealthPage /> : null}
        </main>
      </div>
    </div>
  );
}
