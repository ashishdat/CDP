import { useEffect, useMemo, useState } from "react";
import { AccuracyBars, Empty, MetricCard } from "./components";
import { parseReport, percent, signedDelta } from "./report";
import type { EvaluationReport } from "./types";
import "./styles.css";

type Breakdown = "accuracy_by_field" | "accuracy_by_form_type" | "accuracy_by_extraction_method";

function readFileText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Unable to read report."));
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsText(file);
  });
}

export default function App() {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("ALL");
  const [breakdown, setBreakdown] = useState<Breakdown>("accuracy_by_field");

  useEffect(() => {
    if (typeof fetch === "undefined") return;
    fetch("/reports/evaluation.json")
      .then((response) => {
        if (!response.ok) throw new Error("No deployed evaluation report found.");
        return response.json();
      })
      .then((payload) => setReport(parseReport(payload)))
      .catch(() => undefined);
  }, []);

  async function loadFile(file?: File) {
    if (!file) return;
    try {
      setReport(parseReport(JSON.parse(await readFileText(file))));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to read report.");
    }
  }

  const categories = useMemo(
    () => [...new Set(report?.mismatches.map((row) => row.failure_category) ?? [])],
    [report],
  );
  const rows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return (report?.mismatches ?? []).filter((row) => {
      const matchesCategory = category === "ALL" || row.failure_category === category;
      const matchesQuery =
        !normalizedQuery ||
        [row.document_id, row.field_name, row.form_type, row.extraction_method]
          .join(" ")
          .toLowerCase()
          .includes(normalizedQuery);
      return matchesCategory && matchesQuery;
    });
  }, [report, query, category]);

  const breakdownTitles: Record<Breakdown, string> = {
    accuracy_by_field: "Accuracy by field",
    accuracy_by_form_type: "Accuracy by form type",
    accuracy_by_extraction_method: "Accuracy by extraction method",
  };

  return (
    <main>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">IDP</span>
          <div>
            <strong>Claims Quality Console</strong>
            <small>Blind-holdout evaluation</small>
          </div>
        </div>
        <label className="upload-button">
          Load evaluation JSON
          <input type="file" accept="application/json,.json" onChange={(e) => loadFile(e.target.files?.[0])} />
        </label>
      </header>

      {!report ? (
        <section className="welcome">
          <div className="welcome-copy">
            <p className="eyebrow">Evidence, not estimates</p>
            <h1>Measure claims extraction with field-level proof.</h1>
            <p>
              Load the <code>evaluation.json</code> produced by the evaluation CLI to inspect
              normalized accuracy, critical-field safety, STP, and every mismatch side by side.
            </p>
            <label className="primary-button">
              Choose report
              <input type="file" accept="application/json,.json" onChange={(e) => loadFile(e.target.files?.[0])} />
            </label>
            {error && <p className="error-banner">{error}</p>}
          </div>
          <div className="welcome-visual" aria-hidden="true">
            <span>EXPECTED</span><i />
            <span>EXTRACTED</span><b>✓</b>
          </div>
        </section>
      ) : (
        <>
          <section className="hero">
            <div>
              <p className="eyebrow">Evaluation report</p>
              <h1>Extraction accuracy</h1>
              <p>{report.field_count.toLocaleString()} labelled fields evaluated</p>
            </div>
            <div className="status-chip">
              <span className={report.critical_false_accept_rate === 0 ? "status-dot good" : "status-dot danger"} />
              Critical safety gate
            </div>
          </section>

          {error && <p className="error-banner">{error}</p>}
          {report.report_metadata?.synthetic_demo && (
            <p className="demo-banner">
              Synthetic UI preview — these values are not measured platform accuracy.
            </p>
          )}
          <section className="metric-grid">
            <MetricCard label="Normalized accuracy" value={percent(report.normalized_field_accuracy)} tone={report.normalized_field_accuracy >= 0.98 ? "good" : "danger"} hint="Automated field accuracy" />
            <MetricCard label="Critical-field accuracy" value={percent(report.critical_field_accuracy)} tone={report.critical_field_accuracy === 1 ? "good" : "danger"} hint="All critical labelled fields" />
            <MetricCard label="Critical false accepts" value={percent(report.critical_false_accept_rate)} tone={report.critical_false_accept_rate === 0 ? "good" : "danger"} hint="Target: zero" />
            <MetricCard label="Perfect claims" value={percent(report.perfect_claim_rate)} hint="Every field correct" />
            <MetricCard label="Straight-through rate" value={percent(report.straight_through_processing_rate)} hint="Correct without review" />
            <MetricCard label="HITL rate" value={percent(report.hitl_rate)} hint="Claims requiring review" />
          </section>

          <section className="comparison-grid">
            <div className="panel fallback-card">
              <div>
                <p className="eyebrow">Field-level fallback</p>
                <h2>Before vs. after</h2>
              </div>
              <div className="fallback-values">
                <div><span>Before</span><strong>{percent(report.accuracy_before_fallback)}</strong></div>
                <span className="arrow">→</span>
                <div><span>After</span><strong>{percent(report.accuracy_after_fallback)}</strong></div>
              </div>
              <div className="delta">{signedDelta(report.accuracy_before_fallback, report.accuracy_after_fallback)}</div>
            </div>
            <div className="panel compact-metrics">
              <div><span>Raw exact match</span><strong>{percent(report.raw_exact_match_accuracy)}</strong></div>
              <div><span>Character error rate</span><strong>{percent(report.character_error_rate)}</strong></div>
              <div><span>Missing-field rate</span><strong>{percent(report.missing_field_rate)}</strong></div>
              <div><span>False-review rate</span><strong>{percent(report.false_review_rate)}</strong></div>
            </div>
          </section>

          <div className="breakdown-tabs">
            {(Object.keys(breakdownTitles) as Breakdown[]).map((key) => (
              <button className={breakdown === key ? "active" : ""} key={key} onClick={() => setBreakdown(key)}>
                {breakdownTitles[key].replace("Accuracy by ", "")}
              </button>
            ))}
          </div>
          <AccuracyBars title={breakdownTitles[breakdown]} values={report[breakdown]} />

          <section className="panel comparison-table">
            <div className="panel-heading table-heading">
              <div>
                <p className="eyebrow">Side-by-side evidence</p>
                <h2>Expected vs. extracted</h2>
              </div>
              <div className="filters">
                <input aria-label="Search mismatches" placeholder="Search document or field…" value={query} onChange={(e) => setQuery(e.target.value)} />
                <select aria-label="Failure category" value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="ALL">All failures</option>
                  {categories.map((value) => <option key={value}>{value}</option>)}
                </select>
              </div>
            </div>
            {rows.length === 0 ? (
              <Empty>{report.mismatches.length ? "No mismatches match these filters." : "No mismatches — every evaluated field matched."}</Empty>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Document / field</th><th>Expected</th><th>Extracted</th><th>Normalized</th><th>Confidence</th><th>Validation</th><th>Failure</th></tr></thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={`${row.document_id}-${row.field_name}-${index}`}>
                        <td><strong>{row.field_name.replaceAll("_", " ")}</strong><small>{row.document_id} · {row.form_type}</small></td>
                        <td className="value expected">{row.expected_value ?? "—"}</td>
                        <td className="value extracted">{row.extracted_value ?? "—"}<small>{row.extraction_method}</small></td>
                        <td className="value">{row.normalized_value ?? "—"}</td>
                        <td>{row.ocr_confidence == null ? "—" : percent(row.ocr_confidence)}</td>
                        <td><span className={`badge ${row.validation_result.toLowerCase()}`}>{row.validation_result}</span></td>
                        <td><span className="badge failure">{row.failure_category}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
      <footer>Measured results only · Critical fields fail closed · PHI-safe report handling</footer>
    </main>
  );
}
