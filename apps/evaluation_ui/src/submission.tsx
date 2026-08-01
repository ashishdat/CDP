import { percent } from "./report";
import type { EvaluationReport } from "./types";

function money(value: number | null | undefined) {
  return value == null ? "Not metered" : `$${value.toFixed(6)}`;
}

const architecture = [
  ["01", "Ingestion & preparation", "Decode every page, preserve source hashes, normalize orientation and score image quality."],
  ["02", "Classification & alignment", "Classify each page, validate anchors and align CMS-1500/UB-04 forms using versioned templates."],
  ["03", "Regional evidence", "Build field and block crops with source/aligned bounding boxes, crop-quality checks and complete provenance."],
  ["04", "Local OCR cascade", "PP-OCRv4 primary, PP-OCRv5/v6 recognition routes, constrained Tesseract and geometry-based mark detection."],
  ["05", "Parsing & validation", "Apply field-specific parsing, NPI/date/ZIP/code/amount validation, semantic states and business rules."],
  ["06", "Selective vision fallback", "Escalate only unresolved regional crops to Azure GPT-4o; retain schema, confidence and abstention evidence."],
  ["07", "Reconciliation & output", "Apply dominance rules, contradiction checks and governed references before JSON, CSV, NSF or UB92 projection."],
  ["08", "Audit & observability", "Persist candidate lineage, version checksums, latency, cost, disposition and failure category."],
] as const;

const demo = [
  ["00:00–01:00", "Problem and sample set", "Show image-based claims and the structured target fields."],
  ["01:00–03:00", "Process a claim", "Upload a document and follow page classification, alignment and regional cropping."],
  ["03:00–05:00", "Explain the cascade", "Show local OCR, validation, local-first short-circuits and selective LLM escalation."],
  ["05:00–07:00", "Inspect evidence", "Open Field Evidence and compare source page, crop, expected and extracted output."],
  ["07:00–08:30", "Export output", "Show normalized JSON/CSV and fixed-width NSF/UB92 generation."],
  ["08:30–10:00", "Metrics and economics", "Show accuracy scope, safety, throughput, latency, cost and scale-out design."],
] as const;

export function SubmissionView({ report }: { report: EvaluationReport }) {
  const operations = report.operational_metrics;
  const cost = report.cost_analysis;
  const annualAveragePps = 100_000_000 / (365 * 24 * 60 * 60);
  return <section className="submission-view">
    <div className="submission-callout"><div><p className="eyebrow">Healthcare AI Hackathon</p><h2>Submission readiness centre</h2><p>All narrative and benchmark figures below are connected to the deployed evaluation artifact.</p></div><span className="submission-ready">5 deliverables mapped</span></div>

    <article className="submission-section executive-section">
      <div className="submission-index">01</div><div className="submission-content"><p className="eyebrow">Executive summary</p><h2>High-accuracy claims extraction with evidence-first controls</h2>
      <div className="narrative-grid"><div><h3>Problem understanding</h3><p>Healthcare claims arrive as noisy scans, standard forms, attachments and handwriting. Fixed crops miss values, generic OCR confuses labels with data, and unconstrained AI creates unacceptable risk for critical identity and clinical fields.</p></div><div><h3>Solution overview</h3><p>A page-aware IDP platform aligns structured forms, extracts field-level evidence through a local OCR cascade, applies deterministic validation, and uses crop-only vision fallback only when cheaper evidence is insufficient.</p></div><div><h3>Key innovations</h3><p>Field-level page routing, geometry-preserving crops, independent candidate provenance, semantic-state separation, deterministic dominance rules, reference verification and measurable local-first cost short-circuits.</p></div><div><h3>Why this solution should win</h3><p>It balances accuracy, explainability and cost. Every output is traceable to an image region, expensive inference is selective, critical errors fail closed, and the architecture scales horizontally without coupling extraction to one vendor.</p></div></div>
      <div className="result-ribbon"><div><span>Validated accuracy</span><strong>{percent(report.normalized_field_accuracy)}</strong><small>Current labelled sample</small></div><div><span>Local extraction</span><strong>{percent(report.local_extraction_accuracy ?? report.ocr_deterministic_accuracy)}</strong><small>OCR + parsing + geometry</small></div><div><span>Optimized LLM diversion</span><strong>{percent(report.llm_diversion_rate)}</strong><small>{report.llm_diverted_fields}/{report.field_count} fields</small></div><div><span>Cost per page</span><strong>{money(cost?.projected_optimized_cost_per_page_usd ?? cost?.total_cost_per_page_usd)}</strong><small>Policy replay projection</small></div><div><span>Throughput</span><strong>{operations?.pages_per_second == null ? "Not metered" : `${operations.pages_per_second.toFixed(2)} p/s`}</strong><small>Frozen assembly benchmark</small></div><div><span>Average latency</span><strong>{operations?.average_latency_seconds == null ? "Not metered" : `${operations.average_latency_seconds.toFixed(3)}s`}</strong><small>See measurement note</small></div></div>
      </div>
    </article>

    <article className="submission-section"><div className="submission-index">02</div><div className="submission-content"><p className="eyebrow">Architecture document</p><h2>End-to-end component design</h2><div className="architecture-list">{architecture.map(([number, title, text]) => <div key={number}><b>{number}</b><section><h3>{title}</h3><p>{text}</p></section></div>)}</div>
      <div className="architecture-topics"><div><h3>Confidence-based routing</h3><p>Hard validation, crop quality, provenance, engine agreement and contradiction checks determine acceptance. Raw confidence values from different engines are never compared directly.</p></div><div><h3>Cost optimization</h3><p>Local OCR runs first; requests are deduplicated; validated reference, parser and semantic decisions bypass cloud inference; only unresolved crops reach GPT-4o.</p></div><div><h3>100M+ pages/year</h3><p>The annual average is {annualAveragePps.toFixed(2)} pages/second. Stateless workers, Kafka partitions, object storage, autoscaling and model-specific pools provide burst capacity and failure isolation.</p></div><div><h3>Failure handling</h3><p>Idempotent jobs, content-hash caching, retry/dead-letter queues, explicit NO_EVIDENCE, safe abstention and full audit lineage separate product defects from infrastructure failures.</p></div></div></div></article>

    <article className="submission-section"><div className="submission-index">03</div><div className="submission-content"><p className="eyebrow">Working prototype</p><h2>10-minute live demonstration</h2><div className="demo-timeline">{demo.map(([time, title, detail]) => <div key={time}><time>{time}</time><section><h3>{title}</h3><p>{detail}</p></section></div>)}</div></div></article>

    <article className="submission-section"><div className="submission-index">04</div><div className="submission-content"><p className="eyebrow">Source code</p><h2>Production handoff checklist</h2><div className="check-grid">{["Complete source code", "Root README and UI README", "Pinned Python and Node dependencies", "Versioned templates and policies", "Environment-based configuration", "Docker Compose setup", "Unit/integration/golden tests", "Deployment and autoscaling manifests"].map((item) => <div key={item}><span>✓</span>{item}</div>)}</div><p className="submission-note">The submission ZIP contains the executive summary, architecture, demo and benchmark only. Source code is uploaded separately through the designated submission link.</p></div></article>

    <article className="submission-section"><div className="submission-index">05</div><div className="submission-content"><p className="eyebrow">Benchmark report</p><h2>Excel-ready measured metrics</h2><div className="benchmark-table-wrap"><table className="benchmark-table"><thead><tr><th>Metric</th><th>Value</th><th>Measurement scope</th></tr></thead><tbody>
      <tr><td>Total pages processed</td><td>{operations?.total_pages_processed ?? "Not metered"}</td><td>Current governed sample</td></tr><tr><td>Processing time</td><td>{operations?.processing_time_seconds == null ? "Not metered" : `${operations.processing_time_seconds.toFixed(3)} seconds`}</td><td>Frozen candidate assembly; excludes fresh model inference</td></tr><tr><td>Average latency</td><td>{operations?.average_latency_seconds == null ? "Not metered" : `${operations.average_latency_seconds.toFixed(3)} seconds/page`}</td><td>Same timing boundary</td></tr><tr><td>Pages per second</td><td>{operations?.pages_per_second == null ? "Not metered" : operations.pages_per_second.toFixed(3)}</td><td>Same timing boundary</td></tr><tr><td>Validated accuracy</td><td>{percent(report.normalized_field_accuracy)}</td><td>Current labelled sample; governed closure</td></tr><tr><td>Local extraction accuracy</td><td>{percent(report.local_extraction_accuracy ?? report.ocr_deterministic_accuracy)}</td><td>OCR, deterministic parsing and geometry; excludes LLM and references</td></tr><tr><td>Precision / Recall</td><td>{operations ? `${percent(operations.precision)} / ${percent(operations.recall)}` : "Not metered"}</td><td>Normalized field outcomes</td></tr>
      {cost?.components.map((component) => <tr key={component.name}><td>{component.name} cost/page</td><td>{money(component.name === "LLM" && cost.projected_optimized_cost_per_page_usd != null ? cost.projected_optimized_cost_per_page_usd : component.cost_per_page_usd)}</td><td>{component.status.replaceAll("_", " ")} · {component.name === "LLM" && cost.projected_optimized_cost_per_page_usd != null ? "Latest optimized crop-only route projection" : component.basis}</td></tr>)}{cost?.projected_optimized_cost_per_page_usd != null && <tr className="benchmark-projected"><td>Total optimized cost/page</td><td>{money(cost.projected_optimized_cost_per_page_usd)}</td><td>Current-sample local-first policy replay; not invoice data</td></tr>}
    </tbody></table></div></div></article>
  </section>;
}
