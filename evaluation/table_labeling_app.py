"""Local-only table-cell labeling screen backed by append-only JSONL events."""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from packages.table_contracts import (
    ApprovalStatus,
    CellLabel,
    ReviewDisposition,
)
from packages.table_label_store import TableLabelStore

CONFIG = yaml.safe_load(Path("config/table_shadow_v2.yaml").read_text())
MANIFEST = Path(CONFIG["label_manifest_path"])
DETAILS = Path("evaluation_results/table_shadow_v2/details.json")
LABELS = Path(CONFIG["labels_path"])
CRITICAL = set(CONFIG["critical_columns"])
app = FastAPI(title="Local Table Cell Labeling", docs_url=None, redoc_url=None)


def _queue() -> list[dict]:
    manifest = [
        json.loads(line) for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    details = {
        item["candidate_id"]: item
        for item in json.loads(DETAILS.read_text(encoding="utf-8"))
    }
    events = TableLabelStore(LABELS).read_events()
    queue = []
    for item in manifest:
        # label_id is a review event, candidate_id identifies queue completion.
        candidate = details[item["candidate_id"]]
        candidate["manifest"] = item
        candidate["reviewed"] = any(
            str(event.candidate_id) == item["candidate_id"]
            or (
                event.document_id == item["document_id"]
                and event.table_index == item["table_index"]
                and event.row_index == item["row_index"]
                and event.column_name == item["column_name"]
            )
            for event in events
        )
        queue.append(candidate)
    return sorted(queue, key=lambda row: (row["manifest"]["priority"], row["document_id"]))


@app.get("/", response_class=HTMLResponse)
def queue_screen() -> str:
    queue = _queue()
    done = sum(item["reviewed"] for item in queue)
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['document_id'])}</td>"
        f"<td>{html.escape(item['document_family'])}</td>"
        f"<td>{html.escape(item['column_name'])}</td>"
        f"<td>{html.escape(item['raw_text'])}</td>"
        f"<td>{html.escape(item['manifest']['assigned_primary_reviewer'])}</td>"
        f"<td>{'DONE' if item['reviewed'] else 'OPEN'}</td>"
        f"<td><a href='/cell/{item['candidate_id']}'>review</a></td></tr>"
        for item in queue
    )
    return f"""<!doctype html><meta charset=utf-8><title>Table labeling</title>
<style>body{{font:14px Arial;margin:24px}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccd;padding:7px}}th{{background:#eef}}</style>
<h1>Table cell labeling — evaluation only</h1>
<p>Completed {done}/{len(queue)}. First checkpoint: 50 approved dispositions.</p>
<table><tr><th>Document</th><th>Family</th><th>Column</th><th>OCR</th><th>Assigned</th><th>Status</th><th></th></tr>{rows}</table>"""


def _candidate(candidate_id: str) -> dict:
    for item in _queue():
        if item["candidate_id"] == candidate_id:
            return item
    raise HTTPException(404, "candidate not found")


@app.get("/artifact/{candidate_id}/{kind}")
def artifact(candidate_id: str, kind: str):
    item = _candidate(candidate_id)
    allowed = {
        "page": "source_image", "overlay": "grid_overlay", "cell": "cell_crop",
    }
    if kind not in allowed:
        raise HTTPException(404, "artifact not found")
    path = Path(item["provenance"][allowed[kind]]).resolve()
    root = Path("evaluation_results/table_shadow_v2/artifacts").resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "artifact not found")
    return FileResponse(path)


@app.get("/cell/{candidate_id}", response_class=HTMLResponse)
def review_cell(candidate_id: str) -> str:
    item = _candidate(candidate_id)
    dispositions = "".join(
        f"<option>{value.value}</option>" for value in ReviewDisposition
    )
    assigned = html.escape(item["manifest"]["assigned_primary_reviewer"])
    return f"""<!doctype html><meta charset=utf-8><title>Review cell</title>
<style>body{{font:14px Arial;margin:24px}}img{{max-width:48%;border:1px solid #888;margin:5px}}label{{display:block;margin:9px}}</style>
<p><a href='/'>← queue</a></p><h1>{html.escape(item['document_id'])} / {html.escape(item['column_name'])}</h1>
<img src='/artifact/{candidate_id}/page'><img src='/artifact/{candidate_id}/overlay'>
<h2>Cell crop</h2><img src='/artifact/{candidate_id}/cell'>
<p>OCR: <b>{html.escape(item['raw_text'])}</b> · normalized: <b>{html.escape(item['normalized_value'])}</b></p>
<form method=post action='/cell/{candidate_id}'>
<label>Primary reviewer <input name=reviewer_id value='{assigned}' required></label>
<label>Disposition <select name=disposition>{dispositions}</select></label>
<label>Expected/corrected value <input name=expected_value value='{html.escape(item['raw_text'])}'></label>
<label>Semantic column name <input name=column_name value='{html.escape(item['column_name'])}' required></label>
<label>Second reviewer (critical/disagreement/promotion only) <input name=second_reviewer_id></label>
<button>Append review event</button></form>"""


@app.post("/cell/{candidate_id}")
def submit_review(
    candidate_id: str,
    reviewer_id: str = Form(...),
    disposition: ReviewDisposition = Form(...),
    expected_value: str = Form(""),
    column_name: str = Form(...),
    second_reviewer_id: str = Form(""),
):
    item = _candidate(candidate_id)
    now = datetime.now(UTC)
    accepted = disposition in {
        ReviewDisposition.APPROVED,
        ReviewDisposition.CORRECTED,
        ReviewDisposition.BLANK_CONFIRMED,
    }
    if disposition == ReviewDisposition.BLANK_CONFIRMED:
        expected_value = ""
    label = CellLabel(
        label_id=uuid4(),
        candidate_id=candidate_id,
        document_id=item["document_id"],
        page_number=item["page_number"],
        document_family=item["document_family"],
        table_type=item["table_type"],
        table_index=item["table_index"],
        row_index=item["row_index"],
        column_name=column_name,
        expected_value=expected_value,
        normalized_expected_value=" ".join(expected_value.split()),
        bbox=item["cell_bbox"],
        image_sha256=item["image_sha256"],
        writing_type=item["manifest"]["writing_type"],
        reviewer_id=reviewer_id,
        reviewed_at=now,
        approval_status=(
            ApprovalStatus.APPROVED if accepted else ApprovalStatus.REJECTED
        ),
        disposition=disposition,
        second_reviewer_id=second_reviewer_id or None,
        second_approval_at=now if second_reviewer_id else None,
    )
    try:
        TableLabelStore(LABELS, CRITICAL).append(label)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/", status_code=303)
