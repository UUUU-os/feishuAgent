import { AlertTriangle, ClipboardList, Play, RefreshCw, Send, ShieldAlert } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { consoleApi } from "../api/client";
import type {
  CommandRunResult,
  M4ReadMinuteRequest,
  M4SendCardsRequest,
  M5RiskScanRequest,
  RecordsResult,
  ServiceLogsResult,
  ServicesResult
} from "../api/types";
import { CommandResultPanel } from "../components/CommandResultPanel";
import { ConfirmWriteDialog } from "../components/ConfirmWriteDialog";
import { DataTable } from "../components/DataTable";
import { JsonPreview } from "../components/JsonPreview";
import { PageHeader } from "../components/PageHeader";
import { ServiceControlPanel } from "../components/ServiceControlPanel";
import { StatusBadge } from "../components/StatusBadge";

const initialM4Form: M4SendCardsRequest = {
  minute: "",
  identity: "user",
  chat_id: "",
  receive_id_type: "chat_id",
  content_limit: 300,
  related_top_n: 5,
  skip_related_knowledge: false,
  show_card_json: false,
  allow_write: false,
  timeout_seconds: 180
};

const initialM5Form: M5RiskScanRequest = {
  backend: "local",
  mode: "direct",
  chat_id: "",
  identity: "user",
  send_identity: "tenant",
  completed: "false",
  page_size: 50,
  page_limit: 20,
  stale_update_days: 0,
  due_soon_hours: 0,
  max_reminders: 0,
  show_card: true,
  allow_write: false,
  timeout_seconds: 180
};

type ConfirmTarget = "m4" | "m5" | null;

export function LiveFlowPage() {
  const [services, setServices] = useState<ServicesResult | null>(null);
  const [serviceLogs, setServiceLogs] = useState<ServiceLogsResult | null>(null);
  const [m4Form, setM4Form] = useState<M4SendCardsRequest>(initialM4Form);
  const [m5Form, setM5Form] = useState<M5RiskScanRequest>(initialM5Form);
  const [m4Result, setM4Result] = useState<CommandRunResult | null>(null);
  const [m5Result, setM5Result] = useState<CommandRunResult | null>(null);
  const [reviewSessions, setReviewSessions] = useState<RecordsResult | null>(null);
  const [taskMappings, setTaskMappings] = useState<RecordsResult | null>(null);
  const [riskNotifications, setRiskNotifications] = useState<RecordsResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<ConfirmTarget>(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [serviceResult, reviewResult, mappingResult, riskResult] = await Promise.all([
        consoleApi.services(),
        consoleApi.reviewSessions(10),
        consoleApi.taskMappings(10),
        consoleApi.riskNotifications(10)
      ]);
      setServices(serviceResult);
      setReviewSessions(reviewResult);
      setTaskMappings(mappingResult);
      setRiskNotifications(riskResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const startService = async (name: string, profile: string) => {
    setRunning(`start:${name}`);
    setError("");
    try {
      await consoleApi.startService({ name, profile });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning("");
    }
  };

  const stopService = async (name: string) => {
    setRunning(`stop:${name}`);
    setError("");
    try {
      await consoleApi.stopService({ name });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning("");
    }
  };

  const viewLogs = async (name: string) => {
    setRunning(`logs:${name}`);
    setError("");
    try {
      setServiceLogs(await consoleApi.serviceLogs(name, 240));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning("");
    }
  };

  const readM4Minute = async () => {
    setRunning("m4-read");
    setError("");
    try {
      const body: M4ReadMinuteRequest = {
        minute: m4Form.minute,
        identity: m4Form.identity,
        content_limit: Math.max(m4Form.content_limit, 800),
        show_card_json: m4Form.show_card_json,
        timeout_seconds: m4Form.timeout_seconds
      };
      setM4Result(await consoleApi.readM4Minute(body));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning("");
    }
  };

  const runM4 = async () => {
    setRunning("m4-send");
    setConfirmTarget(null);
    setError("");
    try {
      setM4Result(await consoleApi.sendM4Cards(m4Form));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning("");
    }
  };

  const runM5 = async () => {
    setRunning("m5");
    setConfirmTarget(null);
    setError("");
    try {
      setM5Result(await consoleApi.runM5RiskScan(m5Form));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning("");
    }
  };

  const submitM4 = (event: FormEvent) => {
    event.preventDefault();
    if (m4Form.allow_write) {
      setConfirmTarget("m4");
      return;
    }
    void runM4();
  };

  const submitM5 = (event: FormEvent) => {
    event.preventDefault();
    if (m5Form.allow_write) {
      setConfirmTarget("m5");
      return;
    }
    void runM5();
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="Live Flow"
        title="真实联调"
        description="把 M4 会后总结、待确认任务卡、M5 风险巡检和长期服务控制收敛到一个本地控制台。"
        meta={
          <>
            <StatusBadge status="白名单命令" tone="ok" />
            <span>真实飞书写入必须二次确认</span>
          </>
        }
        actions={
          <button className="button button--secondary" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={16} />
            {loading ? "刷新中" : "刷新状态"}
          </button>
        }
      />
      {error ? <div className="alert alert--danger">真实联调失败：{error}</div> : null}
      <ServiceControlPanel
        services={services?.items ?? []}
        loading={loading || Boolean(running.startsWith("start") || running.startsWith("stop"))}
        onRefresh={() => void load()}
        onStart={(name, profile) => void startService(name, profile)}
        onStop={(name) => void stopService(name)}
        onViewLogs={(name) => void viewLogs(name)}
      />
      {serviceLogs ? (
        <section className="panel">
          <div className="panel__header">
            <div>
              <h2>服务日志</h2>
              <p>{serviceLogs.log_path}</p>
            </div>
            <StatusBadge status={serviceLogs.name} />
          </div>
          <JsonPreview value={serviceLogs.content || "暂无日志"} maxHeight={360} />
        </section>
      ) : null}
      <div className="live-grid">
        <form className="form-panel form-panel--live" onSubmit={submitM4}>
          <div className="form-section-title">
            <ClipboardList size={18} />
            <span>M4 会后总结</span>
          </div>
          <label className="form-field--wide">
            飞书妙记链接
            <input
              value={m4Form.minute}
              onChange={(event) => setM4Form({ ...m4Form, minute: event.target.value })}
              placeholder="https://xxx.feishu.cn/minutes/xxx"
            />
            <small>只读解析和真实发卡都需要填写。</small>
          </label>
          <label>
            Chat ID
            <input
              value={m4Form.chat_id}
              onChange={(event) => setM4Form({ ...m4Form, chat_id: event.target.value })}
              placeholder="可选：不填使用默认测试群"
            />
          </label>
          <label>
            Identity
            <select value={m4Form.identity} onChange={(event) => setM4Form({ ...m4Form, identity: event.target.value })}>
              <option value="user">user：读取妙记</option>
              <option value="tenant">tenant：应用身份</option>
            </select>
          </label>
          <label>
            Content Limit
            <input
              type="number"
              min={100}
              max={5000}
              value={m4Form.content_limit}
              onChange={(event) => setM4Form({ ...m4Form, content_limit: Number(event.target.value) })}
            />
          </label>
          <label>
            Related Top N
            <input
              type="number"
              min={1}
              max={8}
              value={m4Form.related_top_n}
              onChange={(event) => setM4Form({ ...m4Form, related_top_n: Number(event.target.value) })}
            />
          </label>
          <label>
            Timeout
            <input
              type="number"
              min={10}
              max={600}
              value={m4Form.timeout_seconds}
              onChange={(event) => setM4Form({ ...m4Form, timeout_seconds: Number(event.target.value) })}
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={m4Form.skip_related_knowledge}
              onChange={(event) => setM4Form({ ...m4Form, skip_related_knowledge: event.target.checked })}
            />
            <span>跳过相关知识召回</span>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={m4Form.show_card_json}
              onChange={(event) => setM4Form({ ...m4Form, show_card_json: event.target.checked })}
            />
            <span>展示卡片 JSON</span>
          </label>
          <label className="check-row check-row--danger">
            <input
              type="checkbox"
              checked={m4Form.allow_write}
              onChange={(event) => setM4Form({ ...m4Form, allow_write: event.target.checked })}
            />
            <span>允许真实发送 M4 卡片</span>
          </label>
          <div className="form-panel__actions form-field--wide">
            <button type="button" className="button button--secondary" onClick={() => void readM4Minute()} disabled={running === "m4-read"}>
              <Play size={16} />
              {running === "m4-read" ? "解析中" : "只读解析妙记"}
            </button>
            <button className={m4Form.allow_write ? "button button--danger" : "button"} disabled={running === "m4-send"}>
              {m4Form.allow_write ? <Send size={16} /> : <Play size={16} />}
              {running === "m4-send" ? "执行中" : m4Form.allow_write ? "真实发送 M4" : "M4 Dry-run"}
            </button>
          </div>
        </form>
        <form className="form-panel form-panel--live" onSubmit={submitM5}>
          <div className="form-section-title">
            <ShieldAlert size={18} />
            <span>M5 风险巡检</span>
          </div>
          <label>
            Backend
            <select value={m5Form.backend} onChange={(event) => setM5Form({ ...m5Form, backend: event.target.value })}>
              <option value="local">local：本地样本</option>
              <option value="feishu">feishu：真实任务</option>
            </select>
          </label>
          <label>
            Mode
            <select value={m5Form.mode} onChange={(event) => setM5Form({ ...m5Form, mode: event.target.value })}>
              <option value="direct">direct：直接执行</option>
              <option value="enqueue">enqueue：只入队</option>
            </select>
          </label>
          <label>
            Chat ID
            <input
              value={m5Form.chat_id}
              onChange={(event) => setM5Form({ ...m5Form, chat_id: event.target.value })}
              placeholder="可选：不填使用默认测试群"
            />
          </label>
          <label>
            Completed
            <select value={m5Form.completed} onChange={(event) => setM5Form({ ...m5Form, completed: event.target.value })}>
              <option value="false">未完成</option>
              <option value="true">已完成</option>
              <option value="all">全部</option>
            </select>
          </label>
          <label>
            Page Size
            <input
              type="number"
              min={1}
              max={100}
              value={m5Form.page_size}
              onChange={(event) => setM5Form({ ...m5Form, page_size: Number(event.target.value) })}
            />
          </label>
          <label>
            Page Limit
            <input
              type="number"
              min={1}
              max={100}
              value={m5Form.page_limit}
              onChange={(event) => setM5Form({ ...m5Form, page_limit: Number(event.target.value) })}
            />
          </label>
          <label>
            Stale Days
            <input
              type="number"
              min={0}
              value={m5Form.stale_update_days}
              onChange={(event) => setM5Form({ ...m5Form, stale_update_days: Number(event.target.value) })}
            />
          </label>
          <label>
            Due Soon Hours
            <input
              type="number"
              min={0}
              value={m5Form.due_soon_hours}
              onChange={(event) => setM5Form({ ...m5Form, due_soon_hours: Number(event.target.value) })}
            />
          </label>
          <label>
            Timeout
            <input
              type="number"
              min={10}
              max={600}
              value={m5Form.timeout_seconds}
              onChange={(event) => setM5Form({ ...m5Form, timeout_seconds: Number(event.target.value) })}
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={m5Form.show_card}
              onChange={(event) => setM5Form({ ...m5Form, show_card: event.target.checked })}
            />
            <span>展示风险卡片 JSON</span>
          </label>
          <label className="check-row check-row--danger">
            <input
              type="checkbox"
              checked={m5Form.allow_write}
              onChange={(event) => setM5Form({ ...m5Form, allow_write: event.target.checked })}
            />
            <span>允许真实发送风险提醒</span>
          </label>
          <div className="form-panel__actions form-field--wide">
            <button className={m5Form.allow_write ? "button button--danger" : "button"} disabled={running === "m5"}>
              {m5Form.allow_write ? <Send size={16} /> : <Play size={16} />}
              {running === "m5" ? "执行中" : m5Form.allow_write ? "真实执行 M5" : "运行 M5"}
            </button>
          </div>
        </form>
      </div>
      <CommandResultPanel title="M4 运行结果" result={m4Result} />
      <CommandResultPanel title="M5 运行结果" result={m5Result} />
      <section className="panel">
        <div className="panel__header">
          <div>
            <h2>最近业务状态</h2>
            <p>用于确认 M4 按钮闭环和 M5 风险提醒是否产生了可追踪记录。</p>
          </div>
          <div className="callout callout--warn">
            <AlertTriangle size={16} />
            <span>列表为空不代表失败，可能是还没有真实发卡或对应 migration 尚未产生数据。</span>
          </div>
        </div>
        <div className="status-tables">
          <SimpleRecordsTable title="Review Sessions" rows={reviewSessions?.items ?? []} keys={["review_session_id", "status", "minute_token", "updated_at"]} />
          <SimpleRecordsTable title="Task Mappings" rows={taskMappings?.items ?? []} keys={["item_id", "task_id", "meeting_id", "updated_at"]} />
          <SimpleRecordsTable title="Risk Notifications" rows={riskNotifications?.items ?? []} keys={["risk_key", "task_id", "status", "suppressed_until"]} />
        </div>
      </section>
      <ConfirmWriteDialog
        open={confirmTarget !== null}
        title={confirmTarget === "m4" ? "确认真实发送 M4 卡片" : "确认真实执行 M5 风险巡检"}
        details={
          confirmTarget === "m4"
            ? [`妙记：${m4Form.minute || "-"}`, `接收群：${m4Form.chat_id || "默认测试群"}`, `身份：${m4Form.identity}`]
            : [`Backend：${m5Form.backend}`, `接收群：${m5Form.chat_id || "默认测试群"}`, `发送身份：${m5Form.send_identity}`]
        }
        onCancel={() => setConfirmTarget(null)}
        onConfirm={() => (confirmTarget === "m4" ? void runM4() : void runM5())}
      />
    </div>
  );
}

type SimpleRecordsTableProps = {
  title: string;
  rows: Array<Record<string, unknown>>;
  keys: string[];
};

function SimpleRecordsTable({ title, rows, keys }: SimpleRecordsTableProps) {
  return (
    <div className="records-panel">
      <h3>{title}</h3>
      <DataTable
        rows={rows}
        empty="暂无记录"
        columns={keys.map((key) => ({
          key,
          header: key,
          render: (row) => <code>{String(row[key] ?? "-")}</code>
        }))}
      />
    </div>
  );
}
