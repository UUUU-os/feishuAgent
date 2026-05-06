import type {
  ApiResponse,
  DashboardData,
  EvaluationReport,
  HealthStatus,
  JobsResult,
  LatestReport,
  M3SendCardRequest,
  M3SendCardResult,
  MigrationStatus,
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
    })
};
