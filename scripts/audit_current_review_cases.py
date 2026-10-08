"""Inventory every current review/failure without copying labels into inference."""
from collections import Counter
import json
import csv
from pathlib import Path
from packages.recovery.independent_failures import failure_category

ROOT = Path(__file__).resolve().parents[1]


def main():
    run = ROOT / "evaluation_results/regression50_v311_20261006"
    cases = []
    for ledger in sorted(run.glob("product/corpus_*/results.jsonl")):
        rows = {}
        for line in ledger.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            rows[row["document"]] = row
        for row in rows.values():
            if not row.get("finished") or row.get("true_stp"):
                continue
            blockers = [{"field": name, **(row.get("fields") or {}).get(name, {})}
                        for name in (row.get("critical_blockers") or [])]
            case = {"document": row["document"], "corpus": ledger.parent.name,
                    "source_sha256": row.get("source_sha256"),
                    "family": row.get("document_family", "UNKNOWN"),
                    "disposition": row.get("disposition"),
                    "category": failure_category(row),
                    "registration_reason": row.get("registration_reason"),
                    "blockers": blockers, "gap_classes": row.get("gap_classes", []),
                    "analysis": row.get("failure_analysis"),
                    "artifact": str(ledger.parent / "claims" / row["claim_id"])}
            cases.append(case)
            print(row["document"], case["disposition"], case["category"],
                  ",".join(b["field"] for b in blockers), case["registration_reason"] or "")
    out = ROOT / "evaluation_results/current_review_repairs"
    out.mkdir(exist_ok=True)
    (out / "inventory.json").write_text(json.dumps({
        "baseline": str(run), "cases": cases,
        "blocking_field_counts": dict(Counter(b["field"] for c in cases for b in c["blockers"])),
        "category_counts": dict(Counter(c["category"] for c in cases))}, indent=2), encoding="utf-8")
    with (out / "cases.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["document", "corpus", "family", "disposition", "category", "blocking_fields", "registration_reason"])
        writer.writeheader()
        for case in cases:
            writer.writerow({**{key: case[key] for key in writer.fieldnames if key in case},
                             "blocking_fields": ";".join(b["field"] for b in case["blockers"])})


if __name__ == "__main__":
    main()
