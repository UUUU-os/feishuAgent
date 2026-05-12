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
  m5?: LatestReport<Record<string, unknown>>;
  job_status_counts: Record<string, number>;
  recent_jobs: JobsResult;
};

export type M3SendCardRequest = {
  identity: string;
  calendar_id: string;
  date: string;
  event_title: string;
  event_id: string;
  llm_provider: string;
  project_id: string;
  doc: string;
  minute: string;
  max_iterations: number;
  allow_write: boolean;
  write_report: boolean;
  force_index: boolean;
  idempotency_suffix: string;
  report_dir: string;
  timeout_seconds: number;
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

export type CommandRunResult = {
  ok: boolean;
  returncode: number;
  dry_run: boolean;
  command: string[];
  stdout: string;
  stderr?: string;
  parsed: Record<string, unknown>;
  report_path?: string;
  job?: Record<string, unknown>;
};

export type ManagedServiceStatus = {
  name: string;
  profile: string;
  status: string;
  pid: number;
  started_at: number;
  command: string[];
  log_path: string;
  error: string;
};

export type ServicesResult = {
  items: ManagedServiceStatus[];
};

export type ServiceLogsResult = {
  name: string;
  log_path: string;
  content: string;
};

export type M4ReadMinuteRequest = {
  minute: string;
  identity: string;
  content_limit: number;
  show_card_json: boolean;
  timeout_seconds: number;
};

export type M4SendCardsRequest = {
  minute: string;
  identity: string;
  chat_id: string;
  receive_id_type: string;
  content_limit: number;
  related_top_n: number;
  skip_related_knowledge: boolean;
  show_card_json: boolean;
  allow_write: boolean;
  timeout_seconds: number;
};

export type M5RiskScanRequest = {
  backend: string;
  mode: string;
  chat_id: string;
  identity: string;
  send_identity: string;
  completed: string;
  page_size: number;
  page_limit: number;
  stale_update_days: number;
  due_soon_hours: number;
  max_reminders: number;
  show_card: boolean;
  allow_write: boolean;
  timeout_seconds: number;
};

export type RecordsResult = {
  items: Array<Record<string, unknown>>;
};
