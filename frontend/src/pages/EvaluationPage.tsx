import { Play, RefreshCw } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { consoleApi } from "../api/client";
import type { EvaluationReport, LatestReport } from "../api/types";
import { DataTable } from "../components/DataTable";
import { JsonPreview } from "../components/JsonPreview";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";

export function EvaluationPage() {
  const [latest, setLatest] = useState<LatestReport<EvaluationReport> | null>(null);
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [caseId, setCaseId] = useState("");
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);

  const loadLatest = async () => {
    setError("");
    try {
      const data = (await consoleApi.latestReport("evaluation")) as LatestReport<EvaluationReport>;
      setLatest(data);
      if (data.exists) setReport(data.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void loadLatest();
  }, []);

  const run = async (event: FormEvent) => {
    event.preventDefault();
    setRunning(true);
    setError("");
    try {
      setReport(
        await consoleApi.runEvaluation({
          suite: "agent_trajectory",
          case_id: caseId,
          provider: "scripted_debug",
          fail_under: 0.95,
          write_report: true
        })
      );
      await loadLatest();
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
          <h1>Agent 评测中心</h1>
          <p>工具轨迹、Policy 合规和安全门禁</p>
        </div>
        <button className="button button--secondary" onClick={() => void loadLatest()}>
          <RefreshCw size={16} />
          最新报告
        </button>
      </div>
      {error ? <div className="alert alert--danger">{error}</div> : null}
      <form className="toolbar" onSubmit={run}>
        <select value={caseId} onChange={(event) => setCaseId(event.target.value)}>
          <option value="">全部 case</option>
          <option value="m3_evidence_first_plan">m3_evidence_first_plan</option>
          <option value="m4_owner_missing_needs_confirmation">m4_owner_missing_needs_confirmation</option>
          <option value="policy_blocks_unconfirmed_write">policy_blocks_unconfirmed_write</option>
        </select>
        <button className="button" disabled={running}>
          <Play size={16} />
          运行评测
        </button>
      </form>
      <div className="metric-grid">
        <MetricCard label="Score" value={report?.score ?? "-"} tone={(report?.score ?? 0) >= 0.95 ? "ok" : "warn"} />
        <MetricCard
          label="Safety"
          value={report?.safety_score ?? "-"}
          tone={(report?.safety_score ?? 0) === 1 ? "ok" : "danger"}
        />
        <MetricCard label="Cases" value={report ? `${report.passed_cases}/${report.total_cases}` : "-"} />
        <MetricCard label="Provider" value={report?.provider || "scripted_debug"} detail={latest?.path || ""} />
      </div>
      <section className="panel">
        <div className="panel__header">
          <h2>Case 结果</h2>
        </div>
        <DataTable
          rows={report?.results ?? []}
          empty="暂无评测结果"
          columns={[
            { key: "case", header: "Case", render: (row) => <code>{row.case_id}</code> },
            { key: "score", header: "Score", render: (row) => row.score },
            { key: "passed", header: "Passed", render: (row) => <StatusBadge status={row.passed ? "passed" : "failed"} /> },
            { key: "workflow", header: "Workflow", render: (row) => row.trace_summary.workflow_type },
            { key: "tools", header: "Tools", render: (row) => row.trace_summary.tool_calls.join(" -> ") }
          ]}
        />
      </section>
      {report?.results?.[0] ? (
        <section className="panel">
          <div className="panel__header">
            <h2>指标明细</h2>
          </div>
          <JsonPreview value={report.results} maxHeight={420} />
        </section>
      ) : null}
    </div>
  );
}
