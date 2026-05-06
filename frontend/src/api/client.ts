import type {
  ApiResponse,
  CommandRunResult,
  DashboardData,
  EvaluationReport,
  HealthStatus,
  JobsResult,
  LatestReport,
  M3SendCardRequest,
  M3SendCardResult,
  M4ReadMinuteRequest,
  M4SendCardsRequest,
  M5RiskScanRequest,
  ManagedServiceStatus,
  MigrationStatus,
  RecordsResult,
  ServiceLogsResult,
  ServicesResult,
  WorkerRunResult
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  const payload = (await response.json()) as ApiResponse<T>;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload.data;
}

export const consoleApi = {
  health: () => request<HealthStatus>("/api/health"),
  dashboard: () => request<DashboardData>("/api/dashboard"),
  jobs: (params: { limit?: number; status?: string; queue_name?: string } = {}) => {
    const search = new URLSearchParams();
    if (params.limit) search.set("limit", String(params.limit));
    if (params.status) search.set("status", params.status);
    if (params.queue_name) search.set("queue_name", params.queue_name);
    return request<JobsResult>(`/api/jobs?${search.toString()}`);
  },
  latestReport: (type: string) => request<LatestReport>(`/api/reports/latest?type=${encodeURIComponent(type)}`),
  migrationStatus: () => request<MigrationStatus>("/api/migrations/status"),
  runEvaluation: (body: {
    suite: string;
    case_id: string;
    provider: string;
    fail_under: number;
    write_report: boolean;
  }) =>
    request<EvaluationReport>("/api/evaluation/run", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  sendM3Card: (body: M3SendCardRequest) =>
    request<M3SendCardResult>("/api/m3/send-card", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  runWorkerOnce: () =>
    request<WorkerRunResult>("/api/worker/run-once", {
      method: "POST",
      body: JSON.stringify({ dry_run: true })
    }),
  services: () => request<ServicesResult>("/api/services"),
  serviceLogs: (name: string, tail = 200) =>
    request<ServiceLogsResult>(`/api/services/logs?name=${encodeURIComponent(name)}&tail=${tail}`),
  startService: (body: { name: string; profile: string; force_restart?: boolean }) =>
    request<ManagedServiceStatus>("/api/services/start", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  stopService: (body: { name: string }) =>
    request<ManagedServiceStatus>("/api/services/stop", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  readM4Minute: (body: M4ReadMinuteRequest) =>
    request<CommandRunResult>("/api/m4/read-minute", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  sendM4Cards: (body: M4SendCardsRequest) =>
    request<CommandRunResult>("/api/m4/send-cards", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  runM5RiskScan: (body: M5RiskScanRequest) =>
    request<CommandRunResult>("/api/m5/risk-scan", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  reviewSessions: (limit = 20) => request<RecordsResult>(`/api/m4/review-sessions?limit=${limit}`),
  pendingActions: (limit = 20) => request<RecordsResult>(`/api/m4/pending-actions?limit=${limit}`),
  taskMappings: (limit = 20) => request<RecordsResult>(`/api/m4/task-mappings?limit=${limit}`),
  riskNotifications: (limit = 20) => request<RecordsResult>(`/api/m5/risk-notifications?limit=${limit}`)
};
