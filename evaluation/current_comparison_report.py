"""Build the live current-v2 side-by-side report served by evaluation-ui."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

RESULTS = Path("evaluation_results")


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _load_rows() -> list[dict]:
    rows: list[dict] = []
    for path in (
        RESULTS / "structured_rollout/cms1500/details.json",
        RESULTS / "structured_rollout/ub04/details.json",
    ):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    for family in ("laboratory_invoice", "statement", "psychological_receipt", "cms_attachment"):
        rows.extend(json.loads(
            (RESULTS / f"attachment_rollout/{family}/details.json").read_text(encoding="utf-8")
        ))
    return rows


def main() -> int:
    decisions = json.loads(
        (RESULTS / "current_v2_router/details.json").read_text(encoding="utf-8")
    )
    metrics = json.loads(
        (RESULTS / "current_v2_router/metrics.json").read_text(encoding="utf-8")
    )
    pareto = json.loads(
        (RESULTS / "remaining_error_pareto/metrics.json").read_text(encoding="utf-8")
    )
    oracle = json.loads(
        (RESULTS / "reconciliation_oracle/metrics.json").read_text(encoding="utf-8")
    )
    population = json.loads(
        (RESULTS / "population_reconciliation.json").read_text(encoding="utf-8")
    )
    channels = json.loads(
        (RESULTS / "accuracy_channels.json").read_text(encoding="utf-8")
    )
    sources = {
        (row["document_id"], row["field_name"]): row for row in _load_rows()
    }
    grouped: dict[str, list[dict]] = defaultdict(list)
    for decision in decisions:
        grouped[decision["document_id"]].append(decision)

    sections = []
    for document_id, document_rows in sorted(grouped.items()):
        table_rows = []
        matches = 0
        for decision in sorted(document_rows, key=lambda row: row["field_name"]):
            source = sources.get((document_id, decision["field_name"]), {})
            correct = bool(decision["extraction_correct"])
            matches += correct
            css = "match" if correct else "mismatch"
            derived = source.get("candidate_metadata", {}).get("derived_evidence")
            if derived:
                evidence = (
                    f"Raw: {derived['raw_address_evidence']} | ZIP: "
                    f"{derived['raw_zip_evidence']} | Derived: "
                    f"{derived['derived_candidate']} | REVIEW_ONLY | "
                    "reference or human approval required | finalization blocked"
                )
            else:
                evidence = source.get("candidate") or ""
            table_rows.append(
                f"<tr class='{css}'><td>{_e(decision['field_name'])}</td>"
                f"<td>{_e(source.get('expected'))}</td>"
                f"<td>{_e(decision.get('selected_value'))}</td>"
                f"<td>{_e(decision.get('selected_page'))}</td>"
                f"<td>{_e(decision.get('reason'))}</td>"
                f"<td>{_e(evidence)}</td>"
                f"<td>{'Match' if correct else 'Review required'}</td></tr>"
            )
        image = f"assets/{document_id}.png"
        sections.append(f"""
<section><div class="claim-head"><h2>{_e(document_id)}</h2>
<span>{matches}/{len(document_rows)} visible fields matched</span></div>
<div class="comparison"><div class="image-panel">
<a href="{image}"><img loading="lazy" src="{image}" alt="{_e(document_id)} source"></a>
</div><div class="details-panel"><table><thead><tr><th>Field</th><th>Expected</th>
<th>Selected</th><th>Page</th><th>Disposition</th><th>Evidence / verification</th>
<th>Status</th></tr></thead>
<tbody>{''.join(table_rows)}</tbody></table></div></div></section>""")

    correct = population["mutually_exclusive_population"]["correct_automated_visible_fields"]
    visible = population["visible_field_denominator"]
    generated = datetime.now(UTC).isoformat()
    document = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Current claim OCR comparison</title><style>
body{{font:14px system-ui;margin:0;background:#f3f5f8;color:#172033}}
header{{background:#172033;color:white;padding:20px 28px}} h1{{margin:0 0 6px}}
.sub{{color:#bdc8d9}} .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
gap:12px;padding:18px 28px;background:#25324a}} .card{{background:#fff;color:#172033;padding:14px;
border-radius:9px}} .card strong{{display:block;font-size:24px}} .good{{color:#18743a}}
.warning{{background:#fff4ce;padding:10px 28px}} main{{padding:20px}}
section{{background:white;margin-bottom:22px;padding:18px;border-radius:10px;box-shadow:0 2px 8px #0001}}
.claim-head{{display:flex;justify-content:space-between;align-items:center}}
.comparison{{display:grid;grid-template-columns:minmax(330px,.8fr) minmax(550px,1.2fr);gap:20px}}
img{{max-width:100%;max-height:680px;border:1px solid #ccd3df}} table{{border-collapse:collapse;width:100%;
font-size:12px}} th,td{{padding:7px;border:1px solid #dde2e9;text-align:left;vertical-align:top}}
th{{background:#edf1f7;position:sticky;top:0}} tr.mismatch{{background:#fff0f0}}
tr.match td:last-child{{color:#18743a}} tr.mismatch td:last-child{{color:#a21d1d}}
@media(max-width:1000px){{.comparison{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>Current claim OCR side-by-side comparison</h1>
<div class="sub">Router v1 frozen · reconciliation v2.1 · generated <span id="generated">{generated}</span></div>
</header><div class="cards">
<div class="card"><span>Extraction accuracy</span><strong id="accuracy">{metrics['extraction_accuracy']:.2%}</strong></div>
<div class="card"><span>Shadow candidate ceiling</span><strong id="shadowCeiling">{channels['SHADOW_CANDIDATE_CEILING']:.2%}</strong></div>
<div class="card"><span>Safely promoted accuracy</span><strong id="promotedAccuracy">Pending</strong></div>
<div class="card"><span>Reference-verified accuracy</span><strong id="referenceAccuracy">Pending</strong></div>
<div class="card"><span>Low-cost handwriting recovery</span><strong id="handwritingRecovery">{channels['LOW_COST_HANDWRITING_INCREMENTAL_CORRECT']}/{channels['LOW_COST_HANDWRITING_FIELDS_EVALUATED']}</strong></div>
<div class="card"><span>Accepted automation accuracy</span><strong id="acceptedAccuracy">{channels['AUTOMATED_ACCURACY']:.2%}</strong></div>
<div class="card"><span>Automated coverage</span><strong id="coverage">{channels['AUTOMATED_COVERAGE']:.2%}</strong></div>
<div class="card"><span>Abstained fields</span><strong id="abstained">{channels['ABSTAINED_FIELDS']}/{channels['TOTAL_EVALUATED_FIELDS']}</strong></div>
<div class="card"><span>Correct automated fields</span><strong id="correct">{correct}/{visible}</strong></div>
<div class="card"><span>Actionable selection failures</span><strong id="selection">{oracle['selection_failures']}</strong></div>
<div class="card"><span>Remaining visible failures</span><strong id="remaining">{pareto['remaining_errors']}</strong></div>
<div class="card"><span>Page accuracy</span><strong id="page">{metrics['actual_page_accuracy']:.2%}</strong></div>
<div class="card"><span>Wrong-page fields</span><strong id="wrong">{metrics['wrong_page_field_count']}</strong></div>
<div class="card"><span>Critical false accepts</span><strong id="falseAccept">{metrics['critical_false_accepts']}</strong></div>
<div class="card"><span>Governed non-selection cases</span><strong id="governed">{oracle['governed_non_selection_cases']}</strong></div>
<div class="card"><span>Reference-blocked fields</span><strong id="referenceBlocked">{channels['REFERENCE_BLOCKED_FIELDS']}</strong></div>
<div class="card"><span>Human-review-required</span><strong id="humanReview">{channels['HUMAN_REVIEW_REQUIRED_FIELDS']}</strong></div>
<div class="card"><span>Semantic-review fields</span><strong id="semanticReview">{channels['SEMANTIC_REVIEW_FIELDS']}</strong></div>
<div class="card"><span>Final validated accuracy</span><strong id="finalAccuracy">Unavailable</strong></div>
</div><div class="warning">Local PHI-bearing evaluation artifact. Do not deploy publicly.
Expected labels are used only for evaluation, never as inference evidence. Summary cards refresh every 15 seconds.</div>
<main>{''.join(sections)}</main>
<script>
async function refreshMetrics(){{
 try {{
  const [m,p,o,n,c]=await Promise.all([
   fetch('current_v2_router/metrics.json?'+Date.now()).then(r=>r.json()),
   fetch('remaining_error_pareto/metrics.json?'+Date.now()).then(r=>r.json()),
   fetch('reconciliation_oracle/metrics.json?'+Date.now()).then(r=>r.json()),
   fetch('population_reconciliation.json?'+Date.now()).then(r=>r.json()),
   fetch('accuracy_channels.json?'+Date.now()).then(r=>r.json())
  ]);
  accuracy.textContent=(100*m.extraction_accuracy).toFixed(2)+'%';
  shadowCeiling.textContent=(100*c.SHADOW_CANDIDATE_CEILING).toFixed(2)+'%';
  promotedAccuracy.textContent=c.SAFELY_PROMOTED_AUTOMATED_ACCURACY === null ?
    'Pending' : (100*c.SAFELY_PROMOTED_AUTOMATED_ACCURACY).toFixed(2)+'%';
  referenceAccuracy.textContent=c.REFERENCE_VERIFIED_ACCURACY === null ?
    'Pending' : (100*c.REFERENCE_VERIFIED_ACCURACY).toFixed(2)+'%';
  handwritingRecovery.textContent=c.LOW_COST_HANDWRITING_INCREMENTAL_CORRECT+
    '/'+c.LOW_COST_HANDWRITING_FIELDS_EVALUATED;
  acceptedAccuracy.textContent=(100*c.AUTOMATED_ACCURACY).toFixed(2)+'%';
  coverage.textContent=(100*c.AUTOMATED_COVERAGE).toFixed(2)+'%';
  abstained.textContent=c.ABSTAINED_FIELDS+'/'+c.TOTAL_EVALUATED_FIELDS;
  correct.textContent=n.mutually_exclusive_population.correct_automated_visible_fields+'/'+n.visible_field_denominator;
  selection.textContent=o.selection_failures; remaining.textContent=p.remaining_errors;
  page.textContent=(100*m.actual_page_accuracy).toFixed(2)+'%';
  wrong.textContent=m.wrong_page_field_count; falseAccept.textContent=m.critical_false_accepts;
  governed.textContent=o.governed_non_selection_cases;
  referenceBlocked.textContent=c.REFERENCE_BLOCKED_FIELDS;
  humanReview.textContent=c.HUMAN_REVIEW_REQUIRED_FIELDS;
  semanticReview.textContent=c.SEMANTIC_REVIEW_FIELDS;
  finalAccuracy.textContent=c.FINAL_VALIDATED_ACCURACY === null ? 'Unavailable' :
    (100*c.FINAL_VALIDATED_ACCURACY).toFixed(2)+'%';
 }} catch(error) {{ console.warn('Metric refresh failed', error); }}
}}
refreshMetrics(); setInterval(refreshMetrics,15000);
</script></body></html>"""
    output = RESULTS / "comparison.html"
    output.write_text(document, encoding="utf-8")
    print(f"Wrote current comparison report to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
