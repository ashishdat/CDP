"""Authenticated, fail-closed reviewer UI for the 30-cell crop-QA pilot."""

from __future__ import annotations

import html
import json
import os
import re
from datetime import UTC, datetime
from datetime import datetime as DateTime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

PILOT = Path("evaluation_results/table_crop_quality_pilot/pilot_manifest.jsonl")
EVENTS = Path(
    "evaluation_data/table_labels/crop_quality_pilot_review_events.jsonl"
)
ALLOWED_DISPOSITIONS = {
    "APPROVED",
    "CORRECTED",
    "BLANK_CONFIRMED",
    "UNREADABLE",
    "WRONG_CELL_BOUNDARY",
    "WRONG_ROW_OR_COLUMN",
    "NOT_APPLICABLE",
}
BOUNDARY_ERRORS = {"WRONG_CELL_BOUNDARY", "WRONG_ROW_OR_COLUMN"}
app = FastAPI(title="Crop Quality Pilot Review", docs_url=None, redoc_url=None)


def _reviewer(request: Request) -> str:
    reviewer = request.headers.get("X-Reviewer-ID") or os.getenv(
        "TABLE_REVIEWER_ID"
    )
    if not reviewer:
        raise HTTPException(401, "authenticated reviewer context required")
    return reviewer


def _manifest() -> list[dict]:
    if not PILOT.exists():
        return []
    return [
        json.loads(line)
        for line in PILOT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _events() -> list[dict]:
    if not EVENTS.exists():
        return []
    return [
        json.loads(line)
        for line in EVENTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _append_event(event: dict) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _candidate(candidate_id: str) -> dict:
    for item in _manifest():
        if item["candidate_id"] == candidate_id:
            return item
    raise HTTPException(404, "candidate not found")


def validate_submission(
    item: dict,
    disposition: str,
    expected_value: str,
    review_comment: str,
    visual_verified: bool,
) -> None:
    if disposition not in ALLOWED_DISPOSITIONS:
        raise ValueError("explicit review disposition required")
    if not visual_verified:
        raise ValueError("visual verification confirmation is required")
    if not Path(item["crop_path"]).is_file():
        raise ValueError("missing crop image blocks submission")
    if item["crop_quality_status"] != "VALID_SINGLE_CELL":
        raise ValueError("only validated single-cell crops may be reviewed")
    if disposition in {"APPROVED", "CORRECTED"} and not expected_value.strip():
        raise ValueError("approved or corrected values cannot be empty")
    if not expected_value.strip() and disposition != "BLANK_CONFIRMED":
        raise ValueError("blank values require BLANK_CONFIRMED")
    if disposition == "BLANK_CONFIRMED" and expected_value.strip():
        raise ValueError("BLANK_CONFIRMED requires an empty value")
    if disposition in BOUNDARY_ERRORS and not review_comment.strip():
        raise ValueError("boundary errors require a comment")
    value = expected_value.strip()
    data_type = item.get("data_type")
    if value and data_type == "date":
        valid = False
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
            try:
                DateTime.strptime(value, fmt)  # noqa: DTZ007
                valid = True
                break
            except ValueError:
                continue
        if not valid:
            raise ValueError("date fields require a valid date, for example 06/24/2026")
    if value and data_type == "currency" and not re.fullmatch(
        r"\$?\d+(?:\.\d{1,2})?", value.replace(",", "")
    ):
        raise ValueError("currency fields require a valid amount")
    if value and data_type == "code" and not re.fullmatch(r"[A-Za-z0-9.]+", value):
        raise ValueError("code fields contain only letters, digits, or a period")


@app.get("/", response_class=HTMLResponse)
def queue_screen(request: Request) -> str:
    reviewer = _reviewer(request)
    events = _events()
    latest = {event["candidate_id"]: event for event in events}
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['document_id'])}</td>"
        f"<td>{html.escape(item['document_family'])}</td>"
        f"<td>{html.escape(item['form_locator'])}</td>"
        f"<td>{html.escape(item['semantic_field_name'])}</td>"
        f"<td>{item['service_line_number']}</td>"
        f"<td>{html.escape(latest.get(item['candidate_id'], {}).get('status', 'PENDING_REVIEW'))}</td>"
        f"<td><a href='/cell/{item['candidate_id']}'>review</a></td></tr>"
        for item in _manifest()
    )
    return f"""<!doctype html><meta charset=utf-8><title>Crop QA pilot</title>
<style>body{{font:14px Arial;margin:24px}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccd;padding:7px}}th{{background:#eef}}</style>
<h1>30-cell crop-quality pilot</h1>
<p>Authenticated reviewer: <b>{html.escape(reviewer)}</b>. OCR accuracy is not being evaluated.</p>
<table><tr><th>Document</th><th>Family</th><th>Locator</th><th>Semantic field</th><th>Line</th><th>Status</th><th></th></tr>{rows}</table>"""


@app.get("/artifact/{candidate_id}/{kind}")
def artifact(candidate_id: str, kind: str, request: Request):
    _reviewer(request)
    item = _candidate(candidate_id)
    allowed = {
        "page": "original_page",
        "registered": "registered_page",
        "overlay": "registration_overlay",
        "cell": "crop_path",
        "row": "row_context_path",
    }
    if kind not in allowed or not item.get(allowed[kind]):
        raise HTTPException(404, "artifact not found")
    path = Path(item[allowed[kind]]).resolve()
    root = Path("evaluation_results/table_crop_quality_pilot").resolve()
    quarantine = Path("evaluation_data/table_labels/quarantine").resolve()
    if not path.is_file() or not (
        root in path.parents or quarantine in path.parents
    ):
        raise HTTPException(404, "artifact not found")
    return FileResponse(path)


@app.get("/cell/{candidate_id}", response_class=HTMLResponse)
def review_cell(candidate_id: str, request: Request) -> str:
    reviewer = _reviewer(request)
    item = _candidate(candidate_id)
    if not Path(item["crop_path"]).is_file():
        disabled = "disabled"
        warning = "<p class=error>Crop image missing; submission disabled.</p>"
    else:
        disabled = ""
        warning = ""
    options = "<option selected disabled>PENDING_REVIEW</option>" + "".join(
        f"<option>{html.escape(value)}</option>"
        for value in sorted(ALLOWED_DISPOSITIONS)
    )
    suggestion = html.escape(item.get("ocr_suggestion") or "(none)")
    return f"""<!doctype html><meta charset=utf-8><title>Review crop</title>
<style>body{{font:14px Arial;margin:24px}}img{{max-width:90%;border:1px solid #888;margin:7px}}label{{display:block;margin:10px}}.warn{{background:#fff3cd;padding:10px}}.error{{color:#b00}}</style>
<p><a href='/'>← queue</a></p>
<h1>{html.escape(item['document_id'])}: {html.escape(item['semantic_field_name'])}</h1>
<p>Form locator <b>{html.escape(item['form_locator'])}</b>, service line {item['service_line_number']}</p>
<h2>Complete row context</h2><img src='/artifact/{candidate_id}/row'>
<h2>Single semantic cell</h2><img src='/artifact/{candidate_id}/cell'>
<p class=warn><b>Unverified OCR suggestion.</b> {suggestion}</p>{warning}
<form method=post action='/cell/{candidate_id}'>
<label>Authenticated reviewer <input value='{html.escape(reviewer)}' readonly></label>
<label>Semantic field <input value='{html.escape(item['semantic_field_name'])}' readonly></label>
<label>Disposition <select name=disposition required>{options}</select></label>
<label>Expected/corrected value <input name=expected_value value=''></label>
<label>Comment <textarea name=review_comment rows=3 cols=70></textarea></label>
<label><input type=checkbox name=visual_verified value=true required> I visually verified the page, row context, boundary, and cell.</label>
<button {disabled}>Submit primary review</button></form>"""


@app.post("/cell/{candidate_id}")
def submit_review(
    candidate_id: str,
    request: Request,
    disposition: str = Form(...),
    expected_value: str = Form(""),
    review_comment: str = Form(""),
    visual_verified: bool = Form(False),
):
    reviewer = _reviewer(request)
    item = _candidate(candidate_id)
    if any(
        event["candidate_id"] == candidate_id
        and event.get("status") in {"APPROVED", "AWAITING_SECOND_APPROVAL"}
        for event in _events()
    ):
        raise HTTPException(
            400,
            "candidate already has a primary review; use independent second approval when required",
        )
    try:
        validate_submission(
            item,
            disposition,
            expected_value,
            review_comment,
            visual_verified,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    requires_second = disposition == "CORRECTED" or item[
        "semantic_field_name"
    ] in {"procedure_code", "rendering_provider_npi", "revenue_code"}
    _append_event(
        {
            "event_id": str(uuid4()),
            "candidate_id": candidate_id,
            "reviewer_id": reviewer,
            "reviewed_at": datetime.now(UTC).isoformat(),
            "disposition": disposition,
            "expected_value": expected_value.strip(),
            "review_comment": review_comment.strip() or None,
            "visual_verified": True,
            "status": "AWAITING_SECOND_APPROVAL" if requires_second else "APPROVED",
            "evaluation_eligible": False,
            "training_eligible": False,
            "source": "CROP_QUALITY_PILOT",
        }
    )
    from evaluation.evaluate_crop_quality_reviews import publish

    publish()
    return RedirectResponse("/", status_code=303)


@app.post("/cell/{candidate_id}/second-approve")
def second_approve(candidate_id: str, request: Request):
    reviewer = _reviewer(request)
    pending = [
        event
        for event in _events()
        if event["candidate_id"] == candidate_id
        and event["status"] == "AWAITING_SECOND_APPROVAL"
    ]
    if not pending:
        raise HTTPException(400, "no primary review awaiting approval")
    primary = pending[-1]
    if primary["reviewer_id"] == reviewer:
        raise HTTPException(400, "second reviewer must be independent")
    _append_event(
        {
            **primary,
            "event_id": str(uuid4()),
            "second_reviewer_id": reviewer,
            "second_approval_at": datetime.now(UTC).isoformat(),
            "status": "APPROVED",
        }
    )
    from evaluation.evaluate_crop_quality_reviews import publish

    publish()
    return RedirectResponse("/", status_code=303)
