// High-End Multi-Bundle & Multi-Field Transformation Engine with Interactive HITL Review

// Live document catalog populated from /api/documents (+ /results).
const DOCUMENTS = {};

function stageFromField(field) {
  const value = field.normalized_value || field.value || "";
  const confidence = typeof field.confidence === "number" ? field.confidence : null;
  const method = field.extraction_method || "OCR";
  const validation = field.validation_status || "PENDING";
  const needsHitl = ["FAILED", "NEEDS_REVIEW", "PENDING"].includes(validation) || (confidence != null && confidence < 0.8);
  const confLabel = confidence == null ? "n/a" : `${(confidence * 100).toFixed(0)}%`;
  return {
    id: field.field_name,
    name: field.field_name,
    label: field.field_name.replaceAll("_", " "),
    criticality: field.is_critical ? "CRITICAL" : "STANDARD",
    requiredThreshold: 0.80,
    pageNumber: field.page_number || 1,
    bbox: field.bounding_box || { x: 80, y: 200, w: 400, h: 60 },
    stages: {
      s1_opencv: { title: "1. OpenCV", status: "completed", method: "Page Alignment", value: "Aligned", confidence: 1.0, cropText: value || "—" },
      s2_ocr: { title: "2. Regional", status: "completed", method: method, value: value || "—", confidence: confidence ?? 0, cropText: value || "—" },
      s3_retry: { title: "3. Retry", status: "skipped", method: "N/A", value: value || "—", confidence: confidence ?? 0 },
      s4_vlm: { title: "4. Compact", status: "skipped", method: "N/A", value: "N/A", confidence: 1.0 },
      s5_hitl: {
        title: "5. Human Review",
        status: needsHitl ? "active" : "completed",
        method: needsHitl ? "HUMAN REVIEW REQUIRED" : "Auto-Validated",
        value: needsHitl ? (value || "Awaiting Reviewer Action") : (value || "—"),
        confidence: needsHitl ? (confidence ?? 0) : (confidence ?? 1),
      },
    },
    whyEscalated: needsHitl
      ? `Live extraction for ${field.field_name} requires review (validation=${validation}, confidence=${confLabel}).`
      : `Live extraction accepted for ${field.field_name} (validation=${validation}, confidence=${confLabel}).`,
    cost: "—",
    latency: "—",
    reviewTaskId: null,
  };
}

function buildLiveDocument(doc, fields) {
  const byPage = new Map();
  for (const field of fields || []) {
    const page = field.page_number || 1;
    if (!byPage.has(page)) byPage.set(page, []);
    byPage.get(page).push(stageFromField(field));
  }
  const pages = Array.from(byPage.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([pageNumber, pageFields]) => ({
      pageNumber,
      title: `Page ${pageNumber}: ${doc.detected_format || "Claim"}`,
      classification: doc.detected_format || "CLAIM_FORM",
      qualityScore: typeof doc.average_confidence === "number" ? doc.average_confidence : 0,
      fields: pageFields,
    }));
  if (pages.length === 0) {
    pages.push({
      pageNumber: 1,
      title: `Page 1: ${doc.detected_format || "Claim"} (no fields yet)`,
      classification: doc.detected_format || "CLAIM_FORM",
      qualityScore: 0,
      fields: [],
    });
  }
  const patient = doc.patient_name || "Unknown patient";
  return {
    id: doc.document_id,
    name: `${patient} · ${doc.source_filename || doc.document_id}`,
    pages,
  };
}

async function loadLiveDocuments() {
  const statusEl = document.querySelector(".status-pill span:last-child");
  try {
    const listRes = await fetch("/api/documents");
    if (!listRes.ok) throw new Error(`documents ${listRes.status}`);
    const docs = await listRes.json();
    Object.keys(DOCUMENTS).forEach((k) => delete DOCUMENTS[k]);
    for (const doc of docs) {
      let fields = [];
      try {
        const resultRes = await fetch(`/api/documents/${doc.document_id}/results`);
        if (resultRes.ok) {
          const payload = await resultRes.json();
          fields = payload.fields || [];
        }
      } catch (_) {}
      DOCUMENTS[doc.document_id] = buildLiveDocument(doc, fields);
    }
    if (statusEl) {
      statusEl.textContent = docs.length
        ? `Live data · ${docs.length} document${docs.length === 1 ? "" : "s"}`
        : "Live data · no ingested documents";
    }
  } catch (err) {
    console.error("Failed to load live documents", err);
    if (statusEl) statusEl.textContent = "Live API unavailable";
  }
}

let state = {
  doc: { id: "empty", name: "No live documents", pages: [{ pageNumber: 1, title: "Page 1", classification: "EMPTY", qualityScore: 0, fields: [] }] },
  currentPageIdx: 0,
  currentField: null,
  currentStageIdx: 0,
  zoomLevel: 1.0
};

function selectFirstAvailable() {
  const docs = Object.values(DOCUMENTS);
  if (!docs.length) {
    state.doc = { id: "empty", name: "No live documents", pages: [{ pageNumber: 1, title: "Page 1", classification: "EMPTY", qualityScore: 0, fields: [] }] };
    state.currentPageIdx = 0;
    state.currentField = null;
    state.currentStageIdx = 0;
    return;
  }
  state.doc = docs[0];
  state.currentPageIdx = 0;
  state.currentField = state.doc.pages[0]?.fields?.[0] || null;
  state.currentStageIdx = 0;
}

document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  setupEventListeners();
  await loadLiveDocuments();
  selectFirstAvailable();
  renderDocSelectorOptions();
  renderPageTabBar();
  renderFieldList();
  renderCanvas();
  renderPipeline();
  renderDiagnostics();
  renderCostLadder();
});

function initTheme() {
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'light') {
    document.body.classList.add('light-theme');
  }
}

function toggleTheme() {
  document.body.classList.toggle('light-theme');
  const isLight = document.body.classList.contains('light-theme');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
}

function renderDocSelectorOptions() {
  const sel = document.getElementById("doc-selector");
  if (!sel) return;
  const docs = Object.values(DOCUMENTS);
  if (!docs.length) {
    sel.innerHTML = `<option value="empty">No live documents available</option>`;
    return;
  }
  sel.innerHTML = docs.map(d => `
    <option value="${d.id}" ${d.id === state.doc.id ? 'selected' : ''}>${d.name}</option>
  `).join("");
}

function changeDocument(docId) {
  if (DOCUMENTS[docId]) {
    state.doc = DOCUMENTS[docId];
    state.currentPageIdx = 0;
    state.currentField = state.doc.pages[0]?.fields?.[0] || null;
    state.currentStageIdx = 0;
    renderPageTabBar();
    renderFieldList();
    renderCanvas();
    renderPipeline();
    renderDiagnostics();
    renderCostLadder();
  }
}

function selectPage(pageIdx) {
  state.currentPageIdx = pageIdx;
  const page = state.doc.pages[pageIdx];
  if (page && page.fields.length > 0) {
    state.currentField = page.fields[0];
  }
  state.currentStageIdx = 0;
  
  renderPageTabBar();
  renderFieldList();
  renderCanvas();
  renderPipeline();
  renderDiagnostics();
  renderCostLadder();
}

function selectField(fieldId) {
  let foundField = null;
  state.doc.pages.forEach(p => {
    const f = p.fields.find(field => field.id === fieldId);
    if (f) foundField = f;
  });
  
  if (foundField) {
    state.currentField = foundField;
    state.currentStageIdx = 0;
    renderFieldList();
    updateBBoxOverlay();
    renderPipeline();
    renderDiagnostics();
    renderCostLadder();
  }
}

function renderPageTabBar() {
  const container = document.getElementById("page-tab-bar");
  if (!container) return;
  container.innerHTML = state.doc.pages.map((p, idx) => `
    <div class="page-tab ${idx === state.currentPageIdx ? 'active' : ''}" onclick="selectPage(${idx})">
      <span>${p.title}</span>
      <span class="page-badge">${p.classification}</span>
    </div>
  `).join("");

  const pageLabel = document.getElementById("current-page-label");
  if (pageLabel) pageLabel.innerText = `Page ${state.currentPageIdx + 1}`;
}

function renderFieldList() {
  const container = document.getElementById("field-list");
  if (!container) return;
  const currentPageFields = state.doc.pages[state.currentPageIdx]?.fields || [];

  if (currentPageFields.length === 0) {
    container.innerHTML = `<div style="padding: 1rem; color: var(--text-secondary); font-size: 0.8rem;">No extracted fields on this page.</div>`;
    return;
  }

  container.innerHTML = currentPageFields.map(f => {
    const confPct = Math.round(f.stages.s5_hitl.confidence * 100);
    const confColor = f.stages.s5_hitl.confidence >= f.requiredThreshold ? "#10b981" : "#f43f5e";

    return `
      <div class="field-card ${f.id === state.currentField.id ? 'active' : ''}" onclick="selectField('${f.id}')">
        <div class="field-card-header">
          <span class="field-name">${f.label}</span>
          <span class="badge ${f.criticality === 'CRITICAL' ? 'badge-critical' : 'badge-noncritical'}">${f.criticality}</span>
        </div>
        <div class="field-card-value">${f.stages.s5_hitl.value}</div>
        <div class="confidence-bar-bg">
          <div class="confidence-bar-fill" style="width: ${confPct}%; background: ${confColor};"></div>
        </div>
        <div class="field-card-meta">
          <span>Req. Conf: ${(f.requiredThreshold * 100).toFixed(0)}%</span>
          <span style="font-weight: 700; color: ${confColor}">${f.stages.s5_hitl.status.toUpperCase()}</span>
        </div>
      </div>
    `;
  }).join("");
}


function liveFieldValue(names, fallback = "—") {
  const pages = state.doc?.pages || [];
  for (const page of pages) {
    for (const field of page.fields || []) {
      if (names.includes(field.name) || names.includes(field.id)) {
        return field.stages?.s5_hitl?.value || field.stages?.s2_ocr?.value || fallback;
      }
    }
  }
  return fallback;
}

function renderCanvas() {
  const holder = document.getElementById("svg-canvas-holder");
  if (!holder) return;
  const page = state.doc.pages[state.currentPageIdx];

  let pageContent = "";
  if (state.doc.id.includes("ub04")) {
    pageContent = `
      <rect x="0" y="0" width="1712" height="2214" fill="#f8fafc" />
      <rect x="50" y="50" width="1612" height="100" fill="#cbd5e1" rx="4" />
      <text x="80" y="110" font-family="sans-serif" font-size="32" font-weight="bold" fill="#0f172a">UB-04 INSTITUTIONAL CLAIM (CMS-1450) — PAGE ${page.pageNumber}</text>
      <rect x="50" y="180" width="1612" height="1800" fill="#ffffff" stroke="#cbd5e1" stroke-width="2" />
      <text x="1200" y="260" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">FL 56 NPI: ${liveFieldValue(["billing_provider_npi","provider_npi"])}</text>
      <text x="1400" y="150" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">FL 4 TOB: 0111</text>
    `;
  } else {
    pageContent = `
      <rect x="0" y="0" width="1712" height="2214" fill="#f8fafc" />
      <rect x="50" y="50" width="1612" height="100" fill="#e2e8f0" rx="4" />
      <text x="80" y="110" font-family="sans-serif" font-size="32" font-weight="bold" fill="#0f172a">HEALTH INSURANCE CLAIM FORM (NUCC 02/12) — PAGE ${page.pageNumber}</text>
      
      <!-- Box 1a Insured ID -->
      <rect x="980" y="210" width="650" height="70" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="1000" y="255" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">1a. INSURED ID: ${liveFieldValue(["insured_id_number","insured_id","member_id"])}</text>
      
      <!-- Box 2 Patient Name -->
      <rect x="50" y="310" width="600" height="90" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="70" y="340" font-family="sans-serif" font-size="20" font-weight="bold" fill="#334155">2. PATIENT'S NAME</text>
      <text x="80" y="380" font-family="sans-serif" font-size="32" font-weight="bold" fill="#0284c7">${(state.currentField?.stages?.s5_hitl?.value || state.doc.name || "LIVE CLAIM").toString().slice(0, 40)}</text>
      
      <!-- Box 24D CPT Code -->
      <rect x="50" y="1100" width="1612" height="150" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <rect x="900" y="1150" width="150" height="70" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="70" y="1140" font-family="sans-serif" font-size="20" font-weight="bold" fill="#334155">24. A-J SERVICE LINES</text>
      <text x="920" y="1195" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">${liveFieldValue(["procedure_code","cpt_code","service_line_1_cpt"], "—")}</text>

      <!-- Box 25 Federal Tax ID -->
      <rect x="50" y="1810" width="550" height="80" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="70" y="1860" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">25. TAX ID: ${liveFieldValue(["federal_tax_id","billing_provider_tax_id"])}</text>

      <!-- Box 28 Total Charge -->
      <rect x="1150" y="1810" width="480" height="80" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="1180" y="1860" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">28. TOTAL: ${liveFieldValue(["total_charge","total_claim_charge_amount"])}</text>
      
      <!-- Box 31 Signature -->
      <rect x="1050" y="1150" width="600" height="100" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="1070" y="1185" font-family="sans-serif" font-size="20" font-weight="bold" fill="#334155">31. SIGNATURE OF PHYSICIAN</text>
      <path d="M 1100 1230 Q 1150 1200 1200 1230 T 1300 1220 T 1400 1240" fill="transparent" stroke="#0284c7" stroke-width="4"/>

      <!-- Box 33a NPI -->
      <rect x="50" y="1950" width="550" height="80" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" rx="4"/>
      <text x="70" y="2000" font-family="sans-serif" font-size="28" font-weight="bold" fill="#0284c7">33a. NPI: ${liveFieldValue(["rendering_provider_npi","billing_provider_npi","provider_npi"])}</text>
    `;
  }

  holder.innerHTML = `
    <svg class="claim-img" viewBox="0 0 1712 2214" width="580" height="750">
      ${pageContent}
    </svg>
  `;

  updateBBoxOverlay();
}

function updateBBoxOverlay() {
  const overlay = document.getElementById("bbox-overlay");
  const field = state.currentField;
  if (!overlay) return;

  if (!field || field.pageNumber !== state.currentPageIdx + 1) {
    overlay.style.display = "none";
    return;
  }

  overlay.style.display = "block";
  const canvasWidth = 1712;
  const canvasHeight = 2214;
  
  overlay.style.left = `${(field.bbox.x / canvasWidth) * 100}%`;
  overlay.style.top = `${(field.bbox.y / canvasHeight) * 100}%`;
  overlay.style.width = `${(field.bbox.w / canvasWidth) * 100}%`;
  overlay.style.height = `${(field.bbox.h / canvasHeight) * 100}%`;
}

function zoomIn() {
  state.zoomLevel = Math.min(state.zoomLevel + 0.2, 2.5);
  applyZoom();
}

function zoomOut() {
  state.zoomLevel = Math.max(state.zoomLevel - 0.2, 0.6);
  applyZoom();
}

function resetZoom() {
  state.zoomLevel = 1.0;
  applyZoom();
}

function applyZoom() {
  const wrapper = document.getElementById("canvas-wrapper");
  if (wrapper) wrapper.style.transform = `scale(${state.zoomLevel})`;
  const txt = document.getElementById("zoom-level-text");
  if (txt) txt.innerText = `${Math.round(state.zoomLevel * 100)}%`;
}

function renderPipeline() {
  const container = document.getElementById("pipeline-container");
  const field = state.currentField;
  if (!container) return;
  if (!field) {
    container.innerHTML = `<div style="padding:1rem;color:var(--text-secondary);font-size:0.8rem;">Select a live extracted field to inspect pipeline stages.</div>`;
    return;
  }

  const stages = [
    field.stages.s1_opencv,
    field.stages.s2_ocr,
    field.stages.s3_retry,
    field.stages.s4_vlm,
    field.stages.s5_hitl
  ];

  container.innerHTML = stages.map((s, idx) => {
    let statusClass = "";
    if (idx < state.currentStageIdx) statusClass = "completed";
    else if (idx === state.currentStageIdx) statusClass = "active";
    if (s.status === "failed") statusClass += " failed";

    return `
      <div class="pipeline-stage ${statusClass}">
        <div class="stage-number">STAGE ${idx + 1}</div>
        <div class="stage-title">${s.title}</div>
        <div class="stage-crop-preview">${s.cropText || s.value}</div>
        <div class="stage-details">
          <div class="stage-detail-row">
            <span>Method:</span>
            <span class="stage-detail-val">${s.method}</span>
          </div>
          <div class="stage-detail-row">
            <span>Conf:</span>
            <span class="stage-detail-val" style="color: ${s.confidence >= field.requiredThreshold ? '#10b981' : '#f43f5e'}">
              ${(s.confidence * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function completeHitlReview() {
  const field = state.currentField;
  if (!field) return;
  const inputEl = document.getElementById("hitl-input-value");
  const val = inputEl ? inputEl.value.trim() : (field.stages.s2_ocr.value || "");

  field.stages.s5_hitl.value = val;
  field.stages.s5_hitl.confidence = 1.0;
  field.stages.s5_hitl.status = "completed";
  field.stages.s5_hitl.method = "APPROVED_BY_OPERATOR";
  field.whyEscalated = `✓ HITL Review Completed & Approved by Human Operator ("${val}"). Confidence set to 100%. Task closed.`;

  if (field.reviewTaskId) {
    fetch(`/review-api/review-tasks/${field.reviewTaskId}/correct?reviewer=reviewer@company.com`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-User-Role": "reviewer" },
      body: JSON.stringify({ new_value: val, reason: "Approved in transformation visualizer", expected_version: 0 })
    }).catch(() => {});
  }

  renderFieldList();
  renderPipeline();
  renderDiagnostics();
  renderCostLadder();
}

function renderDiagnostics() {
  const container = document.getElementById("diagnostic-box");
  const field = state.currentField;
  if (!container) return;
  if (!field) {
    container.className = "diagnostic-box";
    container.innerHTML = `<div class="diag-header"><span>No field selected</span></div><div class="diag-reason">Ingest documents through the Claims IDP UI to populate live transformation stages.</div>`;
    return;
  }

  const stage = Object.values(field.stages)[state.currentStageIdx];

  let boxClass = "success";
  if (stage.status === "failed" || stage.status === "active") boxClass = "danger";

  const isHitlActive = field.stages.s5_hitl.status === "active" || field.stages.s5_hitl.method === "APPROVED_BY_OPERATOR";
  const defaultHitlValue = field.stages.s4_vlm.value && field.stages.s4_vlm.value !== "N/A" ? field.stages.s4_vlm.value : (field.stages.s2_ocr.value || "");

  container.className = `diagnostic-box ${boxClass}`;
  container.innerHTML = `
    <div class="diag-header">
      <span>${field.label} (Page ${field.pageNumber}) — Stage ${state.currentStageIdx + 1}: ${stage.title}</span>
    </div>
    <div class="diag-reason">
      <strong>Current Value:</strong> <code style="color: var(--cyan-bright)">${stage.value}</code><br>
      <strong>Confidence:</strong> ${(stage.confidence * 100).toFixed(0)}% (Required: ${(field.requiredThreshold * 100).toFixed(0)}%)
      ${stage.error ? `<br><span style="color: var(--rose-bright)">⚠️ ${stage.error}</span>` : ''}
    </div>

    ${isHitlActive ? `
      <div style="margin: 0.85rem 0; padding: 0.75rem; background: rgba(15, 23, 42, 0.8); border: 1px solid var(--cyan-bright); border-radius: 8px;">
        <div style="font-size: 0.78rem; font-weight: 700; color: var(--cyan-bright); margin-bottom: 0.4rem;">
          ✋ INTERACTIVE HUMAN-IN-THE-LOOP (HITL) REVIEW
        </div>
        <label style="font-size: 0.72rem; color: var(--text-secondary); display: block; margin-bottom: 0.3rem;">
          Verified / Corrected Value:
        </label>
        <input id="hitl-input-value" type="text" value="${stage.value !== 'Awaiting Reviewer Action' ? stage.value : defaultHitlValue}" 
               style="width: 100%; padding: 0.45rem 0.75rem; background: #020617; border: 1px solid var(--border-glass); border-radius: 6px; color: #ffffff; font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; margin-bottom: 0.6rem; outline: none;" />
        
        <button onclick="completeHitlReview()" style="width: 100%; padding: 0.5rem 1rem; background: linear-gradient(135deg, #10b981, #059669); color: #ffffff; font-weight: 700; border: none; border-radius: 6px; cursor: pointer; font-size: 0.82rem; box-shadow: 0 0 12px rgba(16, 185, 129, 0.4);">
          ✓ Complete HITL Review & Save Decision
        </button>
      </div>
    ` : ''}

    <div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 0.3rem;">
      <strong>Why Escalated / Transformation Notes:</strong>
    </div>
    <p style="font-size: 0.8rem; line-height: 1.35; color: var(--text-primary);">
      ${field.whyEscalated}
    </p>
  `;
}

function renderCostLadder() {
  const container = document.getElementById("cost-ladder");
  const currentStage = state.currentStageIdx;
  if (!container) return;
  
  const ladder = [
    { name: "1. OpenCV Alignment", cost: "$0.0000", time: "8ms" },
    { name: "2. Regional PaddleOCR", cost: "$0.0001", time: "35ms" },
    { name: "3. Preprocessing Retry", cost: "$0.0002", time: "65ms" },
    { name: "4. Compact Vision-LLM", cost: "$0.0022", time: "420ms" },
    { name: "5. Human Review (HITL)", cost: "$0.1500", time: "45000ms" }
  ];

  container.innerHTML = ladder.map((item, idx) => `
    <div class="ladder-item ${idx === currentStage ? 'active' : ''}">
      <span class="ladder-name">${item.name}</span>
      <div>
        <span style="color: var(--text-secondary); font-size: 0.7rem; margin-right: 0.4rem">${item.time}</span>
        <span class="ladder-cost">${item.cost}</span>
      </div>
    </div>
  `).join("");
}

function setupEventListeners() {
  const btnPrev = document.getElementById("btn-prev");
  const btnNext = document.getElementById("btn-next");

  if (btnPrev) {
    btnPrev.addEventListener("click", () => {
      if (state.currentStageIdx > 0) {
        state.currentStageIdx--;
        renderPipeline();
        renderDiagnostics();
        renderCostLadder();
      }
    });
  }

  if (btnNext) {
    btnNext.addEventListener("click", () => {
      if (state.currentStageIdx < 4) {
        state.currentStageIdx++;
        renderPipeline();
        renderDiagnostics();
        renderCostLadder();
      }
    });
  }
}
