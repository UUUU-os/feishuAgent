import { Activity, BarChart3, CalendarClock, ClipboardList, Sparkles } from "lucide-react";
import { useState } from "react";
import { DashboardPage } from "./pages/DashboardPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { JobsHealthPage } from "./pages/JobsHealthPage";
import { M3ConsolePage } from "./pages/M3ConsolePage";

type PageKey = "dashboard" | "m3" | "evaluation" | "jobs";

const navItems: Array<{ key: PageKey; label: string; description: string; icon: typeof Activity }> = [
  { key: "dashboard", label: "Dashboard", description: "系统总览", icon: Activity },
  { key: "m3", label: "M3 会前", description: "生成背景卡", icon: CalendarClock },
  { key: "evaluation", label: "Agent 评测", description: "质量门禁", icon: BarChart3 },
  { key: "jobs", label: "Jobs / Health", description: "队列与服务", icon: ClipboardList }
];

export default function App() {
  const [page, setPage] = useState<PageKey>("dashboard");
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
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={page === item.key ? "nav-item nav-item--active" : "nav-item"}
                onClick={() => setPage(item.key)}
              >
                <Icon size={18} />
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
              </button>
            );
          })}
        </nav>
      </aside>
      <main className="content">
        {page === "dashboard" ? <DashboardPage /> : null}
        {page === "m3" ? <M3ConsolePage /> : null}
        {page === "evaluation" ? <EvaluationPage /> : null}
        {page === "jobs" ? <JobsHealthPage /> : null}
      </main>
    </div>
  );
}
