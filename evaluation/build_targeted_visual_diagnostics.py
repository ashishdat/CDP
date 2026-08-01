"""Build an auditable visual report for the targeted unresolved-field stage."""

from __future__ import annotations

import html
import json
from pathlib import Path


def main() -> int:
    root = Path("evaluation_results/targeted_diagnostics_v1")
    details = json.loads((root / "evaluation/details.json").read_text(encoding="utf-8"))
    rows = []
    counts: dict[str, int] = {}
    for item in details:
        category = _category(item)
        counts[category] = counts.get(category, 0) + 1
        original = Path("../ocr_shadow_bakeoff/normalized_crops") / item["document_id"] / item["field_name"] / "original.png"
        retuned = Path("../crop_retuning_v1") / item["document_id"] / item["field_name"] / "border_aware.png"
        rows.append(f"""<tr><td>{html.escape(item['document_id'])}</td>
<td>{html.escape(item['field_name'])}</td><td>{html.escape(str(item.get('expected') or ''))}</td>
<td><img src="{original.as_posix()}" alt="original"></td>
<td><img src="{retuned.as_posix()}" alt="retuned"></td>
<td>{html.escape(category)}</td><td>{'Yes' if item['correct_candidate_generated'] else 'No'}</td></tr>""")
    document = f"""<!doctype html><html><head><meta charset="utf-8"><title>Targeted Crop Diagnostics</title>
<style>body{{font:14px system-ui;margin:24px;color:#172033}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #d7deea;padding:8px;text-align:left}}th{{background:#eef3fa}}img{{max-width:420px;max-height:90px;background:white}}</style></head>
<body><h1>Targeted alignment and crop diagnostics</h1><p>All candidates remain review-only.</p>
<pre>{html.escape(json.dumps(counts, indent=2))}</pre><table><thead><tr><th>Document</th><th>Field</th>
<th>Expected (evaluation only)</th><th>Original</th><th>Border-aware</th><th>Disposition</th><th>Correct candidate exists</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"""
    (root / "diagnostics.html").write_text(document, encoding="utf-8")
    (root / "diagnostic_metrics.json").write_text(json.dumps({
        "fields": len(details), "classifications": counts,
        "candidate_authority": "REVIEW_ONLY", "production_promoted": False,
    }, indent=2), encoding="utf-8")
    print(json.dumps({"fields": len(details), "classifications": counts}, indent=2))
    return 0


def _category(item: dict) -> str:
    if item["correct_candidate_generated"]:
        if item["field_name"] == "rel_code":
            return "RECOVERED_BY_ALIGNED_CHECKBOX_GEOMETRY"
        return "RECOVERED_BY_COMPONENT_PARSE_OR_CROP_ENSEMBLE"
    if item["document_id"] == "C-06" and item["field_name"] == "patient_first":
        return "OUTPUT_PROJECTION_REVIEW"
    if item["document_id"] == "A-01" and item["field_name"] == "insured_state":
        return "DEGRADED_GLYPH_REQUIRES_REFERENCE"
    return "CORRECT_REGION_OCR_UNRESOLVED_REQUIRES_REFERENCE"


if __name__ == "__main__":
    raise SystemExit(main())
