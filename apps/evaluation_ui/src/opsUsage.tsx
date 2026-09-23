import { useEffect, useState } from "react";

export type OpsUsageReport = {
  cohort: string;
  run_dir: string;
  n: number;
  true_stp: number;
  true_stp_rate: number;
  hitl: number;
  hitl_rate: number;
  registration_failed: number;
  dispositions: Record<string, number>;
  median_elapsed_sec: number | null;
  azure_di: {
    api_calls: number;
    ok: number;
    fail: number;
    by_kind: Record<string, number>;
    by_field: Record<string, number>;
    claims_with_di_charge: number;
    claims_with_di_charge_rate: number;
  };
  vlm_tokens: {
    metered: boolean;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    by_provider_total_tokens: Record<string, number>;
    note: string | null;
  };
  cloud: {
    claims_with_claude_or_gpt_on_critical: number;
    claims_with_claude_or_gpt_rate: number;
    conflict_agent_attempts: number;
    conflict_agent_claims: number;
  };
  local_ocr: {
    claims_all_critical_local_only: number;
    claims_all_critical_local_only_rate: number;
    fields: Array<{
      field: string;
      present: number;
      local_only: number;
      local_only_rate: number;
      had_di: number;
      had_cloud: number;
    }>;
    engine_attempts: Record<string, number>;
    engine_observed: Record<string, number>;
  };
  hitl_blockers: Record<string, number>;
  hitl_claim_ids: string[];
  reg_claim_ids: string[];
};

function pct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function fmt(n: number): string {
  return n.toLocaleString();
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="ops-stat">
      <span className="ops-stat-label">{label}</span>
      <strong className="ops-stat-value">{value}</strong>
      {hint ? <span className="ops-stat-hint">{hint}</span> : null}
    </div>
  );
}

export function OpsUsagePanel({ reportUrl = "/reports/ops_usage.json" }: { reportUrl?: string }) {
  const [report, setReport] = useState<OpsUsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveProgress, setLiveProgress] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(reportUrl)
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((payload) => {
          if (!cancelled) {
            setReport(payload);
            setError(null);
          }
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message || "Failed to load ops usage report");
        });
      fetch("/ops-usage/progress")
        .then((r) => (r.ok ? r.json() : null))
        .then((payload) => {
          if (!cancelled && payload?.progress) setLiveProgress(String(payload.progress));
        })
        .catch(() => undefined);
    };
    load();
    const id = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [reportUrl]);

  if (error && !report) {
    return (
      <section className="ops-panel">
        <h3>Ops usage</h3>
        <p className="ops-empty">No ops usage report yet ({error}).</p>
      </section>
    );
  }
  if (!report) {
    return (
      <section className="ops-panel">
        <h3>Ops usage</h3>
        <p className="ops-empty">Loading ops usage…</p>
      </section>
    );
  }

  return (
    <section className="ops-panel">
      <header className="ops-header">
        <div>
          <h3>Ops usage — DI / HITL / local OCR / tokens</h3>
          <p className="ops-sub">
            Cohort <code>{report.cohort}</code> · n={report.n}
            {report.median_elapsed_sec != null
              ? ` · median ${report.median_elapsed_sec.toFixed(1)}s`
              : ""}
          </p>
        </div>
        {liveProgress ? <p className="ops-live">Live: {liveProgress}</p> : null}
      </header>

      <div className="ops-grid">
        <Stat label="TRUE_STP" value={`${fmt(report.true_stp)} (${pct(report.true_stp_rate)})`} />
        <Stat label="Field HITL" value={`${fmt(report.hitl)} (${pct(report.hitl_rate)})`} />
        <Stat label="Registration failed" value={fmt(report.registration_failed)} />
        <Stat
          label="DI API calls"
          value={fmt(report.azure_di.api_calls)}
          hint={`${report.azure_di.ok} ok / ${report.azure_di.fail} fail`}
        />
        <Stat
          label="Claims with DI charge"
          value={`${fmt(report.azure_di.claims_with_di_charge)} (${pct(report.azure_di.claims_with_di_charge_rate)})`}
        />
        <Stat
          label="Conflict-agent attempts"
          value={fmt(report.cloud.conflict_agent_attempts)}
          hint={`on ${report.cloud.conflict_agent_claims} claims`}
        />
        <Stat
          label="VLM tokens (total)"
          value={report.vlm_tokens.metered ? fmt(report.vlm_tokens.total_tokens) : "not metered"}
          hint={
            report.vlm_tokens.metered
              ? `${fmt(report.vlm_tokens.input_tokens)} in / ${fmt(report.vlm_tokens.output_tokens)} out · ${fmt(report.vlm_tokens.calls)} calls`
              : report.vlm_tokens.note || undefined
          }
        />
        <Stat
          label="All-critical local-only"
          value={`${fmt(report.local_ocr.claims_all_critical_local_only)} (${pct(report.local_ocr.claims_all_critical_local_only_rate)})`}
        />
      </div>

      <div className="ops-columns">
        <div className="ops-card">
          <h4>Azure DI</h4>
          <ul>
            {Object.entries(report.azure_di.by_kind).map(([k, v]) => (
              <li key={k}>
                <span>{k}</span>
                <strong>{fmt(v)}</strong>
              </li>
            ))}
            {Object.entries(report.azure_di.by_field).map(([k, v]) => (
              <li key={`f-${k}`}>
                <span>field:{k}</span>
                <strong>{fmt(v)}</strong>
              </li>
            ))}
          </ul>
        </div>

        <div className="ops-card">
          <h4>VLM tokens</h4>
          {report.vlm_tokens.metered ? (
            <ul>
              <li>
                <span>input</span>
                <strong>{fmt(report.vlm_tokens.input_tokens)}</strong>
              </li>
              <li>
                <span>output</span>
                <strong>{fmt(report.vlm_tokens.output_tokens)}</strong>
              </li>
              <li>
                <span>total</span>
                <strong>{fmt(report.vlm_tokens.total_tokens)}</strong>
              </li>
              {Object.entries(report.vlm_tokens.by_provider_total_tokens).map(([k, v]) => (
                <li key={k}>
                  <span>{k}</span>
                  <strong>{fmt(v)}</strong>
                </li>
              ))}
            </ul>
          ) : (
            <p className="ops-note">{report.vlm_tokens.note}</p>
          )}
          <p className="ops-note">
            Cloud on critical fields: {fmt(report.cloud.claims_with_claude_or_gpt_on_critical)} (
            {pct(report.cloud.claims_with_claude_or_gpt_rate)})
          </p>
        </div>

        <div className="ops-card">
          <h4>Local OCR (field settled without DI/cloud)</h4>
          <table className="ops-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Local-only</th>
                <th>DI</th>
                <th>Cloud</th>
              </tr>
            </thead>
            <tbody>
              {report.local_ocr.fields.map((f) => (
                <tr key={f.field}>
                  <td>{f.field}</td>
                  <td>
                    {fmt(f.local_only)}/{fmt(f.present)} ({pct(f.local_only_rate)})
                  </td>
                  <td>{fmt(f.had_di)}</td>
                  <td>{fmt(f.had_cloud)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="ops-engines">
            {Object.entries(report.local_ocr.engine_attempts).map(([k, v]) => (
              <li key={k}>
                <span>{k} attempts</span>
                <strong>{fmt(v)}</strong>
              </li>
            ))}
          </ul>
        </div>

        <div className="ops-card">
          <h4>HITL blockers</h4>
          <ul>
            {Object.entries(report.hitl_blockers).map(([k, v]) => (
              <li key={k}>
                <span>{k}</span>
                <strong>{fmt(v)}</strong>
              </li>
            ))}
          </ul>
          {report.hitl_claim_ids.length ? (
            <p className="ops-ids">
              {report.hitl_claim_ids
                .map((id) => String(id).split("__").pop() || id)
                .join(", ")}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
