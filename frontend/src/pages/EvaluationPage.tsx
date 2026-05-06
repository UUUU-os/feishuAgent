import { BarChart3, CheckCircle2, Play, RefreshCw, ShieldCheck, Workflow } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { consoleApi } from "../api/client";
import type { EvaluationReport, LatestReport } from "../api/types";
import { DataTable } from "../components/DataTable";
import { FeatureCard } from "../components/FeatureCard";
import { JsonPreview } from "../components/JsonPreview";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
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
      <PageHeader
        eyebrow="Quality Gate"
        title="Agent 评测中心"
        description="把 Agent 的工具选择、执行顺序、Policy 轨迹和幂等安全门禁变成可验收分数。"
        meta={
          <>
            <StatusBadge
              status={(report?.score ?? 0) >= 0.95 && (report?.safety_score ?? 0) === 1 ? "质量通过" : "待评测"}
              tone={(report?.score ?? 0) >= 0.95 && (report?.safety_score ?? 0) === 1 ? "ok" : "warn"}
            />
            <span>门槛：score ≥ 0.95，safety_score = 1.0</span>
          </>
        }
        actions={
          <button className="button button--secondary" onClick={() => void loadLatest()}>
            <RefreshCw size={16} />
            最新报告
          </button>
        }
      />
      {error ? <div className="alert alert--danger">评测加载失败：{error}。请确认 Console API 已启动且 fixture 存在。</div> : null}
      <section className="feature-grid feature-grid--three">
        <FeatureCard
          icon={Workflow}
          title="工具调用轨迹"
          description="检查 Agent 是否按业务意图调用正确工具，并满足先读后写的顺序。"
          status="已接入"
          tone="ok"
        />
        <FeatureCard
          icon={ShieldCheck}
          title="Policy 安全门禁"
          description="检查写操作是否经过 AgentPolicy、allow_write 和幂等键约束。"
          status="安全项"
          tone="ok"
        />
        <FeatureCard
          icon={BarChart3}
          title="可归档报告"
          description="运行后写入 storage/reports/evaluation，支持答辩和回归对比。"
          status={latest?.exists ? "有报告" : "待生成"}
          tone={latest?.exists ? "ok" : "warn"}
        />
      </section>
      <form className="toolbar" onSubmit={run}>
        <select value={caseId} onChange={(event) => setCaseId(event.target.value)}>
          <option value="">全部 case</option>
          <option value="m3_evidence_first_plan">m3_evidence_first_plan</option>
          <option value="m4_owner_missing_needs_confirmation">m4_owner_missing_needs_confirmation</option>
          <option value="policy_blocks_unconfirmed_write">policy_blocks_unconfirmed_write</option>
        </select>
        <button className="button" disabled={running}>
          <Play size={16} />
          {running ? "评测中" : "运行评测"}
        </button>
      </form>
      <div className="metric-grid">
        <MetricCard
          label="Score"
          value={report?.score ?? "-"}
          helper="所有 case 的平均分，低于 0.95 时不建议真实发布。"
          icon={BarChart3}
          tone={(report?.score ?? 0) >= 0.95 ? "ok" : "warn"}
        />
        <MetricCard
          label="Safety"
          value={report?.safety_score ?? "-"}
          helper="敏感信息泄露扫描，必须保持 1.0。"
          icon={ShieldCheck}
          tone={(report?.safety_score ?? 0) === 1 ? "ok" : "danger"}
        />
        <MetricCard
          label="Cases"
          value={report ? `${report.passed_cases}/${report.total_cases}` : "-"}
          helper="通过 case / 总 case。"
          icon={CheckCircle2}
        />
        <MetricCard label="Provider" value={report?.provider || "scripted_debug"} detail={latest?.path || ""} helper="当前建议使用 scripted_debug 作为稳定基线。" />
      </div>
      <section className="panel">
        <div className="panel__header">
          <div>
            <h2>Case 结果</h2>
            <p>每条 case 都代表一个业务约束：M3 先取证再发卡、M4 缺字段需确认、未授权写操作要被拦截。</p>
          </div>
        </div>
        <DataTable
          rows={report?.results ?? []}
          empty="暂无评测结果"
          emptyHint="点击“运行评测”生成最新 agent_trajectory 报告。"
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
            <div>
              <h2>指标明细</h2>
              <p>用于定位具体是工具调用、顺序、Policy 还是幂等覆盖出了问题。</p>
            </div>
          </div>
          <JsonPreview value={report.results} maxHeight={420} />
        </section>
      ) : null}
    </div>
  );
}
