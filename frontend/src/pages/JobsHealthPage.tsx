import { Database, Play, RefreshCw, ServerCog, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { consoleApi } from "../api/client";
import type { JobsResult, MigrationStatus, WorkerRunResult } from "../api/types";
import { DataTable } from "../components/DataTable";
import { FeatureCard } from "../components/FeatureCard";
import { JsonPreview } from "../components/JsonPreview";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
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
      <PageHeader
        eyebrow="Operations"
        title="Jobs / Health"
        description="查看 SQLite migration、workflow_jobs 队列和 worker dry-run，快速定位后台链路是否健康。"
        meta={
          <>
            <StatusBadge status={migration?.verify.ok ? "schema ok" : "待检查"} tone={migration?.verify.ok ? "ok" : "warn"} />
            <span>第一版 worker 操作仅允许 dry-run。</span>
          </>
        }
        actions={
          <div className="button-row">
            <button className="button button--secondary" onClick={() => void load()}>
              <RefreshCw size={16} />
              刷新
            </button>
            <button className="button" onClick={() => void runWorker()} disabled={running}>
              <Play size={16} />
              {running ? "执行中" : "Worker Dry-run"}
            </button>
          </div>
        }
      />
      {error ? <div className="alert alert--danger">健康检查失败：{error}。请先确认 Console API 和 SQLite 路径可访问。</div> : null}
      <section className="feature-grid feature-grid--three">
        <FeatureCard
          icon={Database}
          title="SQLite Schema"
          description="验证 migrations 是否完整，避免旧表字段导致真实联调失败。"
          status={migration?.verify.ok ? "正常" : "待检查"}
          tone={migration?.verify.ok ? "ok" : "warn"}
        />
        <FeatureCard
          icon={ServerCog}
          title="Workflow Jobs"
          description="查看 callback、daemon 和 worker 写入的后台任务，关注 failed/dead_letter。"
          status={jobs?.items.length ? "有记录" : "暂无任务"}
          tone="muted"
        />
        <FeatureCard
          icon={ShieldCheck}
          title="Worker Dry-run"
          description="只验证 worker 能否领取和解析任务，不执行真实写操作。"
          status={worker ? (worker.ok ? "通过" : "失败") : "未运行"}
          tone={worker ? (worker.ok ? "ok" : "danger") : "warn"}
        />
      </section>
      <div className="metric-grid">
        <MetricCard
          label="Verify"
          value={migration?.verify.ok ? "OK" : "FAIL"}
          detail={migration?.verify.error || migration?.status.db_path || "-"}
          helper="schema verify 失败时先运行 storage_migrate.py --verify。"
          icon={Database}
          tone={migration?.verify.ok ? "ok" : "danger"}
        />
        <MetricCard label="Applied" value={migration?.status.applied_count ?? "-"} helper="已经应用的 migration 数量。" />
        <MetricCard label="Pending" value={migration?.status.pending_count ?? "-"} helper="应保持为 0。" tone={(migration?.status.pending_count ?? 0) ? "warn" : "ok"} />
        <MetricCard label="Jobs" value={jobs?.items.length ?? "-"} helper="最近 50 条 workflow_jobs。" />
      </div>
      <section className="panel">
        <div className="panel__header">
          <div>
            <h2>Workflow Jobs</h2>
            <p>排查后台任务时优先看 status、attempts 和 last_error。</p>
          </div>
        </div>
        <DataTable
          rows={jobs?.items ?? []}
          empty="暂无任务"
          emptyHint="可以先执行 M3 发卡、M5 任务风险提醒或 callback 入队流程。"
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
            <div>
              <h2>Worker Dry-run</h2>
              <p>本操作不会真实写飞书，只用于检查 worker 入口是否可执行。</p>
            </div>
            <StatusBadge status={worker.ok ? "success" : "failed"} />
          </div>
          <JsonPreview value={worker.stdout} maxHeight={280} />
        </section>
      ) : null}
    </div>
  );
}
