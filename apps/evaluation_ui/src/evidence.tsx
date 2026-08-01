import { useMemo, useState } from "react";
import { Empty } from "./components";
import { percent } from "./report";
import type { FieldEvidence } from "./types";

export function EvidenceView({ rows }: { rows: FieldEvidence[] }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => !needle ||
      [row.document_id, row.field_name, row.form_type, row.extraction_method]
        .join(" ").toLowerCase().includes(needle));
  }, [rows, query]);

  return <section className="panel evidence-panel">
    <div className="panel-heading table-heading">
      <div><p className="eyebrow">Side-by-side evidence</p><h2>Source image and extracted output</h2><p className="evidence-note">Expected values are evaluation-only and were unavailable during inference.</p></div>
      <div className="filters"><input aria-label="Search evidence" placeholder="Search document or field..." value={query} onChange={(event) => setQuery(event.target.value)} /></div>
    </div>
    {filtered.length === 0 ? <Empty>No published image evidence matches this filter.</Empty> :
      <div className="evidence-grid">{filtered.map((row, index) =>
        <article className="evidence-card" key={`${row.document_id}-${row.field_name}-${index}`}>
          <div className="evidence-card-head"><div><strong>{row.field_name.replaceAll("_", " ")}</strong><small>{row.document_id} · {row.form_type}</small></div><span className={`badge ${row.correct ? "valid" : "failure"}`}>{row.status}</span></div>
          <div className="evidence-images">
            <figure>{row.original_page_url ? <a href={row.original_page_url} target="_blank" rel="noreferrer"><img src={row.original_page_url} alt={`Original page for ${row.field_name}`} loading="lazy" /></a> : <div className="image-missing">Page unavailable</div>}<figcaption>Original page</figcaption></figure>
            <figure>{row.crop_url ? <a href={row.crop_url} target="_blank" rel="noreferrer"><img src={row.crop_url} alt={`Crop for ${row.field_name}`} loading="lazy" /></a> : <div className="image-missing">Crop unavailable</div>}<figcaption>Regional crop</figcaption></figure>
          </div>
          <div className="evidence-values"><div><span>Expected</span><strong>{row.expected_value ?? "—"}</strong></div><div><span>Extracted</span><strong>{row.extracted_value ?? "—"}</strong></div><div><span>Normalized</span><strong>{row.normalized_value ?? "—"}</strong></div></div>
          <footer className="evidence-meta"><span>{row.extraction_method || "unknown provider"}</span><span>{row.confidence == null ? "No confidence" : `${percent(row.confidence)} confidence`}</span></footer>
        </article>)}</div>}
  </section>;
}
