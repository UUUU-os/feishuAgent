import { ArrowUpRight } from "lucide-react";
import type { LucideIcon } from "lucide-react";

type MetricCardProps = {
  label: string;
  value: string | number;
  detail?: string;
  helper?: string;
  icon?: LucideIcon;
  tone?: "ok" | "warn" | "danger" | "neutral";
};

export function MetricCard({ label, value, detail, helper, icon: Icon, tone = "neutral" }: MetricCardProps) {
  return (
    <section className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__label">
        <span>{label}</span>
        {Icon ? <Icon size={16} aria-hidden="true" /> : <ArrowUpRight size={15} aria-hidden="true" />}
      </div>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
      {helper ? <p>{helper}</p> : null}
    </section>
  );
}
