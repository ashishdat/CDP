import type { ReactNode } from "react";
import { percent } from "./report";

export function MetricCard({
  label,
  value,
  tone = "default",
  hint,
}: {
  label: string;
  value: string;
  tone?: "default" | "good" | "danger";
  hint?: string;
}) {
  return (
    <article className={`metric-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </article>
  );
}

export function AccuracyBars({
  title,
  values,
}: {
  title: string;
  values: Record<string, number>;
}) {
  const entries = Object.entries(values).sort((a, b) => a[1] - b[1]);
  return (
    <section className="panel bars-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Accuracy breakdown</p>
          <h2>{title}</h2>
        </div>
        <span className="count">{entries.length} groups</span>
      </div>
      {entries.length === 0 ? (
        <Empty>No grouped results in this report.</Empty>
      ) : (
        <div className="bars">
          {entries.map(([label, value]) => (
            <div className="bar-row" key={label}>
              <span title={label}>{label.replaceAll("_", " ")}</span>
              <div className="bar-track">
                <div
                  className={value < 0.98 ? "bar-fill warning" : "bar-fill"}
                  style={{ width: `${Math.max(value * 100, 1)}%` }}
                />
              </div>
              <strong>{percent(value)}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
