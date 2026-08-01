"""Generate a local PHI-safe side-by-side image/OCR comparison report."""

from __future__ import annotations

import argparse
import html
from pathlib import Path

from evaluation.metrics import evaluate
from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset, PredictionDataset


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--normalization-rules",
        type=Path,
        default=Path("config/evaluation/normalization_rules.yaml"),
    )
    args = parser.parse_args()

    truth = GroundTruthDataset.model_validate_json(args.ground_truth.read_text(encoding="utf-8"))
    predictions = PredictionDataset.model_validate_json(
        args.predictions.read_text(encoding="utf-8")
    )
    registry = NormalizerRegistry.from_yaml(args.normalization_rules)
    metrics = evaluate(truth, predictions, registry)
    predicted_by_document = {document.document_id: document for document in predictions.documents}
    asset_prefix = Path(args.assets.name)
    splits = sorted({document.split for document in truth.documents})
    report_label = " / ".join(split.upper() for split in splits)
    if any("synthetic" in document.image_quality_bucket.lower() for document in truth.documents):
        report_label += " · SYNTHETIC"

    sections = []
    for document in truth.documents:
        prediction = predicted_by_document.get(document.document_id)
        predicted_fields = (
            {field.field_name: field for field in prediction.fields} if prediction else {}
        )
        rows = []
        matches = 0
        for expected in document.fields:
            actual = predicted_fields.get(expected.field_name)
            expected_normalized = expected.expected_normalized
            if expected_normalized is None:
                expected_normalized = registry.normalize(expected.field_name, expected.expected_raw)
            actual_normalized = actual.normalized_value if actual else None
            if actual and actual_normalized is None:
                actual_normalized = registry.normalize(expected.field_name, actual.raw_value)
            ok = (expected_normalized or "") == (actual_normalized or "")
            matches += ok
            status = "match" if ok else "mismatch"
            candidates = (actual.metadata.get("ocr_candidates", []) if actual else [])
            candidate_text = " · ".join(
                f"{item.get('engine')}/{item.get('preprocessing')}: "
                f"{item.get('value') or '∅'} ({float(item.get('confidence') or 0):.0%})"
                for item in candidates
            )
            rows.append(
                "<tr class='{status}'><td>{field}</td><td>{expected}</td>"
                "<td>{actual}</td><td>{method}</td><td>{confidence}</td><td>{candidates}</td>"
                "<td>{status_text}</td></tr>".format(
                    status=status,
                    field=_e(expected.field_name),
                    expected=_e(expected_normalized),
                    actual=_e(actual.raw_value if actual else None),
                    method=_e(actual.extraction_method if actual else "—"),
                    confidence=_e(f"{actual.confidence:.1%}" if actual and actual.confidence else "—"),
                    candidates=_e(candidate_text),
                    status_text="✓ Match" if ok else "✗ Not finalized",
                )
            )
        image_name = f"{document.document_id}.png"
        sections.append(
            f"""<section>
<div class="claim-head"><h2>{_e(document.document_id)} · {_e(document.form_type)}</h2>
<span>{matches}/{len(document.fields)} fields matched</span></div>
<div class="comparison">
  <div class="image-panel"><h3>Aligned source image / field strip</h3>
    <a href="{_e(asset_prefix / image_name)}"><img loading="lazy"
       src="{_e(asset_prefix / image_name)}" alt="{_e(document.document_id)} source"></a>
  </div>
  <div class="details-panel"><h3>Reference vs automated parsing</h3>
    <table><thead><tr><th>Field</th><th>Expected</th><th>OCR parsed</th>
    <th>Method</th><th>Confidence</th><th>Cascade candidates</th><th>Status</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table>
  </div>
</div></section>"""
        )

    document = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Claim OCR comparison</title>
<style>
body{{font:14px system-ui;margin:0;background:#f3f5f8;color:#172033}}
header{{position:sticky;top:0;z-index:2;background:#172033;color:white;padding:18px 28px}}
header h1{{margin:0 0 8px}} .metrics{{display:flex;gap:24px;flex-wrap:wrap}}
.warning{{background:#fff4ce;color:#5c4700;padding:10px 28px;border-bottom:1px solid #e1c65a}}
main{{padding:20px}} section{{background:white;margin:0 0 22px;padding:18px;border-radius:10px;
box-shadow:0 2px 8px #0001}} .claim-head{{display:flex;justify-content:space-between;align-items:center}}
.comparison{{display:grid;grid-template-columns:minmax(360px,1fr) minmax(520px,1.2fr);gap:20px}}
.image-panel{{overflow:auto}} img{{max-width:100%;max-height:720px;border:1px solid #ccd3df}}
table{{border-collapse:collapse;width:100%;font-size:12px}} th,td{{padding:7px;border:1px solid #dde2e9;
text-align:left;vertical-align:top}} th{{background:#edf1f7;position:sticky;top:0}}
tr.match td:last-child{{color:#18743a}} tr.mismatch{{background:#fff0f0}} tr.mismatch td:last-child{{color:#a21d1d}}
@media(max-width:1000px){{.comparison{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>Claim OCR side-by-side comparison · {_e(report_label)}</h1><div class="metrics">
<span>Documents: {len(truth.documents)}</span>
<span>Fields: {metrics.field_count}</span>
<span>Automated normalized accuracy: {metrics.normalized_field_accuracy:.2%}</span>
<span>Perfect claims: {metrics.perfect_claim_rate:.2%}</span>
<span>Critical false accepts: {metrics.critical_false_accept_rate:.2%}</span>
</div></header>
<div class="warning">Local evaluation artifact containing claim images and extracted PHI.
Do not deploy publicly. Red rows require review; reference values are evaluation labels,
not OCR output.</div><main>{''.join(sections)}</main></body></html>"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")
    print(f"Wrote comparison report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
