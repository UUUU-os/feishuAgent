export type ApiResponse<T> = {
  ok: boolean;
  data: T;
  error: string;
};

export type HealthStatus = {
  app: {
    name: string;
    env: string;
    timezone: string;
  };
  storage: {
    db_path: string;
    db_exists: boolean;
    reports_dir: string;
    reports_dir_exists: boolean;
  };
  migration: {
    ok: boolean;
    error: string;
  };
  evaluation_latest_exists: boolean;
};

export type LatestReport<T = Record<string, unknown>> = {
  exists: boolean;
  path: string;
  mtime?: number;
  error?: string;
  data: T;
};

export type EvaluationMetric = {
  name: string;
  score: number;
  passed: boolean;
  expected?: unknown;
  actual?: unknown;
  reason?: string;
};

export type EvaluationCaseResult = {
  case_id: string;
  score: number;
  passed: boolean;
  metrics: EvaluationMetric[];
  trace_summary: {
    workflow_type: string;
    status: string;
    tool_calls: string[];
    policy_statuses: string[];
  };
};

export type EvaluationReport = {
  suite: string;
  provider: string;
  total_cases: number;
  passed_cases: number;
  score: number;
  safety_score: number;
  generated_at: number;
  results: EvaluationCaseResult[];
  report_path?: string;
  passed_threshold?: boolean;
  fail_under?: number;
};

export type JobRow = {
  job_id: string;
  queue_name: string;
  job_type: string;
  status: string;
  priority: number;
  idempotency_key: string;
  attempts: number;
  max_attempts: number;
  available_at: number;
  locked_by: string;
  locked_until: number;
  last_error: string;
  created_at: number;
  updated_at: number;
};

export type JobsResult = {
  items: JobRow[];
  limit: number;
  status: string;
  queue_name: string;
};

export type DashboardData = {
  health: HealthStatus;
  evaluation: LatestReport<EvaluationReport>;
  m3: LatestReport<Record<string, unknown>>;
  m4: LatestReport<Record<string, unknown>>;
  job_status_counts: Record<string, number>;
  recent_jobs: JobsResult;
};

export type M3SendCardRequest = {
  date: string;
  event_title: string;
  event_id: string;
  llm_provider: string;
  project_id: string;
  allow_write: boolean;
  write_report: boolean;
  force_index: boolean;
  idempotency_suffix: string;
};

export type M3SendCardResult = {
  ok: boolean;
  returncode: number;
  dry_run: boolean;
  command: string[];
  idempotency_suffix: string;
  stdout: string;
  parsed: {
    trace_id: string;
    workflow_type: string;
    status: string;
    report_markdown: string;
    report_json: string;
  };
};

export type MigrationStatus = {
  status: {
    db_path: string;
    applied_count: number;
    pending_count: number;
    applied: Array<Record<string, unknown>>;
    pending: Array<Record<string, unknown>>;
  };
  verify: {
    ok: boolean;
    error: string;
  };
};

export type WorkerRunResult = {
  ok: boolean;
  returncode: number;
  command: string[];
  stdout: string;
};
