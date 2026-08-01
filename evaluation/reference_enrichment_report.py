from __future__ import annotations

import html
import json
from pathlib import Path


def write_report(output: Path, metrics: dict) -> None:
    cards = "".join(
        f"<div class='card'><span>{html.escape(key.replace('_', ' ').title())}</span>"
        f"<strong>{html.escape(str(value))}</strong></div>"
        for key, value in metrics.items()
    )
    payload = html.escape(json.dumps(metrics, indent=2))
    output.write_text(f"""<!doctype html><html><head><meta charset='utf-8'>
<title>Reference Enrichment</title><style>body{{font:16px Arial;background:#061522;color:#eef6fb;margin:40px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}}.card{{background:#10283a;padding:20px;border:1px solid #43d7b3;border-radius:12px}}
.card span{{display:block;color:#9fb2c5}}.card strong{{font-size:26px}}pre{{background:#10283a;padding:20px}}</style></head>
<body><h1>Governed Reference Enrichment</h1><div class='grid'>{cards}</div><h2>Machine-readable metrics</h2><pre>{payload}</pre></body></html>""", encoding="utf-8")
