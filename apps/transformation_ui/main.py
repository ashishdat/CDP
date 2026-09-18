"""FastAPI server to host the Field Transformation & Escalation Visualizer UI."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

UI_DIR = Path(__file__).resolve().parent
INGESTION_API_URL = os.getenv("INGESTION_API_URL", "http://localhost:8000")
HUMAN_REVIEW_API_URL = os.getenv("HUMAN_REVIEW_API_URL", "http://localhost:8100")

app = FastAPI(title="IDP Transformation Visualizer UI", version="1.0.0")
client = httpx.AsyncClient(timeout=120.0)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _proxy(request: Request, base_url: str, path: str) -> StreamingResponse:
    url = f"{base_url.rstrip('/')}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)
    body = await request.body()
    try:
        req = client.build_request(method=request.method, url=url, headers=headers, content=body)
        resp = await client.send(req, stream=True)
        resp_headers = dict(resp.headers)
        resp_headers.pop("content-length", None)
        resp_headers.pop("content-encoding", None)
        return StreamingResponse(resp.aiter_raw(), status_code=resp.status_code, headers=resp_headers)
    except (OSError, httpx.HTTPError, TimeoutError, ValueError) as exc:
        return StreamingResponse(
            iter([f'{{"error": "proxy failure: {exc!s}"}}'.encode()]),
            status_code=502,
            media_type="application/json",
        )


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_api(request: Request, path: str):
    return await _proxy(request, INGESTION_API_URL, path)


@app.api_route("/review-api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_review_api(request: Request, path: str):
    return await _proxy(request, HUMAN_REVIEW_API_URL, path)


app.mount("/static", StaticFiles(directory=UI_DIR), name="static")


@app.get("/")
def read_root():
    return FileResponse(UI_DIR / "index.html")


@app.get("/styles.css")
def read_css():
    return FileResponse(UI_DIR / "styles.css")


@app.get("/app.js")
def read_js():
    return FileResponse(UI_DIR / "app.js")


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8185)
