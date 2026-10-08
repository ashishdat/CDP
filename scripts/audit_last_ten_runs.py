"""Offline cohort audit; diagnostics and tiny replays are not cohort runs."""
from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    candidates = []
    for folder in (ROOT / "evaluation_results").iterdir():
        path = folder / "comparison_product.json"
        if not path.is_file():
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if not report.get("overall"):
            continue
        candidates.append((path.stat().st_mtime, folder, report))
    selected = sorted(candidates, reverse=True)[:10]
    runs = []
    for _, folder, report in selected:
        rows = {}
        for ledger in folder.glob("product/corpus_*/results.jsonl"):
            for line in ledger.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("finished"):
                    rows[(ledger.parent.name, row.get("document"))] = row
        from packages.recovery.independent_failures import failure_category
        terminal = [r for r in rows.values() if not r.get("completed")
                    and failure_category(r) != "NON_CLAIM_PAGE"]
        review = [r for r in rows.values() if r.get("disposition") == "HITL"]
        runs.append({"run": folder.name, "status": report.get("status"),
                     "overall": report["overall"],
                     "terminal_failure_categories": dict(Counter(map(failure_category, terminal))),
                     "hitl_root_categories": dict(Counter(map(failure_category, review))),
                     "ledger_finished": len(rows),
                     "terminal_failures": [{"document": r.get("document"),
                         "reason": r.get("registration_reason"),
                         "category": failure_category(r)} for r in terminal]})
    output = ROOT / "evaluation_results" / "last_ten_runs_audit"
    output.mkdir(exist_ok=True)
    (output / "review.json").write_text(json.dumps({
        "scope": "Latest ten top-level PRODUCT cohort reports by report modification time; stopped runs retained; diagnostics and small local probes excluded. Modification time is report recency, not inference start time.",
        "runs": runs}, indent=2), encoding="utf-8")
    for run in runs:
        print(run["run"], run["status"], run["overall"])


if __name__ == "__main__":
    main()
