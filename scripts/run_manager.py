"""Record development measurement attempts without changing pipeline behavior."""

import json
import subprocess
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from uuid import uuid4

METRICS = (
    "document_accuracy", "field_accuracy", "critical_accuracy", "latency",
    "geometry", "ocr", "ranking", "validator", "provider_usage", "retries",
    "coverage", "parity", "memory",
)


class RunManager:
    """Write an isolated record for an execution or a blocked execution attempt.

    Callers supply measured metrics with units and provenance. Absent metrics
    remain unavailable, never zero or passing. This class does not run OCR,
    infer truth from validator outcomes, or bind unfinished runtime stages.
    """

    def __init__(self, dataset, *, versions, output_root="runs", repository="."):
        repo = Path(repository).resolve()

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(repo), *args], text=True,
            ).strip()

        started = datetime.now(UTC)
        run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
        self.directory = Path(output_root) / run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.record = {
            "run_id": run_id,
            "dataset": dataset,
            "commit_sha": git("rev-parse", "HEAD"),
            "working_tree_status": git("status", "--porcelain"),
            "pipeline_version": versions.get("pipeline"),
            "ocr_version": versions.get("ocr"),
            "geometry_version": versions.get("geometry"),
            "start": started.isoformat(),
            "end": None,
            "status": "started",
            "metrics": {},
        }
        self._write("run.json", self.record)

    def _write(self, filename, value):
        (self.directory / filename).write_text(
            json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )

    def finish_blocked(self, *, reasons, dataset_verification, evidence):
        """Finalize preflight failure; it is explicitly not a V3 measurement."""
        if self.record["status"] != "started":
            raise ValueError("Run already finalized")
        metrics = {
            name: {"value": None, "status": "unavailable", "reason": "Pipeline not executed"}
            for name in METRICS
        }
        self.record.update({
            "status": "blocked",
            "end": datetime.now(UTC).isoformat(),
            "metrics": metrics,
            "blockers": reasons,
            "evidence": evidence,
            "dataset_verification": dataset_verification,
            "processed_documents": 0,
            "processed_pages": 0,
        })
        summary = {
            "run_id": self.record["run_id"], "status": "blocked",
            "metrics": metrics, "blockers": reasons,
            "top_20_incorrect_fields": {
                "status": "unavailable", "items": [],
                "reason": "No predictions or linked ground truth; empty list does not mean zero errors",
                "required_evidence": ["image", "crop", "ocr", "winner", "validator", "reason"],
            },
        }
        self._write("run.json", self.record)
        self._write("summary.json", summary)
        rows = "".join(f"<tr><td>{escape(name)}</td><td>Unavailable</td></tr>" for name in metrics)
        blockers = "".join(f"<li>{escape(reason)}</li>" for reason in reasons)
        html = (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<title>Development run report</title><body>'
            '<h1>Development run: blocked</h1>'
            f'<p>Run {escape(self.record["run_id"])}</p>'
            '<p>V3 was not executed. Documents processed: 0. Pages processed: 0.</p>'
            f'<ul>{blockers}</ul><table><caption>Requested pipeline metrics</caption>'
            f'<tr><th>Metric</th><th>Result</th></tr>{rows}</table>'
            '<h2>Top 20 incorrect fields</h2><p>Unavailable: no predictions or linked truth. '
            'This is not a zero-error result.</p></body></html>'
        )
        (self.directory / "dashboard.html").write_text(html, encoding="utf-8")
        return self.directory
