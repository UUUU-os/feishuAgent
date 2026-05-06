import { Activity, BarChart3, CalendarClock, ClipboardList } from "lucide-react";
import { useState } from "react";
import { DashboardPage } from "./pages/DashboardPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { JobsHealthPage } from "./pages/JobsHealthPage";
import { M3ConsolePage } from "./pages/M3ConsolePage";

type PageKey = "dashboard" | "m3" | "evaluation" | "jobs";

const navItems: Array<{ key: PageKey; label: string; icon: typeof Activity }> = [
  { key: "dashboard", label: "Dashboard", icon: Activity },
  { key: "m3", label: "M3 发卡", icon: CalendarClock },
  { key: "evaluation", label: "评测", icon: BarChart3 },
  { key: "jobs", label: "Jobs", icon: ClipboardList }
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
                {item.label}
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
