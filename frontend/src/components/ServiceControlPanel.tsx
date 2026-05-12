import { FileText, Play, RefreshCw, Square } from "lucide-react";
import type { ManagedServiceStatus } from "../api/types";
import { DataTable } from "./DataTable";
import { StatusBadge } from "./StatusBadge";

type ServiceControlPanelProps = {
  services: ManagedServiceStatus[];
  loading: boolean;
  onRefresh: () => void;
  onStart: (name: string, profile: string) => void;
  onStop: (name: string) => void;
  onViewLogs: (name: string) => void;
};

const serviceLabels: Record<string, string> = {
  worker: "Worker",
  sdk_callback: "SDK 回调",
  m4_callback: "M4 按钮回调"
};

export function ServiceControlPanel({
  services,
  loading,
  onRefresh,
  onStart,
  onStop,
  onViewLogs
}: ServiceControlPanelProps) {
  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <h2>服务控制</h2>
          <p>长期进程由 Console 后端按白名单启动，前端只传服务名和 profile。</p>
        </div>
        <button className="button button--secondary" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={16} />
          {loading ? "刷新中" : "刷新"}
        </button>
      </div>
      <DataTable
        rows={services}
        empty="暂无服务状态"
        emptyHint="请确认 Console API 已启动。"
        columns={[
          {
            key: "name",
            header: "Service",
            render: (row) => (
              <span>
                <strong>{serviceLabels[row.name] || row.name}</strong>
                <small className="muted-text">{row.profile}</small>
              </span>
            )
          },
          { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
          { key: "pid", header: "PID", render: (row) => row.pid || "-" },
          { key: "log", header: "Log", render: (row) => <code>{row.log_path || "-"}</code> },
          {
            key: "actions",
            header: "Actions",
            render: (row) => (
              <div className="table-actions">
                <button className="icon-button" onClick={() => onStart(row.name, row.profile || "default")} title="启动">
                  <Play size={15} />
                </button>
                <button className="icon-button" onClick={() => onStop(row.name)} title="停止">
                  <Square size={15} />
                </button>
                <button className="icon-button" onClick={() => onViewLogs(row.name)} title="查看日志">
                  <FileText size={15} />
                </button>
              </div>
            )
          }
        ]}
      />
    </section>
  );
}
