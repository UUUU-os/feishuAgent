import { Play, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { consoleApi } from "../api/client";
import type { JobsResult, MigrationStatus, WorkerRunResult } from "../api/types";
import { DataTable } from "../components/DataTable";
import { JsonPreview } from "../components/JsonPreview";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";

export function JobsHealthPage() {
  const [migration, setMigration] = useState<MigrationStatus | null>(null);
  const [jobs, setJobs] = useState<JobsResult | null>(null);
  const [worker, setWorker] = useState<WorkerRunResult | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);

  const load = async () => {
    setError("");
    try {
      const [migrationStatus, jobsResult] = await Promise.all([consoleApi.migrationStatus(), consoleApi.jobs({ limit: 50 })]);
      setMigration(migrationStatus);
      setJobs(jobsResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const runWorker = async () => {
    setRunning(true);
    setError("");
    try {
      setWorker(await consoleApi.runWorkerOnce());
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Jobs / Health</h1>
          <p>后台队列、migration 和 worker dry-run</p>
        </div>
        <div className="button-row">
          <button className="button button--secondary" onClick={() => void load()}>
            <RefreshCw size={16} />
            刷新
          </button>
          <button className="button" onClick={() => void runWorker()} disabled={running}>
            <Play size={16} />
            Worker
          </button>
        </div>
      </div>
      {error ? <div className="alert alert--danger">{error}</div> : null}
      <div className="metric-grid">
        <MetricCard
          label="Verify"
          value={migration?.verify.ok ? "OK" : "FAIL"}
          detail={migration?.verify.error || migration?.status.db_path || "-"}
          tone={migration?.verify.ok ? "ok" : "danger"}
        />
        <MetricCard label="Applied" value={migration?.status.applied_count ?? "-"} />
        <MetricCard label="Pending" value={migration?.status.pending_count ?? "-"} tone={(migration?.status.pending_count ?? 0) ? "warn" : "ok"} />
        <MetricCard label="Jobs" value={jobs?.items.length ?? "-"} />
      </div>
      <section className="panel">
        <div className="panel__header">
          <h2>Workflow Jobs</h2>
        </div>
        <DataTable
          rows={jobs?.items ?? []}
          empty="暂无任务"
          columns={[
            { key: "job", header: "Job", render: (row) => <code>{row.job_id}</code> },
            { key: "queue", header: "Queue", render: (row) => row.queue_name },
            { key: "type", header: "Type", render: (row) => row.job_type },
            { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
            { key: "attempts", header: "Attempts", render: (row) => `${row.attempts}/${row.max_attempts}` },
            { key: "error", header: "Error", render: (row) => row.last_error || "-" }
          ]}
        />
      </section>
      {worker ? (
        <section className="panel">
          <div className="panel__header">
            <h2>Worker Dry-run</h2>
            <StatusBadge status={worker.ok ? "success" : "failed"} />
          </div>
          <JsonPreview value={worker.stdout} maxHeight={280} />
        </section>
      ) : null}
    </div>
  );
}
