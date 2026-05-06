import { Play, Send } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { consoleApi } from "../api/client";
import type { M3SendCardRequest, M3SendCardResult } from "../api/types";
import { ConfirmWriteDialog } from "../components/ConfirmWriteDialog";
import { JsonPreview } from "../components/JsonPreview";
import { StatusBadge } from "../components/StatusBadge";

const initialForm: M3SendCardRequest = {
  date: "tomorrow",
  event_title: "MeetFlow 测试会议",
  event_id: "",
  llm_provider: "scripted_debug",
  project_id: "meetflow",
  allow_write: false,
  write_report: true,
  force_index: false,
  idempotency_suffix: ""
};

export function M3ConsolePage() {
  const [form, setForm] = useState<M3SendCardRequest>(initialForm);
  const [result, setResult] = useState<M3SendCardResult | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const finalSuffix = useMemo(() => form.idempotency_suffix || makeSuffix(), [form.idempotency_suffix]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (form.allow_write) {
      setConfirmOpen(true);
      return;
    }
    void run();
  };

  const run = async () => {
    setRunning(true);
    setError("");
    setConfirmOpen(false);
    try {
      setResult(await consoleApi.sendM3Card({ ...form, idempotency_suffix: finalSuffix }));
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
          <h1>M3 会前发卡</h1>
          <p>选择会议并触发会前背景卡链路</p>
        </div>
      </div>
      {error ? <div className="alert alert--danger">{error}</div> : null}
      <form className="form-panel" onSubmit={submit}>
        <label>
          日期
          <select value={form.date} onChange={(event) => setForm({ ...form, date: event.target.value })}>
            <option value="today">today</option>
            <option value="tomorrow">tomorrow</option>
          </select>
        </label>
        <label>
          会议标题
          <input
            value={form.event_title}
            onChange={(event) => setForm({ ...form, event_title: event.target.value })}
            placeholder="MeetFlow 测试会议"
          />
        </label>
        <label>
          Event ID
          <input value={form.event_id} onChange={(event) => setForm({ ...form, event_id: event.target.value })} />
        </label>
        <label>
          LLM Provider
          <select
            value={form.llm_provider}
            onChange={(event) => setForm({ ...form, llm_provider: event.target.value })}
          >
            <option value="scripted_debug">scripted_debug</option>
            <option value="dry-run">dry-run</option>
            <option value="configured">configured</option>
            <option value="deepseek">deepseek</option>
          </select>
        </label>
        <label>
          Project ID
          <input value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })} />
        </label>
        <label>
          Idempotency Suffix
          <input
            value={form.idempotency_suffix}
            onChange={(event) => setForm({ ...form, idempotency_suffix: event.target.value })}
            placeholder={finalSuffix}
          />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={form.write_report}
            onChange={(event) => setForm({ ...form, write_report: event.target.checked })}
          />
          写入报告
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={form.force_index}
            onChange={(event) => setForm({ ...form, force_index: event.target.checked })}
          />
          重建索引
        </label>
        <label className="check-row check-row--danger">
          <input
            type="checkbox"
            checked={form.allow_write}
            onChange={(event) => setForm({ ...form, allow_write: event.target.checked })}
          />
          允许真实发卡
        </label>
        <div className="form-panel__actions">
          <button className={form.allow_write ? "button button--danger" : "button"} disabled={running}>
            {form.allow_write ? <Send size={16} /> : <Play size={16} />}
            {form.allow_write ? "发卡" : "Dry Run"}
          </button>
        </div>
      </form>
      {result ? (
        <section className="panel">
          <div className="panel__header">
            <h2>运行结果</h2>
            <StatusBadge status={result.parsed.status || (result.ok ? "success" : "failed")} />
          </div>
          <div className="summary-grid">
            <div>
              <span>Trace</span>
              <code>{result.parsed.trace_id || "-"}</code>
            </div>
            <div>
              <span>Workflow</span>
              <code>{result.parsed.workflow_type || "-"}</code>
            </div>
            <div>
              <span>Report</span>
              <code>{result.parsed.report_json || "-"}</code>
            </div>
          </div>
          <JsonPreview value={result.stdout} maxHeight={360} />
        </section>
      ) : null}
      <ConfirmWriteDialog
        open={confirmOpen}
        title="确认真实发卡"
        details={[`会议：${form.event_title || form.event_id}`, `日期：${form.date}`, `Provider：${form.llm_provider}`]}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => void run()}
      />
    </div>
  );
}

function makeSuffix() {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `m3-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(
    now.getMinutes()
  )}${pad(now.getSeconds())}`;
}
