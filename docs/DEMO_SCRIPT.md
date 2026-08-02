# Healthcare Claims IDP — 10-minute demo and pitch script

## Presenter preparation

Before the session:

1. Restart Docker Desktop and allow at least 8 GB memory for the OCR workers.
2. Run `docker compose up -d ingestion-api document-preparation-worker page-detection-worker standard-form-extraction-worker evaluation-ui`.
3. Open `http://localhost:8180` and confirm the Overview and Process claims tabs load.
4. Keep one representative CMS-1500 or UB-04 image ready for upload. Avoid using real PHI unless the demonstration environment and audience are authorized.
5. Pre-warm the OCR worker with a non-sensitive sample. The first PaddleOCR invocation downloads/loads models and can take several minutes on a CPU-only Docker Desktop environment.
6. Keep a previously completed extraction JSON available as a fallback if venue networking or Docker resources fail.

Do not describe the current-sample score as independent production accuracy. Say “100% normalized accuracy on the governed current sample.” The untouched production holdout and authorization gates remain separate.

## 0:00–0:45 — Opening and objective

**On screen:** Overview tab.

**Say:**

“Healthcare claims arrive as clean digital forms, scanned CMS-1500 and UB-04 documents, multipage attachments, invoices, statements and handwritten records. Traditional OCR treats these documents as plain text. That loses form geometry, selects data from the wrong page, confuses labels with values and sends too many cases to manual review.

Our objective is to convert these documents into validated, traceable claim data with the best practical balance of accuracy, cost, throughput and safety. The solution is local-first: OpenCV, regional OCR and deterministic validation handle the majority of evidence. A multimodal LLM sees only the small unresolved crop—not the whole claim—and only after cheaper methods fail.”

## 0:45–1:30 — Use case and business value

**Say:**

“The primary use case is claims intake and normalization. A payer, provider, clearinghouse or claims operations team uploads an image, TIFF or PDF. The platform identifies each page, aligns structured forms, extracts field-level evidence, validates healthcare identifiers and codes, reconciles competing candidates, and produces canonical JSON plus evidence suitable for CSV or fixed-width NSF and UB92 generation.

This reduces manual data entry, shortens claim intake time, lowers per-page AI cost and creates an auditable answer to a critical question: which pixels produced each field?”

## 1:30–2:30 — Results summary

**On screen:** Point to the front-page metric table/cards.

**Say:**

“On the current governed sample, the system processes 239 labelled fields across 30 pages.

- Final normalized accuracy is 100% on this sample.
- Local extraction accuracy before LLM fallback is 90.38%.
- Only 9 of 239 fields—3.77%—are diverted to Azure OpenAI Vision.
- Critical-field accuracy is 100% on this sample, with zero critical false accepts.
- The measured Azure provider cost is $0.003663 per source page, or $0.10989 for this 30-page run.
- The optimized cost projection is $0.00091575 per page after local-first routing and cache policies.

The displayed 7.66 pages per second and 130-millisecond average latency measure frozen candidate assembly, parsing and reconciliation. They intentionally exclude fresh OCR model cold start and cloud network latency. We show that qualification in the report rather than mixing unlike measurements.”

## 2:30–3:30 — Technology stack

**On screen:** OCR & LLM flow tab or architecture diagram.

**Say:**

“The platform uses a production-oriented, event-driven stack:

- React and TypeScript for the report and live processing workspace.
- FastAPI and Pydantic for ingestion and results APIs.
- Postgres for documents, provenance, candidates and audit records.
- MinIO for original pages, aligned images and regional crops.
- Redpanda using the Kafka protocol for asynchronous worker events.
- Pillow and OpenCV for decoding, orientation, deskewing, denoising, alignment, homography and checkbox geometry.
- PaddleOCR as the primary local OCR family, with constrained Tesseract and deterministic parsers as complementary evidence.
- Azure OpenAI GPT-4o Vision as a crop-only fallback for a narrowly governed unresolved set.
- Docker Compose for the prototype, with Helm, KEDA, Prometheus, OpenTelemetry and Grafana patterns for enterprise deployment.”

## 3:30–4:45 — End-to-end processing flow

**On screen:** OCR & LLM flow tab.

**Say:**

“The flow is evidence-first and field-specific.

First, ingestion verifies the file type, hashes the document, stores it idempotently and emits an event. The preparation worker decodes every page, corrects orientation and creates reproducible image derivatives.

Next, page routing evaluates every page using document-family evidence, anchor relevance, grid signatures and template similarity. Different fields may come from different pages; routing does not assume one page contains the entire truth.

Structured forms are aligned to versioned CMS-1500 or UB-04 templates. We crop regional evidence using the correct coordinate frame, field-specific padding and crop-quality checks. PaddleOCR and Tesseract produce candidates. Checkbox fields use pixel-mark detection rather than OCR.

Deterministic parsers then validate dates, NPIs, ZIP codes, amounts and medical codes. Reconciliation applies eligibility and dominance rules: labels and routing-only text cannot become values, hard-valid regional evidence beats invalid generic text, and output sentinels never compete as visible OCR.

Only unresolved crops enter the LLM fallback. The response is schema-constrained, normalized and passed through the same validation rules. Every final field retains page, bounding box, engine, confidence, parser and decision lineage.”

## 4:45–6:15 — Live UI flow

**On screen:** Process claims tab.

**Actions and narration:**

1. Drag a representative claim image into the upload area.
   - “The browser accepts PNG, JPEG, TIFF and PDF, including multiple documents.”
2. Click **Process documents**.
   - “The file is sent through the real ingestion API—not a browser-only mock.”
3. Point to progress, document ID and pipeline status.
   - “The UI polls the results endpoint while the asynchronous workers prepare, classify and extract the document.”
4. When complete, show the extracted-fields table.
   - “Each row exposes the normalized value, confidence, page, validation status and extraction method.”
5. Click **Download JSON**.
   - “The same canonical result can feed downstream adjudication, CSV transformation or fixed-width output generation.”
6. Open **Field evidence**.
   - “Here we compare source evidence and the selected output. This makes boundary, OCR, parsing and reconciliation defects visually diagnosable.”
7. Open **OCR & LLM flow**.
   - “This tab makes the cascade and escalation policy understandable to both engineers and business reviewers.”

**If live OCR is slow:**

“This is a CPU-only cold start in Docker Desktop. In production, workers remain warm and model artifacts are mounted from a persistent cache. I’ll use the completed governed result to continue the demonstration while this job remains traceable by document ID.”

## 6:15–7:30 — Challenges and how we overcame them

**On screen:** Tuning & governance tab.

**Say:**

“The hardest problems were not solved by simply adding a larger model.

**Challenge one: wrong pages and repeated labels.** Multipage claims contained cover sheets, attachments and repeated patient or provider labels. We evaluated every eligible page for every field, persisted explicit no-evidence outcomes, introduced routing completeness, and required ambiguity margins.

**Challenge two: crop misalignment.** Template coordinates were being applied in the wrong frame or with global padding. We added source, reference-template, aligned and anchor-relative coordinate frames, homography-aware boxes, crop validity checks and field-specific expansion profiles.

**Challenge three: handwriting and degraded scans.** A single OCR engine produced confident nonsense. We introduced preprocessing variants, Paddle/Tesseract evidence families, handwriting-aware escalation, hard field validation and safe abstention. Generic handwriting candidates cannot silently auto-accept critical identity fields.

**Challenge four: correct evidence losing during selection.** We separated page routing from value reconciliation and added deterministic dominance rules before weighted scoring. Candidate lineage now explains why a value was eligible, filtered, selected or rejected.

**Challenge five: cost.** Sending entire claims to an LLM would be expensive and creates unnecessary PHI exposure. Crop-only escalation, caching, deterministic repairs and local numeric/code routes reduced LLM diversion to 3.77% on the governed sample.

**Challenge six: honest metrics.** We separated local accuracy, final accuracy, LLM diversion, abstention, critical false accepts and cost. Replay throughput is labelled separately from true end-to-end latency.”

## 7:30–8:30 — Key innovations

**Say:**

“There are six differentiators in this implementation:

1. Field-level page routing permits different fields to come from different pages.
2. Every candidate has regional provenance; absence is explicit rather than silently omitted.
3. Form geometry handles checkboxes and alignment, avoiding inappropriate OCR.
4. Visible OCR values, semantic states and output-format sentinels are kept separate.
5. Reconciliation uses hard safety rules before confidence scoring and treats OCR-family independence correctly.
6. The LLM is a governed exception processor: crop-only, schema-constrained, validated, auditable and cost-measured.

The result is not ‘OCR plus a chatbot.’ It is a specification-driven evidence and validation system where AI is used only where it adds measurable value.”

## 8:30–9:20 — Why this solution should win

**Say:**

“This solution should win because it optimizes the complete enterprise outcome rather than one model benchmark.

It demonstrates high current-sample accuracy, zero observed critical false accepts, very low LLM diversion and transparent cost. It supports structured forms and attachments, preserves evidence, avoids ground-truth leakage and provides an actual upload-to-result workflow.

It is also operationally credible: idempotent ingestion, asynchronous workers, object storage, relational provenance, immutable audit concepts, metrics, containerization and horizontal scaling patterns are built into the architecture.

Most importantly, the system knows when evidence is insufficient. In healthcare claims, a safe abstention is more valuable than a confident fabricated answer.”

## 9:20–10:00 — Limitations and closing

**Say:**

“The current limitations are explicit.

- The 100% score is on the governed current sample, not an untouched independent production holdout.
- Only 239 labelled fields and 30 pages are represented in the current published comparison.
- Fresh end-to-end OCR and LLM latency must be benchmarked separately from the frozen-policy replay.
- PaddleOCR has a heavy cold start in the CPU-only local environment; production needs persistent model volumes, warm workers and resource limits.
- External Azure processing requires approved PHI contracts, region, retention, logging and security controls.
- Critical identity and clinical fields should retain authoritative-reference verification or safe abstention policies.
- Complete production NSF/UB92/X12 coverage, enterprise identity integration, migrations, disaster recovery and untouched holdout/canary evidence remain release gates.

Our closing proposition is simple: use deterministic geometry, local OCR and healthcare rules for the predictable 96%; spend multimodal AI only on the difficult remainder; validate everything; and preserve the evidence. That delivers an accurate, economical and scalable claims-intelligence platform without hiding risk behind a single headline score.”

## Suggested judge questions and answers

### “Is the system really 100% accurate?”

“It is 100% normalized accuracy on the current governed 239-field sample. We do not present that as a production-generalization estimate. Production promotion requires an untouched document-level holdout, zero critical false accepts and a canary.”

### “Why not send every page to GPT-4o?”

“Local extraction is cheaper, faster, more deterministic and minimizes external PHI exposure. GPT-4o is used only for 3.77% of fields in this sample, and only as crop-level evidence after local methods fail.”

### “How do you prevent hallucination?”

“Strict response schemas, field whitelisting, crop-only context, temperature zero, hard validation, contradiction checks and safe insufficient-evidence outcomes. Critical fields require stronger evidence.”

### “How will it scale to 100 million pages per year?”

“The stages are stateless asynchronous workers behind Kafka-compatible topics. CPU preparation, OCR and expensive fallback pools scale independently with KEDA. Images remain in object storage, Postgres stores compact provenance, and deterministic/local routes keep costly inference demand small.”

### “What is the actual cost?”

“The measured Azure provider cost for the current run is $0.10989, or $0.003663 per source page. CPU, storage, networking and operational costs were not metered in that figure and are shown separately as unavailable rather than guessed.”

### “What happens when the model is uncertain?”

“The platform records insufficient evidence instead of inventing a value. Depending on field criticality and deployment policy, it can use an authorized reference, enter governed exception processing, or abstain.”

## One-minute backup pitch

“Our healthcare claims IDP converts CMS-1500, UB-04 and supporting documents into validated, traceable claim data. Unlike flat OCR, it aligns forms, evaluates every page per field, extracts regional evidence and validates NPIs, dates, codes, amounts and checkbox geometry. PaddleOCR, Tesseract and deterministic parsers handle 90.38% locally on the current sample; only 3.77% of fields reach crop-only GPT-4o Vision. The governed 239-field sample reaches 100% normalized accuracy with zero observed critical false accepts and a measured provider cost of $0.003663 per page. Every value retains page, box, engine and decision lineage. The architecture is event-driven, containerized and independently scalable. Our advantage is not using more AI—it is using the right evidence, model and rule for each field, with honest metrics and safe abstention.”
