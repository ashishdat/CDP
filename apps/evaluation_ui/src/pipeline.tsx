import type { EvaluationReport } from "./types";

const stages = [
  ["01", "Document foundation", "Ingest & prepare", "Decode every page, normalize orientation, assess scan quality and retain the immutable source image hash.", "TIFF / PDF / image|deskew|quality score", ""],
  ["02", "Page intelligence", "Classify & align", "Classify each page, verify anchors and align standard forms to their versioned reference template.", "family classifier|anchors|homography", ""],
  ["03", "Field-level crops", "Build regional evidence", "Create field-specific and complete-block crops with coordinate lineage, padding profiles and blank-crop rejection.", "source bbox|aligned bbox|crop quality", ""],
  ["04", "Lowest-cost evidence first", "Run local OCR cascade", "Run PaddleOCR first, then alternate Paddle recognition, constrained Tesseract and handwriting OCR only where indicated.", "Paddle family|Tesseract|TrOCR review-only", "local"],
  ["05", "Deterministic controls", "Parse & validate", "Normalize by field type, reconstruct geometry, parse names and addresses, and enforce NPI, date, ZIP, code and amount rules.", "hard validation|semantic state|no sentinels as OCR", "control"],
  ["06", "Crop-only LLM fallback", "Escalate unresolved crops", "If enabled and authorized, send only unresolved regional crops to Azure GPT-4o with a strict schema and abstention contract.", "PHI-gated|temperature 0|shadow-first", "cloud"],
  ["07", "Safe candidate selection", "Reconcile evidence", "Apply eligibility and dominance rules, independent-engine agreement, calibrated confidence and contradiction checks.", "router v1 frozen|provenance|winning margin", "control"],
  ["08", "Final disposition", "Verify or abstain", "Critical fields require authoritative evidence; insufficient or contradictory evidence always fails closed.", "reference match|safe abstention|audit trail", "control"],
] as const;

export function PipelineFlow({ report }: { report: EvaluationReport }) {
  const observedMethods = Object.keys(report.accuracy_by_extraction_method);
  return (
    <section className="flow-view">
      <div className="section-intro">
        <div><p className="eyebrow">Controlled extraction architecture</p><h2>How evidence becomes a validated field</h2><p>Each level adds evidence. No OCR engine or LLM can bypass deterministic validation and critical-field policy.</p></div>
        <div className="flow-legend"><span><i className="legend-local" /> Local model</span><span><i className="legend-cloud" /> Authorized cloud</span><span><i className="legend-control" /> Safety control</span></div>
      </div>
      <div className="flow-rail">
        {stages.map(([number, label, title, detail, tags, tone], index) => (
          <article className={`flow-stage ${tone}`} key={number}>
            <div className="stage-index">{number}</div>
            <div className="stage-copy"><span>{label}</span><h3>{title}</h3><p>{detail}</p><div className="stage-tags">{tags.split("|").map((tag) => <b key={tag}>{tag}</b>)}</div></div>
            {index < stages.length - 1 && <div className="stage-connector" aria-hidden="true">↓</div>}
          </article>
        ))}
      </div>
      <div className="decision-grid">
        <article className="decision-card success"><span>Accept automatically</span><strong>Valid + corroborated</strong><p>Hard rules pass, policy threshold passes, provenance is regional, and required independent/reference evidence agrees.</p></article>
        <article className="decision-card review"><span>Abstain safely</span><strong>Insufficient evidence</strong><p>Disagreement, ambiguity, unreadable handwriting or a missing critical reference creates a review task—not a guess.</p></article>
        <article className="decision-card observed"><span>Observed in this report</span><strong>{observedMethods.length} extraction routes</strong><p>{observedMethods.length ? observedMethods.map((method) => method.replaceAll("_", " ")).join(" · ") : "No route breakdown supplied."}</p></article>
      </div>
    </section>
  );
}

const tuningGroups = [
  ["Correct cell, correct page", "Alignment & coordinates", "Template homography for CMS-1500 and UB-04|Anchor-relative fallback for variable layouts|Source and aligned bounding-box lineage|Blank, clipped and overlap rejection"],
  ["More readable regional evidence", "Crop optimization", "Field-specific asymmetric padding|2× and 3× upscale|CLAHE and adaptive threshold variants|Line removal only where geometry permits"],
  ["Less confident nonsense", "Field-aware recognition", "Recognition-only OCR for isolated lines|Line segmentation for multiline blocks|Character whitelists for IDs and codes|Handwriting detection before TrOCR escalation"],
  ["Correct component selection", "Deterministic parsing", "Complete name and address block parsing|Calendar, NPI checksum and ZIP validation|Geometry-based checkbox interpretation|Semantic states separated from output sentinels"],
  ["Zero critical false accepts", "Reconciliation safety", "Routing-only tokens cannot become values|Hard-valid evidence dominates invalid evidence|Independent architectures—not model versions—count as agreement|Critical uncertainty routes to review"],
  ["No benchmark-only shortcuts", "Governed model promotion", "New models start review-only|Frozen validation and untouched holdout|Per-route promotion instead of global enablement|Cost, latency, abstention and regression gates"],
] as const;

const hotlRoadmap = [
  ["01", "ACTIVE", "HITL production review", "Uncertain fields fail closed into the reviewer queue. Every decision retains crop, candidate, validation and reviewer lineage.", "Open review queue|field-level correction|audit trail"],
  ["02", "ACTIVE", "Structured correction memory", "Approved corrections are stored as tenant- and field-scoped examples and injected into matching future prompts without bypassing validation.", "append-only memory|bounded examples|deterministic gate"],
  ["03", "NEXT", "Shadow adaptation", "Replay learned patterns without changing production outcomes. Compare extraction, abstention and contradiction rates against reviewer-approved results.", "prediction before label|no silent promotion|route metrics"],
  ["04", "PLANNED", "Route-scoped canary", "Promote only qualified field-family routes through 5%, 25% and 50% canaries after untouched holdout evidence passes.", "≥99% selective accuracy|zero critical false accepts|automatic rollback"],
  ["05", "TARGET", "HOTL with continuous control", "Remove routine human review only for certified routes. Drift, new form versions, contradictions or low confidence immediately restore HITL.", "route-level autonomy|drift monitoring|fail-back to HITL"],
] as const;

export function TuningView() {
  return (
    <section className="tuning-view">
      <div className="section-intro"><div><p className="eyebrow">Optimization catalogue</p><h2>Tuning applied across the extraction stack</h2><p>Accuracy improvements come from better evidence and safer interpretation—not from forcing uncertain values.</p></div></div>
      <div className="tuning-grid">
        {tuningGroups.map(([outcome, title, items], index) => <article className="tuning-card" key={title}><span className="tuning-number">{String(index + 1).padStart(2, "0")}</span><div><p className="eyebrow">{outcome}</p><h3>{title}</h3><ul>{items.split("|").map((item) => <li key={item}>{item}</li>)}</ul></div></article>)}
      </div>
      <div className="governance-strip"><div><span>Production policy</span><strong>Fail closed</strong></div><div><span>Critical fields</span><strong>Reference or review</strong></div><div><span>LLM scope</span><strong>Unresolved crops only</strong></div><div><span>Truth during inference</span><strong>Never available</strong></div></div>
      <div className="section-intro hotl-heading"><div><p className="eyebrow">Promotion roadmap</p><h2>HITL to HOTL</h2><p>Human-out-of-the-loop is earned per field-family route. It is never enabled globally from prompt learning alone.</p></div><span className="badge">Route scoped</span></div>
      <div className="hotl-roadmap">
        {hotlRoadmap.map(([number, status, title, detail, gates]) => <article className={`hotl-step ${status.toLowerCase()}`} key={number}><div className="hotl-step-index">{number}</div><div><div className="hotl-step-title"><span className="cost-status">{status}</span><h3>{title}</h3></div><p>{detail}</p><div className="stage-tags">{gates.split("|").map((gate) => <b key={gate}>{gate}</b>)}</div></div></article>)}
      </div>
      <div className="hotl-gates"><div><span>Promotion</span><strong>Untouched holdout passes</strong></div><div><span>Safety</span><strong>0 critical false accepts</strong></div><div><span>Quality</span><strong>≥99% selective accuracy</strong></div><div><span>Rollback</span><strong>Immediate on drift</strong></div></div>
    </section>
  );
}
