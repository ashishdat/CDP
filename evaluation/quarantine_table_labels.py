"""Quarantine invalid table-label evidence without deleting audit history."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

SOURCE_LABELS = Path("evaluation_data/table_labels")
SOURCE_RESULTS = Path("evaluation_results/table_shadow_v2")
QUARANTINE = SOURCE_LABELS / "quarantine/table-shadow-v2"
REASON = "SOURCE_CROP_GEOMETRY_NOT_VALIDATED"


def _annotate_events(source: Path, output: Path) -> int:
    count = 0
    with source.open(encoding="utf-8") as incoming, output.open(
        "w", encoding="utf-8"
    ) as outgoing:
        for line in incoming:
            if not line.strip():
                continue
            event = json.loads(line)
            event["evaluation_eligible"] = False
            event["training_eligible"] = False
            event["quarantine_reason"] = REASON
            outgoing.write(json.dumps(event, sort_keys=True) + "\n")
            count += 1
    return count


def quarantine() -> dict:
    if QUARANTINE.exists():
        raise FileExistsError(
            f"{QUARANTINE} already exists; quarantine is append-only"
        )
    QUARANTINE.mkdir(parents=True)
    manifest = SOURCE_LABELS / "cell_label_manifest.jsonl"
    events = SOURCE_LABELS / "approved_cell_labels.jsonl"
    moved = []
    for source in (manifest, events):
        if source.exists():
            destination = QUARANTINE / source.name
            shutil.move(str(source), destination)
            moved.append(str(destination))
    event_count = 0
    quarantined_events = QUARANTINE / "quarantined_review_events.jsonl"
    moved_events = QUARANTINE / events.name
    if moved_events.exists():
        event_count = _annotate_events(moved_events, quarantined_events)
    if SOURCE_RESULTS.exists():
        result_destination = QUARANTINE / "candidate_results"
        shutil.move(str(SOURCE_RESULTS), result_destination)
        moved.append(str(result_destination))
    metadata = {
        "quarantine_version": "table-shadow-v2",
        "created_at": datetime.now(UTC).isoformat(),
        "evaluation_eligible": False,
        "training_eligible": False,
        "quarantine_reason": REASON,
        "review_event_count": event_count,
        "moved": moved,
    }
    (QUARANTINE / "quarantine_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> int:
    print(json.dumps(quarantine(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
