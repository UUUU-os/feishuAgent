type StatusBadgeProps = {
  status: string;
  tone?: "ok" | "warn" | "danger" | "muted";
};

export function StatusBadge({ status, tone }: StatusBadgeProps) {
  const resolvedTone = tone ?? inferTone(status);
  return <span className={`status-badge status-badge--${resolvedTone}`}>{status || "-"}</span>;
}

function inferTone(status: string): "ok" | "warn" | "danger" | "muted" {
  const normalized = status.toLowerCase();
  if (["success", "succeeded", "ok", "passed", "allow", "active"].includes(normalized)) return "ok";
  if (["pending", "retrying", "running", "needs_confirmation"].includes(normalized)) return "warn";
  if (["failed", "dead_letter", "blocked", "error"].includes(normalized)) return "danger";
  return "muted";
}
