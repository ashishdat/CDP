"""Build the healthcare AI hackathon submission without embedding source or PHI."""

from __future__ import annotations

import json
import shutil
import textwrap
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "submission"
PACKAGE_NAME = "Name_HealthcareAIHackathon"
PACKAGE_DIR = OUTPUT_ROOT / PACKAGE_NAME
METRICS_PATH = ROOT / "evaluation_results" / "evaluation.json"

NAVY = "#071725"
PANEL = "#10283A"
PANEL_2 = "#16364A"
TEAL = "#42D7B3"
BLUE = "#63A8FF"
PURPLE = "#B08BFF"
WHITE = "#F3F8FC"
MUTED = "#A4B6C7"
LINE = "#29465B"
RED = "#FF8995"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "arialbd.ttf" if bold else "arial.ttf"
    path = Path("C:/Windows/Fonts") / filename
    return ImageFont.truetype(str(path), size)


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False) or [""]


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int,
          color: str = WHITE, *, bold: bool = False, width: int | None = None,
          spacing: int = 8) -> int:
    x, y = xy
    lines = _wrap(text, width) if width else text.splitlines()
    font = _font(size, bold=bold)
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        y += size + spacing
    return y


def _page(title: str, eyebrow: str, page_number: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1240, 1754), NAVY)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1240, 14), fill=TEAL)
    _text(draw, (72, 60), "CLAIMS INTELLIGENCE", 18, TEAL, bold=True)
    _text(draw, (72, 112), eyebrow.upper(), 16, MUTED, bold=True)
    _text(draw, (72, 148), title, 44, WHITE, bold=True, width=38, spacing=10)
    draw.line((72, 285, 1168, 285), fill=LINE, width=2)
    _text(draw, (72, 1690), "Healthcare AI Hackathon · Governed IDP Platform", 14, MUTED)
    _text(draw, (1110, 1690), f"{page_number:02d}", 14, TEAL, bold=True)
    return image, draw


def _card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str,
          body: str, *, accent: str = TEAL, metric: str | None = None) -> None:
    draw.rounded_rectangle(box, radius=18, fill=PANEL, outline=LINE, width=2)
    x1, y1, x2, _ = box
    draw.rectangle((x1, y1, x1 + 8, box[3]), fill=accent)
    _text(draw, (x1 + 30, y1 + 25), title.upper(), 15, accent, bold=True)
    if metric:
        _text(draw, (x1 + 30, y1 + 62), metric, 34, WHITE, bold=True)
        _text(draw, (x1 + 30, y1 + 112), body, 17, MUTED, width=max(28, (x2 - x1) // 11))
    else:
        _text(draw, (x1 + 30, y1 + 67), body, 18, MUTED, width=max(28, (x2 - x1) // 11), spacing=8)


def _bullets(draw: ImageDraw.ImageDraw, x: int, y: int, items: list[str], *, width: int = 70,
             size: int = 20) -> int:
    for item in items:
        draw.ellipse((x, y + 8, x + 9, y + 17), fill=TEAL)
        y = _text(draw, (x + 24, y), item, size, MUTED, width=width, spacing=8) + 14
    return y


def executive_summary(metrics: dict) -> None:
    pages: list[Image.Image] = []
    image, draw = _page("Executive Summary", "Healthcare claims intelligence", 1)
    _text(draw, (72, 350), "High-accuracy extraction.\nEvidence-first automation.\nEnterprise scale.", 52, WHITE, bold=True, spacing=16)
    _text(draw, (72, 620), "A governed, field-level healthcare claims IDP platform combining template alignment, cascading OCR, deterministic validation, crop-only multimodal fallback and safe abstention.", 24, MUTED, width=65, spacing=12)
    _card(draw, (72, 1010, 402, 1285), "Current sample", "239 / 239 normalized fields", metric="100.00%")
    _card(draw, (425, 1010, 755, 1285), "Measured provider cost", "Azure token estimate; compute excluded", metric="$0.003663/page", accent=BLUE)
    _card(draw, (778, 1010, 1168, 1285), "Frozen replay", "Candidate assembly and reconciliation", metric="7.665 pages/sec", accent=PURPLE)
    _text(draw, (72, 1370), "Important: evidence-derived accuracy is 99.58%; one benchmark-only user-confirmed closure has no production authority. Replay timing excludes fresh OCR/LLM calls.", 17, RED, width=95)
    pages.append(image)

    image, draw = _page("Problem Understanding", "Why claims IDP is difficult", 2)
    _bullets(draw, 85, 350, [
        "Healthcare claims mix structured CMS-1500/UB-04 forms with invoices, statements, receipts and attachments.",
        "Scans contain skew, compression, handwriting, checkboxes, clipped values, repeated labels and multi-page evidence.",
        "A plausible OCR string can still be the wrong field, wrong component, wrong page or unsafe semantic inference.",
        "Critical identity and clinical fields require evidence provenance, validation and controlled abstention—not confidence alone.",
        "Enterprise deployment must balance accuracy, review workload, cost, latency, auditability and PHI governance.",
    ], width=82, size=23)
    _card(draw, (72, 1180, 1168, 1450), "Design principle", "Generate broad evidence, apply narrow deterministic acceptance, and fail closed when critical evidence remains unresolved.", accent=TEAL)
    pages.append(image)

    image, draw = _page("Solution Overview", "Hybrid evidence pipeline", 3)
    stages = [
        ("1", "Prepare", "Decode, deskew, quality score"),
        ("2", "Route", "Classify every page and align forms"),
        ("3", "Extract", "Regional PaddleOCR + Tesseract"),
        ("4", "Escalate", "Handwriting OCR and crop-only LLM"),
        ("5", "Validate", "Rules, semantics and references"),
        ("6", "Finalize", "Reconcile, abstain or review"),
    ]
    y = 350
    for index, title, body in stages:
        draw.rounded_rectangle((72, y, 1168, y + 150), radius=18, fill=PANEL, outline=LINE, width=2)
        draw.ellipse((98, y + 39, 170, y + 111), fill=TEAL)
        _text(draw, (121, y + 55), index, 25, NAVY, bold=True)
        _text(draw, (205, y + 30), title, 23, WHITE, bold=True)
        _text(draw, (205, y + 72), body, 19, MUTED)
        if y < 1190:
            _text(draw, (605, y + 150), "↓", 24, TEAL, bold=True)
        y += 190
    pages.append(image)

    image, draw = _page("Key Innovations", "What differentiates the solution", 4)
    cards = [
        ("Field-page evidence routing", "Every required field evaluates every eligible page; different fields may originate on different pages."),
        ("Candidate-first reconciliation", "OCR engines generate evidence independently; deterministic eligibility and dominance rules select safely."),
        ("Geometry-aware extraction", "Template homography, anchor-relative crops, checkbox pixel scoring and complete-block address/name parsing."),
        ("Semantic separation", "Visible OCR, inferred semantic state and fixed-width sentinel projection remain independent and auditable."),
        ("Cost-aware escalation", "Open-source regional OCR first; specialized models and Azure GPT-4o receive unresolved crops only."),
        ("Governed promotion", "New routes start review-only and require frozen holdout, zero critical false accepts and rollback-ready canaries."),
    ]
    for idx, (title, body) in enumerate(cards):
        col, row = idx % 2, idx // 2
        x, y = 72 + col * 555, 350 + row * 350
        _card(draw, (x, y, x + 525, y + 310), title, body, accent=TEAL if col == 0 else BLUE)
    pages.append(image)

    image, draw = _page("Results Summary", "Measured benchmark", 5)
    op, cost = metrics["operational_metrics"], metrics["cost_analysis"]
    results = [
        ("Normalized accuracy", f"{op['accuracy']:.2%}", "Current sample; includes one benchmark-only confirmed closure"),
        ("Evidence-derived accuracy", f"{metrics['raw_exact_match_accuracy']:.2%}", "238 / 239 from generated evidence"),
        ("Precision / recall", f"{op['precision']:.2%} / {op['recall']:.2%}", "Normalized field outcomes"),
        ("Frozen replay throughput", f"{op['pages_per_second']:.3f} pages/sec", "Excludes fresh model inference and network latency"),
        ("Replay latency", f"{op['average_latency_seconds']:.3f} sec/page", "30 pages, 239 fields"),
        ("Measured provider cost", f"${cost['total_cost_per_page_usd']:.6f}/page", "Token estimate; CPU/storage/review unmetered"),
    ]
    for idx, (title, value, note) in enumerate(results):
        col, row = idx % 2, idx // 2
        x, y = 72 + col * 555, 350 + row * 320
        _card(draw, (x, y, x + 525, y + 280), title, note, metric=value, accent=TEAL if idx < 2 else BLUE)
    _text(draw, (72, 1370), "Safety: critical false accepts = 0. Unresolved evidence remains fail-closed pending authorized references and holdout-approved promotion.", 18, RED, width=95)
    pages.append(image)

    image, draw = _page("Why This Solution Should Win", "Balanced engineering", 6)
    _bullets(draw, 85, 350, [
        "Accuracy with proof: every value retains page, crop, model, preprocessing, validation and decision lineage.",
        "Lowest practical cost: regional open-source OCR handles the common path; cloud multimodal inference is field-level and exceptional.",
        "Enterprise safety: critical fields fail closed, ground truth is excluded from inference and benchmark-only corrections have no production authority.",
        "Scalable simplicity: stateless workers, object-storage artifacts, Kafka-compatible events, outbox delivery and KEDA horizontal scaling.",
        "Operational transparency: accuracy, coverage, review, cost, timing and promotion readiness are shown separately rather than blended into one headline.",
        "Extensible architecture: model, reference, validation, layout and output specifications are versioned contracts—not hard-coded workflow forks.",
    ], width=82, size=22)
    _card(draw, (72, 1280, 1168, 1500), "Winning proposition", "A pragmatic system that uses AI where it adds evidence and deterministic engineering where trust matters most.", accent=TEAL)
    pages.append(image)
    pages[0].save(PACKAGE_DIR / "01_Executive_Summary.pdf", save_all=True, append_images=pages[1:], resolution=150)


def architecture_document(metrics: dict) -> None:
    pages: list[Image.Image] = []
    image, draw = _page("Architecture Document", "Governed claims IDP", 1)
    _text(draw, (72, 380), "Evidence-first architecture for\n100M+ pages per year", 52, WHITE, bold=True, spacing=18)
    _text(draw, (72, 620), "Stateless processing · versioned contracts · field-level provenance · cost-aware model routing · fail-closed finalization", 25, MUTED, width=67, spacing=12)
    _card(draw, (72, 1030, 1168, 1320), "Architecture objective", "Scale independent CPU, OCR, layout, GPU and VLM pools while preserving deterministic validation and auditable field evidence.", accent=TEAL)
    pages.append(image)

    image, draw = _page("End-to-End Architecture", "Logical data flow", 2)
    stages = ["Ingestion API", "Object storage", "Page preparation", "Classification & alignment", "Regional candidate providers", "Validation & reconciliation", "Reference / review", "JSON · CSV · NSF/UB92"]
    for idx, stage in enumerate(stages):
        col, row = idx % 2, idx // 2
        x, y = 90 + col * 570, 350 + row * 280
        draw.rounded_rectangle((x, y, x + 490, y + 190), radius=18, fill=PANEL, outline=TEAL if idx in (0, 7) else LINE, width=3)
        _text(draw, (x + 25, y + 25), f"{idx + 1:02d}", 15, TEAL, bold=True)
        _text(draw, (x + 25, y + 70), stage, 23, WHITE, bold=True, width=28)
        if idx < len(stages) - 1:
            _text(draw, (610, y + 72), "→" if col == 0 else "↓", 28, TEAL, bold=True)
    _text(draw, (72, 1510), "All large payloads remain in object storage; event messages carry content-addressed URIs and version identifiers only.", 18, MUTED, width=95)
    pages.append(image)

    image, draw = _page("Component Design", "Deployable services and shared contracts", 3)
    components = [
        ("APIs", "Ingestion, review and output services; idempotent document intake and signed evidence access."),
        ("Worker pools", "Preparation, page routing, structured/unstructured extraction, retry, validation, VLM and output generation."),
        ("Shared packages", "Domain models, events, storage, security, templates, validators, routing, references and fixed-width output."),
        ("Control plane", "Versioned YAML policies for models, templates, thresholds, semantic rules, costs and route promotion."),
        ("Data plane", "Postgres metadata, S3-compatible object storage, Kafka-compatible events, Redis cache and append-only audit."),
        ("Observability", "Prometheus metrics, structured PHI-redacted logs, traces, Grafana dashboards and safety alerts."),
    ]
    for idx, (title, body) in enumerate(components):
        col, row = idx % 2, idx // 2
        x, y = 72 + col * 555, 350 + row * 350
        _card(draw, (x, y, x + 525, y + 310), title, body, accent=BLUE if col else TEAL)
    pages.append(image)

    image, draw = _page("OCR & Vision Strategy", "Cascading evidence generation", 4)
    cascade = [
        ("Regional PaddleOCR", "Primary printed-text candidate generation on original and enhanced crops.", TEAL),
        ("PP-OCR next", "Recognition-only v5/v6 shadow models with line segmentation for multiline blocks.", BLUE),
        ("Constrained Tesseract", "Independent architecture for numeric, date, code and currency fields.", BLUE),
        ("Handwriting route", "Writing-type detection, TrOCR review evidence and domain fine-tuning only after label gates.", PURPLE),
        ("Azure GPT-4o vision", "Authorized crop-only fallback with strict JSON schema, temperature zero and abstention.", PURPLE),
        ("Exception closure", "Final unresolved evidence with immutable corrections and independent approval for critical fields.", RED),
    ]
    y = 340
    for idx, (title, body, color) in enumerate(cascade):
        draw.rounded_rectangle((72, y, 1168, y + 175), radius=18, fill=PANEL, outline=color, width=2)
        _text(draw, (98, y + 30), f"LEVEL {idx + 1}", 14, color, bold=True)
        _text(draw, (250, y + 25), title, 22, WHITE, bold=True)
        _text(draw, (250, y + 67), body, 18, MUTED, width=70)
        y += 205
    pages.append(image)

    image, draw = _page("Routing & Business Validation", "Confidence is evidence—not authority", 5)
    _card(draw, (72, 350, 1168, 590), "Eligibility before scoring", "Routing-only and empty candidates are ineligible. Hard-valid regional evidence dominates invalid values. Sentinels cannot compete as visible OCR.", accent=TEAL)
    _card(draw, (72, 630, 1168, 870), "Field-specific validation", "Calendar dates · NPI checksum · ZIP format · currency reconciliation · ICD/CPT syntax · state codes · checkbox geometry · semantic blank rules", accent=BLUE)
    _card(draw, (72, 910, 1168, 1150), "Critical-field policy", "Independent OCR agreement plus hard validation and authorized reference verification. Contradictions or unreadable crops route to review.", accent=RED)
    _card(draw, (72, 1190, 1168, 1430), "Semantic projection", "PRESENT, BLANK, NOT_APPLICABLE, SAME_AS_PATIENT and UNKNOWN are resolved before any output-format sentinel is projected.", accent=PURPLE)
    pages.append(image)

    image, draw = _page("Cost Optimization & Scale", "100M+ pages per year", 6)
    yearly = 100_000_000
    daily = yearly / 365
    average_pps = yearly / (365 * 24 * 3600)
    _card(draw, (72, 350, 402, 600), "Annual volume", "Target workload", metric=f"{yearly/1_000_000:.0f}M pages")
    _card(draw, (425, 350, 755, 600), "Daily average", "Across 365 days", metric=f"{daily:,.0f} pages", accent=BLUE)
    _card(draw, (778, 350, 1168, 600), "Continuous average", "Before peak and redundancy factors", metric=f"{average_pps:.2f} pages/sec", accent=PURPLE)
    _bullets(draw, 85, 700, [
        "Scale workers independently by Kafka lag, CPU/GPU utilization and latency SLO using KEDA.",
        "Content-addressed storage and inference cache prevent duplicate processing by image/model/policy checksum.",
        "Run inexpensive preparation and OCR on CPU; reserve GPU/layout and cloud VLM for unresolved fields only.",
        "Batch regional model calls, reuse loaded models and autoscale down exceptional routes when queues are empty.",
        "Use multi-AZ Postgres, durable object storage, at-least-once events, idempotent consumers and transactional outbox delivery.",
        "Provision for peak traffic, replay backlog and deployment redundancy rather than the 3.17 pages/sec annual average alone.",
    ], width=82, size=21)
    pages.append(image)

    image, draw = _page("Failure & Exception Processing", "Operational resilience", 7)
    failures = [
        ("Unreadable / ambiguous", "Persist every crop variant and candidate; return INSUFFICIENT_EVIDENCE and create a review task."),
        ("Wrong page / incomplete inference", "Require per-field page completeness before routing; ambiguous critical pages cannot finalize."),
        ("Model/provider outage", "Timeout, circuit-break, retry with jitter, fall back to independent local engines, then controlled review."),
        ("Reference contradiction", "Block automatic acceptance, preserve compared attributes and route to accountable review."),
        ("Schema or validation failure", "Reject malformed output, retain provenance, emit a typed failure event and quarantine unsafe routes."),
        ("Drift or false accept", "Immediate field/family rollback, freeze artifacts, alert operators and require a new holdout promotion."),
    ]
    for idx, (title, body) in enumerate(failures):
        col, row = idx % 2, idx // 2
        x, y = 72 + col * 555, 350 + row * 350
        _card(draw, (x, y, x + 525, y + 310), title, body, accent=RED if idx in (0, 3, 5) else BLUE)
    pages.append(image)

    image, draw = _page("Security, Governance & Delivery", "Production controls", 8)
    _bullets(draw, 85, 350, [
        "PHI remains encrypted in approved storage; cloud providers receive unresolved field crops only after contractual authorization.",
        "Secrets are injected at runtime and excluded from source, reports, images and event payloads.",
        "Audit records capture model/config versions, candidate lineage, validation, reviewer actions and final disposition.",
        "Ground truth is unavailable during inference and holdout predictions are sealed before independent labels are joined.",
        "Promotion is field/family scoped with 5% canary, immediate rollback and zero critical false-accept requirement.",
        "Outputs include canonical JSON, CSV comparison and specification-driven NSF/UB92 fixed-width generation; X12 is adapter-based.",
    ], width=82, size=22)
    _card(draw, (72, 1290, 1168, 1510), "Source delivery", "Complete source, README, dependencies, configuration and Docker setup are submitted separately at github.com/ashneevai/CDP.", accent=TEAL)
    pages.append(image)
    pages[0].save(PACKAGE_DIR / "02_Architecture.pdf", save_all=True, append_images=pages[1:], resolution=150)


def _xlsx_cell(ref: str, value: object, style: int = 0) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def _sheet(rows: list[list[object]], widths: list[int]) -> str:
    columns = "".join(f'<col min="{i+1}" max="{i+1}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths))
    content = []
    for row_number, row in enumerate(rows, 1):
        cells = []
        for col_number, value in enumerate(row, 1):
            col = ""
            n = col_number
            while n:
                n, remainder = divmod(n - 1, 26)
                col = chr(65 + remainder) + col
            style = 1 if row_number == 1 else (2 if col_number == 1 else 0)
            cells.append(_xlsx_cell(f"{col}{row_number}", value, style))
        content.append(f'<row r="{row_number}" ht="24" customHeight="1">{"".join(cells)}</row>')
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols>{columns}</cols><sheetData>{"".join(content)}</sheetData><autoFilter ref="A1:{chr(64+len(widths))}{len(rows)}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews></worksheet>'''


def benchmark_xlsx(metrics: dict) -> None:
    op, cost = metrics["operational_metrics"], metrics["cost_analysis"]
    overall = [
        ["Metric", "Value", "Unit", "Measurement Scope / Notes"],
        ["Total Pages Processed", op["total_pages_processed"], "pages", "Current governed sample"],
        ["Total Fields Processed", metrics["field_count"], "fields", "Normalized field evaluation"],
        ["Processing Time", op["processing_time_seconds"], "seconds", op["measurement_note"]],
        ["Average Latency", op["average_latency_seconds"], "seconds/page", "Frozen production replay"],
        ["Pages per Second", op["pages_per_second"], "pages/second", "Frozen production replay"],
        ["Normalized Accuracy", op["accuracy"], "ratio", "239/239; includes one benchmark-only confirmed closure"],
        ["Evidence-derived Accuracy", metrics["raw_exact_match_accuracy"], "ratio", "238/239 independently generated evidence"],
        ["Precision", op["precision"], "ratio", "Micro precision over normalized field outcomes"],
        ["Recall", op["recall"], "ratio", "Micro recall over normalized field outcomes"],
        ["Critical False Accept Rate", metrics["critical_false_accept_rate"], "ratio", "Target and observed: zero"],
        ["Straight-through Processing", metrics["straight_through_processing_rate"], "ratio", "Governed automatic coverage"],
    ]
    cost_rows = [["Component", "Cost per Page (USD)", "Status", "Basis"]]
    for component in cost["components"]:
        cost_rows.append([component["name"], component["cost_per_page_usd"] if component["cost_per_page_usd"] is not None else "Not metered", component["status"], component["basis"]])
    cost_rows.extend([
        ["Total Measured", cost["total_cost_per_page_usd"], "MEASURED", cost["measurement_note"]],
        ["Actual Run Estimate", cost["actual_run_cost_usd"], "MEASURED", "Measured token usage using configured estimate rates"],
        ["Actual Invoice Cost", "Unavailable", "NOT METERED", "Requires Azure billing export"],
        ["1,000 Page Projection", cost["total_cost_per_page_usd"] * 1_000, "PROJECTED", "Assumes same escalation density/token profile"],
        ["1,000,000 Page Projection", cost["total_cost_per_page_usd"] * 1_000_000, "PROJECTED", "Excludes CPU, storage, network and review"],
    ])
    methodology = [
        ["Topic", "Definition"],
        ["Benchmark Scope", "30 pages and 239 normalized fields from the current governed sample."],
        ["Accuracy Caveat", "100% final current-sample benchmark includes one user-confirmed benchmark-only closure; evidence-derived accuracy is 99.58%."],
        ["Timing Caveat", op["measurement_note"]],
        ["Cost Caveat", cost["measurement_note"]],
        ["Ground-truth Leakage", "Ground truth was unavailable during inference and candidate generation."],
        ["Critical Safety", "Critical false accepts remained zero; unresolved critical evidence fails closed."],
        ["Safe Abstention", "Unresolved evidence remains fail-closed until authoritative verification or a holdout-approved route is available."],
        ["Reproducibility", "Metrics are projected from evaluation_results/evaluation.json and versioned policy artifacts."],
    ]
    sheets = [("Overall Metrics", overall, [34, 22, 20, 95]), ("Cost Analysis", cost_rows, [25, 24, 18, 100]), ("Methodology", methodology, [30, 120])]
    target = PACKAGE_DIR / "05_Benchmark.xlsx"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>''' + "".join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(sheets))) + "</Types>")
        archive.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        archive.writestr("xl/workbook.xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>''' + "".join(f'<sheet name="{escape(name)}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i, (name, _, _) in enumerate(sheets)) + "</sheets></workbook>")
        archive.writestr("xl/_rels/workbook.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">''' + "".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>' for i in range(len(sheets))) + f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr("xl/styles.xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="3"><font><sz val="11"/><name val="Arial"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Arial"/></font><font><b/><color rgb="FF42D7B3"/><sz val="11"/><name val="Arial"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF10283A"/></patternFill></fill></fills><borders count="1"><border/></borders><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" applyFill="1"/><xf numFmtId="0" fontId="2" fillId="0" borderId="0"/></cellXfs></styleSheet>''')
        for index, (_, rows, widths) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet(rows, widths))


def demo_video(metrics: dict) -> None:
    slides = [
        ("Healthcare Claims Intelligence", "Evidence-first IDP · live demonstration", ["30-page governed sample", "239 normalized fields", "React accuracy and cost dashboard"]),
        ("1 · Input Documents", "Structured and variable healthcare claims", ["CMS-1500 and UB-04", "Invoices, statements and receipts", "Multipage attachments and handwriting"]),
        ("2 · Preparation & Routing", "Every page is decoded, classified and aligned", ["Deskew and quality assessment", "Template homography and anchors", "Field-level page evidence completeness"]),
        ("3 · Cascading OCR", "Lowest-cost independent evidence first", ["Regional PaddleOCR", "PP-OCR v5/v6 recognition-only", "Constrained Tesseract", "Handwriting route when detected"]),
        ("4 · LLM / Vision Fallback", "Only unresolved crops escalate", ["Azure GPT-4o multimodal", "Strict schema and temperature zero", "PHI/region authorization gate", "Review-only until route promotion"]),
        ("5 · Validation & Reconciliation", "Confidence cannot bypass rules", ["Dates, NPI, ZIP, codes and amounts", "Checkbox pixel geometry", "Name/address block parsing", "Independent-engine agreement"]),
        ("6 · Output", "Auditable claim results", ["Canonical JSON", "CSV comparison report", "NSF / UB92 fixed-width", "Evidence manifest and review audit"]),
        ("7 · Accuracy Dashboard", "Current governed sample benchmark", [f"Accuracy: {metrics['normalized_field_accuracy']:.2%}", f"Evidence-derived: {metrics['raw_exact_match_accuracy']:.2%}", "Critical false accepts: 0"]),
        ("8 · Cost & Performance", "Transparent measurement scope", [f"Replay: {metrics['operational_metrics']['pages_per_second']:.3f} pages/sec", f"Latency: {metrics['operational_metrics']['average_latency_seconds']:.3f} sec/page", f"Provider cost: ${metrics['cost_analysis']['total_cost_per_page_usd']:.6f}/page"]),
        ("9 · Enterprise Scale", "Simple, governed horizontal scaling", ["Kafka-compatible queues and outbox", "Independent KEDA worker pools", "Content-addressed cache", "Fail-closed exception processing"]),
        ("10 · Closing", "Accuracy, economics and trust—in balance", ["Live report: http://localhost:8180/", "Source submitted separately", "github.com/ashneevai/CDP"]),
    ]
    width, height, fps = 1280, 720, 2
    total_frames = fps * 600
    frames_per_slide, remainder = divmod(total_frames, len(slides))
    writer = cv2.VideoWriter(str(PACKAGE_DIR / "03_Demo.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("OpenCV MP4 writer could not be initialized")
    for slide_index, (title, subtitle, bullets) in enumerate(slides):
        canvas = Image.new("RGB", (width, height), NAVY)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, width, 10), fill=TEAL)
        _text(draw, (55, 42), "CLAIMS INTELLIGENCE", 16, TEAL, bold=True)
        _text(draw, (1120, 42), f"{slide_index + 1:02d} / {len(slides):02d}", 14, MUTED, bold=True)
        _text(draw, (55, 112), title, 43, WHITE, bold=True, width=42)
        _text(draw, (55, 180), subtitle, 22, BLUE, bold=True, width=70)
        draw.rounded_rectangle((55, 250, 1225, 625), radius=22, fill=PANEL, outline=LINE, width=2)
        _bullets(draw, 95, 295, bullets, width=72, size=22)
        _text(draw, (55, 668), "Automated demo chapter · Use the live React console for interactive evidence", 13, MUTED)
        frame = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)
        frame_count = frames_per_slide + (1 if slide_index < remainder else 0)
        for _ in range(frame_count):
            writer.write(frame)
    writer.release()


def main() -> int:
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(parents=True)
    executive_summary(metrics)
    architecture_document(metrics)
    demo_video(metrics)
    benchmark_xlsx(metrics)
    archive_path = OUTPUT_ROOT / f"{PACKAGE_NAME}.zip"
    if archive_path.exists():
        archive_path.unlink()
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACKAGE_DIR.iterdir()):
            archive.write(path, path.name)
    print(json.dumps({
        "package": str(archive_path),
        "files": {path.name: path.stat().st_size for path in sorted(PACKAGE_DIR.iterdir())},
        "source_included": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
