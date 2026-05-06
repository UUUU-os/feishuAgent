import { ArrowUpRight } from "lucide-react";

type MetricCardProps = {
  label: string;
  value: string | number;
  detail?: string;
  tone?: "ok" | "warn" | "danger" | "neutral";
};

export function MetricCard({ label, value, detail, tone = "neutral" }: MetricCardProps) {
  return (
    <section className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__label">
        <span>{label}</span>
        <ArrowUpRight size={15} aria-hidden="true" />
      </div>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </section>
  );
}
