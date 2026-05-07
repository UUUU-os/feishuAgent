import { BarChart3, CalendarClock, ClipboardList, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { consoleApi } from "../api/client";
import type { DashboardData } from "../api/types";
import { DataTable } from "../components/DataTable";
import { FeatureCard } from "../components/FeatureCard";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
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
  const systemReady = Boolean(data?.health.migration.ok && data?.health.storage.db_exists);
  return (
    <div className="page">
      <PageHeader
        eyebrow="Agent Operations"
        title="MeetFlow Console"
        description="连接飞书真实业务、Agent 运行、后台队列和评测报告的一站式工作台。"
        meta={
          <>
            <StatusBadge status={systemReady ? "系统可运行" : "需要检查"} tone={systemReady ? "ok" : "danger"} />
            <span>默认安全策略：真实写入必须显式确认</span>
          </>
        }
        actions={
          <button className="button button--secondary" onClick={load} disabled={loading}>
            <RefreshCw size={16} />
            {loading ? "刷新中" : "刷新状态"}
          </button>
        }
      />
      {error ? <div className="alert alert--danger">加载 Dashboard 失败：{error}。请先确认 Console API 已启动。</div> : null}
      <section className="feature-grid">
        <FeatureCard
          icon={CalendarClock}
          title="M3 会前背景卡"
          description="选择飞书日程，触发会前知识检索和群卡片推送。默认 dry-run，真实发卡需要二次确认。"
          status={data?.m3.exists ? "已有报告" : "待运行"}
          tone={data?.m3.exists ? "ok" : "warn"}
          secondary={<span className="text-link">入口：M3 会前</span>}
        >
          <code>{data?.m3.path || "暂无 M3 报告"}</code>
        </FeatureCard>
        <FeatureCard
          icon={BarChart3}
          title="Agent 轨迹评测"
          description="检查工具调用顺序、Policy 合规、allow_write 门禁和幂等键覆盖。"
          status={(evaluation?.score ?? 0) >= 0.95 ? "质量通过" : "待评测"}
          tone={(evaluation?.score ?? 0) >= 0.95 ? "ok" : "warn"}
          secondary={<span className="text-link">入口：Agent 评测</span>}
        >
          <span>score={evaluation?.score ?? "-"} / safety={evaluation?.safety_score ?? "-"}</span>
        </FeatureCard>
        <FeatureCard
          icon={ClipboardList}
          title="后台队列与健康"
          description="查看 workflow_jobs、migration verify 和 worker dry-run，定位任务堆积或失败原因。"
          status={Object.values(data?.job_status_counts ?? {}).some(Boolean) ? "有任务记录" : "暂无任务"}
          tone="muted"
          secondary={<span className="text-link">入口：Jobs / Health</span>}
        >
          <span>
            {Object.entries(data?.job_status_counts ?? {})
              .map(([status, count]) => `${status}:${count}`)
              .join("  ") || "队列为空"}
          </span>
        </FeatureCard>
      </section>
      <div className="metric-grid">
        <MetricCard
          label="Migration"
          value={data?.health.migration.ok ? "OK" : "FAIL"}
          detail={data?.health.storage.db_path ?? "-"}
          helper="SQLite schema 是否满足当前运行要求。"
          icon={ShieldCheck}
          tone={data?.health.migration.ok ? "ok" : "danger"}
        />
        <MetricCard
          label="Agent Score"
          value={evaluation?.score ?? "-"}
          detail={`Safety ${evaluation?.safety_score ?? "-"}`}
          helper=">= 0.95 且 safety=1.0 才建议继续真实联调。"
          icon={BarChart3}
          tone={(evaluation?.score ?? 0) >= 0.95 && (evaluation?.safety_score ?? 0) === 1 ? "ok" : "warn"}
        />
        <MetricCard
          label="Cases"
          value={evaluation ? `${evaluation.passed_cases}/${evaluation.total_cases}` : "-"}
          detail={data?.evaluation.path || "未生成评测报告"}
          helper="通过 case / 总 case，来自 agent_trajectory_latest.json。"
          tone="neutral"
        />
        <MetricCard
          label="Jobs"
          value={Object.values(data?.job_status_counts ?? {}).reduce((sum, item) => sum + item, 0)}
          detail={Object.entries(data?.job_status_counts ?? {})
            .map(([status, count]) => `${status}:${count}`)
            .join("  ")}
          helper="后台 workflow_jobs 的当前状态分布。"
          tone="neutral"
        />
      </div>
      <section className="panel">
        <div className="panel__header">
          <div>
            <h2>最近任务</h2>
            <p>用于排查 callback、daemon、worker 产生的后台任务。</p>
          </div>
        </div>
        <DataTable
          rows={data?.recent_jobs.items ?? []}
          empty="暂无任务"
          emptyHint="可以先运行 M3 发卡、风险巡检或 worker dry-run 生成任务记录。"
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
