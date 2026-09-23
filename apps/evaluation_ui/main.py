"""FastAPI server to host the Claims Intelligence Governance Console (evaluation_ui)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

DIST_DIR = Path(__file__).resolve().parent / "dist"
PUBLIC_DIR = Path(__file__).resolve().parent / "public"
TRANSFORMATION_DIR = Path(__file__).resolve().parent.parent / "transformation_ui"

INGESTION_API_URL = os.getenv("INGESTION_API_URL", "http://localhost:8000")
HUMAN_REVIEW_API_URL = os.getenv("HUMAN_REVIEW_API_URL", "http://localhost:8100")

app = FastAPI(title="IDP Evaluation & Governance Console UI", version="1.0.0")

client = httpx.AsyncClient(timeout=120.0)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_api(request: Request, path: str):
    url = f"{INGESTION_API_URL}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)
    
    body = await request.body()
    
    try:
        req = client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            content=body
        )
        resp = await client.send(req, stream=True)
        
        # Clean response headers
        resp_headers = dict(resp.headers)
        resp_headers.pop("content-length", None)
        resp_headers.pop("content-encoding", None)
        
        return StreamingResponse(
            resp.aiter_raw(),
            status_code=resp.status_code,
            headers=resp_headers
        )
    except (OSError, httpx.HTTPError, TimeoutError, ValueError) as exc:
        return StreamingResponse(
            iter([f'{{"error": "Ingestion API proxy error: {exc!s}"}}'.encode()]),
            status_code=502,
            media_type="application/json"
        )


@app.api_route("/review-api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_review_api(request: Request, path: str):
    url = f"{HUMAN_REVIEW_API_URL}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
        
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)
    
    body = await request.body()
    
    try:
        req = client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            content=body
        )
        resp = await client.send(req, stream=True)
        
        resp_headers = dict(resp.headers)
        resp_headers.pop("content-length", None)
        resp_headers.pop("content-encoding", None)
        
        return StreamingResponse(
            resp.aiter_raw(),
            status_code=resp.status_code,
            headers=resp_headers
        )
    except (OSError, httpx.HTTPError, TimeoutError, ValueError) as exc:
        return StreamingResponse(
            iter([f'{{"error": "Human Review API proxy error: {exc!s}"}}'.encode()]),
            status_code=502,
            media_type="application/json"
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

if (DIST_DIR / "reports").exists():
    app.mount("/reports", StaticFiles(directory=DIST_DIR / "reports"), name="reports")

if TRANSFORMATION_DIR.exists():
    app.mount("/transformation-files", StaticFiles(directory=TRANSFORMATION_DIR), name="transformation_files")


@app.get("/transformation")
def read_transformation():
    return FileResponse(TRANSFORMATION_DIR / "index.html")


@app.get("/styles.css")
def read_transformation_css():
    return FileResponse(TRANSFORMATION_DIR / "styles.css")


@app.get("/app.js")
def read_transformation_js():
    return FileResponse(TRANSFORMATION_DIR / "app.js")


@app.get("/transformation-files/styles.css")
def read_transformation_css_files():
    return FileResponse(TRANSFORMATION_DIR / "styles.css")


@app.get("/transformation-files/app.js")
def read_transformation_js_files():
    return FileResponse(TRANSFORMATION_DIR / "app.js")


@app.get("/reports/evaluation.json")
def get_evaluation_report():
    report_file = DIST_DIR / "reports" / "evaluation.json"
    if report_file.exists():
        return FileResponse(report_file)
    return {"error": "Report file not found"}


def _ops_usage_candidates() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    return [
        DIST_DIR / "reports" / "ops_usage.json",
        PUBLIC_DIR / "reports" / "ops_usage.json",
        root / "docs" / "metrics" / "ops_usage_latest.json",
        root / "evaluation_results" / "hackathon_600_independent_v13c" / "ops_usage.json",
        root / "evaluation_results" / "hackathon_300_independent_v13c" / "ops_usage.json",
    ]


@app.get("/reports/ops_usage.json")
def get_ops_usage_report():
    for candidate in _ops_usage_candidates():
        if candidate.is_file():
            return FileResponse(candidate)
    return JSONResponse({"error": "ops_usage_missing"}, status_code=404)


@app.get("/ops-usage/progress")
def get_ops_usage_progress():
    """Live progress line from the active Independent-600 (or 300) run."""
    root = Path(__file__).resolve().parents[2]
    for name in (
        "hackathon_600_independent_v13c",
        "hackathon_300_independent_v13c",
    ):
        run_dir = root / "evaluation_results" / name
        progress = run_dir / "progress.txt"
        if progress.is_file():
            text = progress.read_text(encoding="utf-8", errors="ignore").strip()
            line = text.splitlines()[-1] if text else ""
            if line:
                return {"cohort": name, "progress": line}
        results = run_dir / "results.jsonl"
        run_log = run_dir / "run.log"
        if results.is_file() or run_log.is_file():
            done = 0
            if results.is_file():
                done = sum(1 for line in results.read_text(encoding="utf-8").splitlines() if line.strip())
            token_path = run_dir / "vlm_token_meter.jsonl"
            tok = 0
            if token_path.is_file():
                tok = sum(
                    int(json.loads(line).get("total_tokens") or 0)
                    for line in token_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            di_path = run_dir / "azure_di_meter.jsonl"
            di = 0
            if di_path.is_file():
                di = sum(1 for line in di_path.read_text(encoding="utf-8").splitlines() if line.strip())
            return {
                "cohort": name,
                "progress": f"{name}: completed={done} di_calls={di} vlm_tokens={tok}",
            }
    return {"cohort": None, "progress": None}


_MISSING_DIST_MESSAGE = (
    "Evaluation UI build unavailable: dist/index.html is missing. "
    "Run `npm run build` in apps/evaluation_ui."
)


@app.get("/")
def read_root(request: Request):
    index = DIST_DIR / "index.html"
    if not index.is_file():
        accept = (request.headers.get("accept") or "").lower()
        if "text/html" in accept and "application/json" not in accept:
            return HTMLResponse(
                content=(
                    "<!doctype html><html><head><title>UI build unavailable</title></head>"
                    f"<body><h1>Evaluation UI unavailable</h1><p>{_MISSING_DIST_MESSAGE}</p>"
                    "</body></html>"
                ),
                status_code=503,
            )
        return JSONResponse(
            {"error": "ui_build_unavailable", "detail": _MISSING_DIST_MESSAGE},
            status_code=503,
        )
    return FileResponse(index)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/favicon.ico")
def favicon_ico():
    for candidate in (DIST_DIR / "favicon.ico", PUBLIC_DIR / "favicon.ico"):
        if candidate.is_file():
            return FileResponse(candidate, media_type="image/x-icon")
    return JSONResponse({"error": "favicon_missing"}, status_code=404)


@app.get("/favicon.svg")
def favicon_svg():
    for candidate in (DIST_DIR / "favicon.svg", PUBLIC_DIR / "favicon.svg"):
        if candidate.is_file():
            return FileResponse(candidate, media_type="image/svg+xml")
    return JSONResponse({"error": "favicon_missing"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8180)

