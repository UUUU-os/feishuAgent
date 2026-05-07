import { AlertTriangle, CheckCircle2, FileText, Play, Send } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { consoleApi } from "../api/client";
import type { M3SendCardRequest, M3SendCardResult } from "../api/types";
import { ConfirmWriteDialog } from "../components/ConfirmWriteDialog";
import { JsonPreview } from "../components/JsonPreview";
import { PageHeader } from "../components/PageHeader";
import { StepList } from "../components/StepList";
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
      <PageHeader
        eyebrow="M3 Pre-meeting"
        title="会前背景卡"
        description="从飞书日历定位会议，触发知识检索和受控发卡。默认 dry-run，开启 allow_write 后才会真实发送飞书卡片。"
        meta={
          <>
            <StatusBadge status={form.allow_write ? "真实写入" : "Dry-run"} tone={form.allow_write ? "danger" : "warn"} />
            <span>幂等后缀：{finalSuffix}</span>
          </>
        }
      />
      {error ? (
        <div className="alert alert--danger">
          M3 执行失败：{error}。请确认日期窗口内存在测试会议，或改用 event_id 精确定位。
        </div>
      ) : null}
      <div className="workflow-layout">
        <section className="panel panel--sticky">
          <div className="panel__header panel__header--stack">
            <h2>执行步骤</h2>
            <p>每次发卡都应先确认会议窗口和写入开关。</p>
          </div>
          <StepList
            steps={[
              { title: "配置参数", description: "选择日期、标题或 event_id", state: "active" },
              { title: "连接飞书", description: "后端使用 user 身份读取日历", state: result ? "done" : "pending" },
              {
                title: form.allow_write ? "真实发卡" : "Dry-run",
                description: form.allow_write ? "会发送到测试群" : "只打印下游命令",
                state: form.allow_write ? "danger" : "pending"
              },
              { title: "查看结果", description: "确认 trace_id、报告和 stdout", state: result ? "done" : "pending" }
            ]}
          />
          <div className="callout callout--warn">
            <AlertTriangle size={16} />
            <span>如果提示没有会议，通常是 `--date` 指向的日期没有匹配标题的飞书日程。</span>
          </div>
        </section>
        <form className="form-panel form-panel--wide" onSubmit={submit}>
          <label>
            日期窗口
            <select value={form.date} onChange={(event) => setForm({ ...form, date: event.target.value })}>
              <option value="today">today：今天本地整天</option>
              <option value="tomorrow">tomorrow：明天本地整天</option>
            </select>
            <small>也可以在 Console API 中传 YYYY-MM-DD；当前页面保留常用日期。</small>
          </label>
          <label>
            会议标题
            <input
              value={form.event_title}
              onChange={(event) => setForm({ ...form, event_title: event.target.value })}
              placeholder="例如：MeetFlow 测试会议"
            />
            <small>按标题包含匹配。找不到时请检查日期或改用 event_id。</small>
          </label>
          <label>
            Event ID
            <input
              value={form.event_id}
              onChange={(event) => setForm({ ...form, event_id: event.target.value })}
              placeholder="可选：精确指定飞书 event_id"
            />
            <small>传入 event_id 后可以避免标题重名。</small>
          </label>
          <label>
            LLM Provider
            <select
              value={form.llm_provider}
              onChange={(event) => setForm({ ...form, llm_provider: event.target.value })}
            >
              <option value="scripted_debug">scripted_debug：推荐联调</option>
              <option value="dry-run">dry-run：只验证链路</option>
              <option value="configured">configured：使用配置 provider</option>
              <option value="deepseek">deepseek：真实模型</option>
            </select>
            <small>默认 scripted_debug，避免真实模型接收飞书内容。</small>
          </label>
          <label>
            Project ID
            <input value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })} />
            <small>用于读取项目记忆和报告归属。</small>
          </label>
          <label>
            Idempotency Suffix
            <input
              value={form.idempotency_suffix}
              onChange={(event) => setForm({ ...form, idempotency_suffix: event.target.value })}
              placeholder={finalSuffix}
            />
            <small>重复真实发送同一会议时请使用唯一后缀。</small>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={form.write_report}
              onChange={(event) => setForm({ ...form, write_report: event.target.checked })}
            />
            <span>
              写入报告
              <small>生成 storage/reports/m3 下的 JSON/Markdown。</small>
            </span>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={form.force_index}
              onChange={(event) => setForm({ ...form, force_index: event.target.checked })}
            />
            <span>
              重建索引
              <small>重新处理补充资源，耗时会更长。</small>
            </span>
          </label>
          <label className="check-row check-row--danger">
            <input
              type="checkbox"
              checked={form.allow_write}
              onChange={(event) => setForm({ ...form, allow_write: event.target.checked })}
            />
            <span>
              允许真实发卡
              <small>开启后会触发飞书写操作，提交前需要二次确认。</small>
            </span>
          </label>
          <div className="form-panel__actions">
            <button className={form.allow_write ? "button button--danger" : "button"} disabled={running}>
              {form.allow_write ? <Send size={16} /> : <Play size={16} />}
              {running ? "执行中" : form.allow_write ? "确认并发卡" : "运行 Dry-run"}
            </button>
          </div>
        </form>
      </div>
      {result ? (
        <section className="panel">
          <div className="panel__header">
            <div>
              <h2>运行结果</h2>
              <p>{result.dry_run ? "Dry-run 已完成，未发送飞书卡片。" : "真实发卡请求已返回，请核对报告和飞书消息。"}</p>
            </div>
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
          {result.ok ? (
            <div className="callout callout--ok">
              <CheckCircle2 size={16} />
              <span>命令返回成功。下一步可以打开报告文件或在飞书测试群检查卡片。</span>
            </div>
          ) : null}
          {result.parsed.report_json ? (
            <div className="callout">
              <FileText size={16} />
              <span>{result.parsed.report_json}</span>
            </div>
          ) : null}
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
