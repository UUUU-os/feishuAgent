import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { consoleApi } from "../api/client";
import type { DashboardData } from "../api/types";
import { DataTable } from "../components/DataTable";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setData(await consoleApi.dashboard());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const evaluation = data?.evaluation.data;
  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>MeetFlow Console</h1>
          <p>会议知识闭环 Agent 工作台</p>
        </div>
        <button className="button button--secondary" onClick={load} disabled={loading}>
          <RefreshCw size={16} />
          刷新
        </button>
      </div>
      {error ? <div className="alert alert--danger">{error}</div> : null}
      <div className="metric-grid">
        <MetricCard
          label="Migration"
          value={data?.health.migration.ok ? "OK" : "FAIL"}
          detail={data?.health.storage.db_path ?? "-"}
          tone={data?.health.migration.ok ? "ok" : "danger"}
        />
        <MetricCard
          label="Agent Score"
          value={evaluation?.score ?? "-"}
          detail={`Safety ${evaluation?.safety_score ?? "-"}`}
          tone={(evaluation?.score ?? 0) >= 0.95 && (evaluation?.safety_score ?? 0) === 1 ? "ok" : "warn"}
        />
        <MetricCard
          label="Cases"
          value={evaluation ? `${evaluation.passed_cases}/${evaluation.total_cases}` : "-"}
          detail={data?.evaluation.path || "未生成评测报告"}
          tone="neutral"
        />
        <MetricCard
          label="Jobs"
          value={Object.values(data?.job_status_counts ?? {}).reduce((sum, item) => sum + item, 0)}
          detail={Object.entries(data?.job_status_counts ?? {})
            .map(([status, count]) => `${status}:${count}`)
            .join("  ")}
          tone="neutral"
        />
      </div>
      <section className="panel">
        <div className="panel__header">
          <h2>最近任务</h2>
        </div>
        <DataTable
          rows={data?.recent_jobs.items ?? []}
          empty="暂无任务"
          columns={[
            { key: "job_id", header: "Job", render: (row) => <code>{row.job_id}</code> },
            { key: "queue", header: "Queue", render: (row) => row.queue_name },
            { key: "type", header: "Type", render: (row) => row.job_type },
            { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
            { key: "attempts", header: "Attempts", render: (row) => `${row.attempts}/${row.max_attempts}` }
          ]}
        />
      </section>
    </div>
  );
}
