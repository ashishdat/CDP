import { useEffect, useState } from "react";

export type ProductGateReport = {
  pass: boolean;
  claim_page_stp: number;
  claim_pages: number;
  true_stp: number;
  hitl: number;
  registration_failed: number;
  false_accepts: number | null;
  accepted_field_precision: number | null;
  fa_status: string;
  residual_counts: Record<string, number>;
  reasons: string[];
  targets: {
    claim_page_stp_min: number;
    accepted_field_precision_min: number;
    max_false_accepts: number;
  };
  generated_at?: string;
};

function pct(rate: number): string {
  return `${(rate * 100).toFixed(2)}%`;
}

export function ProductGatePanel({
  reportUrl = "/reports/product_gate.json",
}: {
  reportUrl?: string;
}) {
  const [report, setReport] = useState<ProductGateReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof fetch === "undefined") return;
    fetch(reportUrl)
      .then((response) => {
        if (!response.ok) throw new Error("Product gate report not found.");
        return response.json();
      })
      .then((payload) => setReport(payload as ProductGateReport))
      .catch((err: Error) => setError(err.message));
  }, [reportUrl]);

  if (error) {
    return (
      <section className="ops-panel product-gate-panel">
        <h3>Product gate (97% STP · FA=0)</h3>
        <p className="ops-stat-hint">{error} Run <code>make product-gate</code>.</p>
      </section>
    );
  }
  if (!report) {
    return (
      <section className="ops-panel product-gate-panel">
        <h3>Product gate (97% STP · FA=0)</h3>
        <p className="ops-stat-hint">Loading…</p>
      </section>
    );
  }

  const stpOk = report.claim_page_stp + 1e-9 >= report.targets.claim_page_stp_min;
  const faOk =
    report.fa_status === "SCORED" &&
    (report.false_accepts ?? 1) <= report.targets.max_false_accepts;

  return (
    <section className="ops-panel product-gate-panel">
      <div className="product-gate-header">
        <h3>Product gate (97% STP · FA=0)</h3>
        <span className={`product-gate-badge ${report.pass ? "pass" : "fail"}`}>
          {report.pass ? "PASS" : "FAIL"}
        </span>
      </div>
      <div className="ops-stat-grid">
        <div className="ops-stat">
          <span className="ops-stat-label">Claim-page STP</span>
          <strong className={`ops-stat-value ${stpOk ? "ok" : "bad"}`}>
            {pct(report.claim_page_stp)}
          </strong>
          <span className="ops-stat-hint">
            target ≥ {pct(report.targets.claim_page_stp_min)} · {report.true_stp}/
            {report.claim_pages}
          </span>
        </div>
        <div className="ops-stat">
          <span className="ops-stat-label">Accepted precision</span>
          <strong className={`ops-stat-value ${faOk ? "ok" : "bad"}`}>
            {report.accepted_field_precision == null
              ? report.fa_status
              : pct(report.accepted_field_precision)}
          </strong>
          <span className="ops-stat-hint">
            FA={report.false_accepts ?? "—"} (max {report.targets.max_false_accepts})
          </span>
        </div>
        <div className="ops-stat">
          <span className="ops-stat-label">HITL / REG</span>
          <strong className="ops-stat-value">
            {report.hitl} / {report.registration_failed}
          </strong>
          <span className="ops-stat-hint">
            {Object.entries(report.residual_counts || {})
              .map(([k, v]) => `${k}:${v}`)
              .join(" · ") || "no residuals"}
          </span>
        </div>
      </div>
      {report.reasons?.length ? (
        <ul className="product-gate-reasons">
          {report.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
