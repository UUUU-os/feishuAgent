import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { StatusBadge } from "./StatusBadge";

type FeatureCardProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  status: string;
  children?: ReactNode;
  action?: ReactNode;
  secondary?: ReactNode;
  tone?: "ok" | "warn" | "danger" | "muted";
};

export function FeatureCard({
  icon: Icon,
  title,
  description,
  status,
  children,
  action,
  secondary,
  tone = "muted"
}: FeatureCardProps) {
  return (
    <section className="feature-card">
      <div className={`feature-card__icon feature-card__icon--${tone}`}>
        <Icon size={20} />
      </div>
      <div className="feature-card__body">
        <div className="feature-card__title">
          <h3>{title}</h3>
          <StatusBadge status={status} tone={tone} />
        </div>
        <p>{description}</p>
        {children ? <div className="feature-card__content">{children}</div> : null}
        {(action || secondary) ? (
          <div className="feature-card__actions">
            {action}
            {secondary}
          </div>
        ) : null}
      </div>
    </section>
  );
}
