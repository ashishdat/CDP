"""Compare handwriting providers on the same frozen reviewed-crop manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.metrics import character_error_rate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument(
        "--provider", action="append", default=[],
        help="NAME=provider-results.jsonl",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    labels = {
        (row["document_id"], row["field_name"]): row
        for row in _jsonl(args.labels)
        if row.get("verified_value") is not None
    }
    results = []
    for provider_arg in args.provider:
        name, path = provider_arg.split("=", 1)
        predictions = {
            (row["document_id"], row["field_name"]): row
            for row in _jsonl(Path(path))
        }
        exact = critical_false = latency = cost = 0.0
        count = critical_accepted = 0
        cer = 0.0
        for key, label in labels.items():
            prediction = predictions.get(key, {})
            expected = str(label["verified_value"])
            actual = str(prediction.get("value") or "")
            ok = expected == actual
            count += 1
            exact += ok
            cer += character_error_rate(expected, actual)
            latency += float(prediction.get("latency_ms", 0))
            cost += float(prediction.get("cost_usd", 0))
            if label.get("critical") and prediction.get("accepted"):
                critical_accepted += 1
                critical_false += not ok
        results.append({
            "provider": name,
            "field_count": count,
            "exact_accuracy": exact / count if count else 0,
            "character_error_rate": cer / count if count else 0,
            "critical_false_accept_rate": (
                critical_false / critical_accepted if critical_accepted else 0
            ),
            "average_latency_ms": latency / count if count else 0,
            "average_cost_usd": cost / count if count else 0,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    raise SystemExit(main())
