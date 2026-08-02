import { useMemo, useState } from "react";

type ApiDocument = { document_id: string; status: string; detected_format: string; page_count: number; source_filename: string; is_new_document: boolean };
type ApiField = { field_name: string; value: string; normalized_value: string | null; confidence: number; page_number: number; extraction_method: string; validation_status: string; validation_reasons: string[] };
type ApiResult = { document: ApiDocument; fields: ApiField[]; field_count: number; processing_complete: boolean };
type Phase = "READY" | "UPLOADING" | "PROCESSING" | "COMPLETE" | "FAILED";
type UploadJob = { key: string; file: File; previewUrl: string | null; phase: Phase; progress: number; result?: ApiResult; error?: string };

const terminal = new Set(["FAILED", "QUARANTINED", "NEEDS_REVIEW", "COMPLETED", "OUTPUT_GENERATED"]);
const wait = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

async function apiError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return String(body.detail ?? `Request failed (${response.status})`);
  } catch {
    return `Request failed (${response.status})`;
  }
}

export function ProcessingWorkspace() {
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [dragging, setDragging] = useState(false);
  const active = jobs.some((job) => job.phase === "UPLOADING" || job.phase === "PROCESSING");
  const completed = useMemo(() => jobs.filter((job) => job.phase === "COMPLETE").length, [jobs]);

  function addFiles(files: FileList | File[]) {
    const accepted = Array.from(files).filter((file) =>
      ["image/png", "image/jpeg", "image/tiff", "application/pdf"].includes(file.type) || /\.(png|jpe?g|tiff?|pdf)$/i.test(file.name));
    setJobs((current) => [...current, ...accepted.map((file) => ({
      key: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
      file,
      previewUrl: file.type.startsWith("image/") ? URL.createObjectURL(file) : null,
      phase: "READY" as const,
      progress: 0,
    }))]);
  }

  function patch(key: string, values: Partial<UploadJob>) {
    setJobs((current) => current.map((job) => job.key === key ? { ...job, ...values } : job));
  }

  async function processJob(job: UploadJob) {
    patch(job.key, { phase: "UPLOADING", progress: 12, error: undefined });
    const form = new FormData();
    form.append("file", job.file);
    const uploaded = await fetch("/api/documents?tenant_id=prototype-ui", { method: "POST", body: form });
    if (!uploaded.ok) throw new Error(await apiError(uploaded));
    const document = await uploaded.json() as ApiDocument;
    patch(job.key, { phase: "PROCESSING", progress: 28, result: { document, fields: [], field_count: 0, processing_complete: false } });

    // Cold CPU workers may need several minutes to initialize OCR models.
    for (let attempt = 0; attempt < 300; attempt += 1) {
      await wait(2000);
      const response = await fetch(`/api/documents/${document.document_id}/results`, { cache: "no-store" });
      if (!response.ok) throw new Error(await apiError(response));
      const result = await response.json() as ApiResult;
      patch(job.key, { phase: "PROCESSING", progress: Math.min(92, 35 + attempt * 2 + (result.document.page_count ? 15 : 0)), result });
      if (result.processing_complete || terminal.has(result.document.status)) {
        if (["FAILED", "QUARANTINED"].includes(result.document.status)) throw new Error(`Pipeline stopped with status ${result.document.status}`);
        patch(job.key, { phase: "COMPLETE", progress: 100, result });
        return;
      }
    }
    throw new Error("Processing did not finish within ten minutes. The document remains available by ID.");
  }

  async function processAll() {
    for (const job of jobs.filter((item) => item.phase === "READY" || item.phase === "FAILED")) {
      try {
        await processJob(job);
      } catch (reason) {
        patch(job.key, { phase: "FAILED", error: reason instanceof Error ? reason.message : "Processing failed" });
      }
    }
  }

  function clear() {
    jobs.forEach((job) => job.previewUrl && URL.revokeObjectURL(job.previewUrl));
    setJobs([]);
  }

  function download(job: UploadJob) {
    if (!job.result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(job.result, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${job.file.name.replace(/\.[^.]+$/, "")}-extraction.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return <section className="processing-workspace">
    <div className="process-intro">
      <div><p className="eyebrow">Live prototype</p><h2>Upload and process claims</h2><p>PNG, JPEG, TIFF or PDF. Files enter the real asynchronous preparation, routing and regional OCR pipeline.</p></div>
      <div className="process-summary"><strong>{completed}/{jobs.length}</strong><span>completed</span></div>
    </div>
    <div className={`upload-dropzone ${dragging ? "dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files); }}>
      <div className="upload-icon">↑</div><h3>Drop claim images here</h3><p>Multiple files supported. Maximum size follows the ingestion policy.</p><label className="primary-button upload-file-label">Choose files<input multiple type="file" accept="image/png,image/jpeg,image/tiff,application/pdf,.tif,.tiff" onChange={(event) => { if (event.target.files) addFiles(event.target.files); event.target.value = ""; }} /></label>
    </div>
    {jobs.length > 0 && <div className="process-toolbar"><span>{jobs.length} document{jobs.length === 1 ? "" : "s"} queued</span><div><button disabled={active} onClick={clear}>Clear</button><button className="primary-button" disabled={active || jobs.every((job) => job.phase === "COMPLETE")} onClick={processAll}>{active ? "Processing…" : "Process documents"}</button></div></div>}
    <div className="upload-jobs">{jobs.map((job) => <article className="upload-job" key={job.key}>
      <div className="upload-preview">{job.previewUrl ? <img src={job.previewUrl} alt={`Preview of ${job.file.name}`} /> : <span>PDF</span>}</div>
      <div className="job-content"><div className="job-heading"><div><h3>{job.file.name}</h3><p>{(job.file.size / 1024 / 1024).toFixed(2)} MB · {job.result?.document.detected_format ?? job.file.type}</p></div><span className={`job-status ${job.phase.toLowerCase()}`}>{job.phase}</span></div>
        <div className="progress-track"><i style={{ width: `${job.progress}%` }} /></div>
        {job.result && <div className="job-meta"><span>Document ID <code>{job.result.document.document_id}</code></span><span>Pipeline <strong>{job.result.document.status}</strong></span><span>Pages <strong>{job.result.document.page_count}</strong></span><span>Fields <strong>{job.result.field_count}</strong></span></div>}
        {job.error && <p className="job-error">{job.error}</p>}
        {job.result?.fields.length ? <div className="job-results"><div className="job-results-heading"><h4>Extracted fields</h4><button onClick={() => download(job)}>Download JSON</button></div><div className="table-scroll"><table><thead><tr><th>Field</th><th>Value</th><th>Confidence</th><th>Page</th><th>Validation</th><th>Method</th></tr></thead><tbody>{job.result.fields.map((field, index) => <tr key={`${field.field_name}-${field.page_number}-${index}`}><td><strong>{field.field_name.replaceAll("_", " ")}</strong></td><td>{(field.normalized_value ?? field.value) || "—"}</td><td>{(field.confidence * 100).toFixed(1)}%</td><td>{field.page_number}</td><td><span className={`badge ${field.validation_status.toLowerCase()}`}>{field.validation_status}</span></td><td>{field.extraction_method}</td></tr>)}</tbody></table></div></div> : null}
      </div>
    </article>)}</div>
  </section>;
}
