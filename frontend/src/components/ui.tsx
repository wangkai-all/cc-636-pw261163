import type { ReactNode } from "react";

export type Tone = "good" | "warn" | "bad" | "muted" | "info" | "accent";

export function Badge({
  tone = "muted",
  children,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = "",
  id,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`panel ${className}`} id={id}>
      <header className="panel-head">
        <div className="panel-heading">
          <h2>{title}</h2>
          {subtitle ? <p className="panel-subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function Callout({
  tone = "info",
  title,
  children,
  icon,
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className={`callout callout-${tone}`}>
      {icon ? <span className="callout-icon">{icon}</span> : null}
      <div className="callout-body">
        {title ? <strong className="callout-title">{title}</strong> : null}
        {children ? <div className="callout-text">{children}</div> : null}
      </div>
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint ? <span className="stat-hint">{hint}</span> : null}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="spinner-wrap" role="status">
      <span className="spinner" aria-hidden="true" />
      {label ? <span>{label}</span> : null}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function KeyValue({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="kv-grid">
      {items.map((item) => (
        <div className="kv" key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Collapse({
  summary,
  children,
  open = false,
  count,
}: {
  summary: ReactNode;
  children: ReactNode;
  open?: boolean;
  count?: number;
}) {
  return (
    <details className="collapse" open={open}>
      <summary>
        <span>{summary}</span>
        {typeof count === "number" ? <span className="collapse-count">{count}</span> : null}
      </summary>
      <div className="collapse-body">{children}</div>
    </details>
  );
}
