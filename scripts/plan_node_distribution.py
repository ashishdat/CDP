#!/usr/bin/env python3
"""Preview or emit a node-aware work distribution plan for a claim list."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.work_distribution import (  # noqa: E402
    auto_local_workers,
    plan_distribution,
    resolve_topology,
    write_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items-file", type=Path, help="Newline-separated claim/document ids")
    parser.add_argument("--items", default="", help="Comma-separated claim/document ids")
    parser.add_argument("--count", type=int, default=0, help="Synthetic item count (doc-0..N)")
    parser.add_argument("--nodes", type=int, default=None)
    parser.add_argument("--node-index", type=int, default=None)
    parser.add_argument("--auto-workers", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    items: list[str] = []
    if args.items_file and args.items_file.exists():
        items = [
            line.strip()
            for line in args.items_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif args.items:
        items = [p.strip() for p in args.items.split(",") if p.strip()]
    elif args.count > 0:
        items = [f"doc-{i}" for i in range(args.count)]
    else:
        parser.error("Provide --items-file, --items, or --count")

    topology = resolve_topology(node_count=args.nodes, node_index=args.node_index)
    workers = 1
    if args.auto_workers:
        workers = auto_local_workers(
            pending=max(1, len(items) // topology.node_count),
            node_count=topology.node_count,
        )
    plan = plan_distribution(
        items,
        node_count=topology.node_count,
        local_workers_per_node=workers,
    )
    payload = plan.to_dict()
    payload["this_node"] = {
        "node_index": topology.node_index,
        "node_id": topology.node_id,
        "item_count": plan.for_node(topology.node_index).item_count,
    }
    if args.out:
        write_plan(plan, args.out)
        print(f"wrote {args.out}", flush=True)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
