"""Node-aware work distribution for multi-host claim processing.

Deterministic sharding: each claim maps to ``hash(claim_id) % node_count``.
Nodes discover topology from CLI / env (``CDP_NODE_COUNT``, ``CDP_NODE_INDEX``).
Local concurrency can auto-size from CPU and pending load.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class NodeTopology:
    """Identity of this process within a fixed-size worker fleet."""

    node_count: int
    node_index: int
    node_id: str = ""

    def __post_init__(self) -> None:
        if self.node_count < 1:
            raise ValueError("node_count must be >= 1")
        if not (0 <= self.node_index < self.node_count):
            raise ValueError(
                f"node_index {self.node_index} out of range for node_count {self.node_count}"
            )
        if not self.node_id:
            object.__setattr__(self, "node_id", f"node-{self.node_index}")


@dataclass(frozen=True)
class ShardAssignment:
    """One node's slice of the work queue."""

    node_index: int
    node_id: str
    items: tuple[str, ...]
    item_count: int


@dataclass(frozen=True)
class DistributionPlan:
    """Full fleet plan — used by coordinators and the Ops UI."""

    total_items: int
    node_count: int
    shards: tuple[ShardAssignment, ...]
    strategy: str = "stable_hash_mod"
    local_workers_per_node: int = 1
    notes: tuple[str, ...] = field(default_factory=tuple)

    def for_node(self, node_index: int) -> ShardAssignment:
        for shard in self.shards:
            if shard.node_index == node_index:
                return shard
        raise KeyError(node_index)

    def to_dict(self) -> dict:
        return {
            "total_items": self.total_items,
            "node_count": self.node_count,
            "strategy": self.strategy,
            "local_workers_per_node": self.local_workers_per_node,
            "notes": list(self.notes),
            "shards": [
                {
                    "node_index": s.node_index,
                    "node_id": s.node_id,
                    "item_count": s.item_count,
                    "items": list(s.items),
                }
                for s in self.shards
            ],
            "load_balance": {
                "min_shard": min((s.item_count for s in self.shards), default=0),
                "max_shard": max((s.item_count for s in self.shards), default=0),
                "spread": (
                    max((s.item_count for s in self.shards), default=0)
                    - min((s.item_count for s in self.shards), default=0)
                ),
            },
        }


def resolve_topology(
    *,
    node_count: int | None = None,
    node_index: int | None = None,
    node_id: str | None = None,
) -> NodeTopology:
    """Resolve topology from explicit args, else env, else single-node."""
    count = node_count
    if count is None:
        raw = (os.environ.get("CDP_NODE_COUNT") or "").strip()
        count = int(raw) if raw else 1
    index = node_index
    if index is None:
        raw = (os.environ.get("CDP_NODE_INDEX") or "").strip()
        # Kubernetes StatefulSet ordinal
        if not raw:
            raw = (os.environ.get("CDP_STATEFULSET_ORDINAL") or "").strip()
        if not raw:
            hostname = (os.environ.get("HOSTNAME") or "").strip()
            if "-" in hostname and hostname.rsplit("-", 1)[-1].isdigit():
                raw = hostname.rsplit("-", 1)[-1]
        index = int(raw) if raw else 0
    nid = (node_id or os.environ.get("CDP_NODE_ID") or "").strip()
    return NodeTopology(node_count=max(1, int(count)), node_index=int(index), node_id=nid)


def stable_shard(key: str, node_count: int) -> int:
    """Deterministic shard index for a claim/document key."""
    if node_count <= 1:
        return 0
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % node_count


def plan_distribution(
    items: Sequence[str],
    *,
    node_count: int,
    local_workers_per_node: int = 1,
    notes: Iterable[str] = (),
) -> DistributionPlan:
    """Build a full fleet plan that evenly spreads items across nodes."""
    n = max(1, int(node_count))
    buckets: list[list[str]] = [[] for _ in range(n)]
    for item in items:
        buckets[stable_shard(str(item), n)].append(str(item))
    shards = tuple(
        ShardAssignment(
            node_index=i,
            node_id=f"node-{i}",
            items=tuple(bucket),
            item_count=len(bucket),
        )
        for i, bucket in enumerate(buckets)
    )
    return DistributionPlan(
        total_items=len(items),
        node_count=n,
        shards=shards,
        local_workers_per_node=max(1, int(local_workers_per_node)),
        notes=tuple(notes),
    )


def shard_for_node(
    items: Sequence[str],
    topology: NodeTopology,
) -> list[str]:
    """Return only the items this node should process."""
    if topology.node_count <= 1:
        return [str(x) for x in items]
    return [
        str(item)
        for item in items
        if stable_shard(str(item), topology.node_count) == topology.node_index
    ]


def auto_local_workers(
    *,
    pending: int,
    node_count: int = 1,
    cpu_count: int | None = None,
    max_workers: int | None = None,
    min_workers: int = 1,
) -> int:
    """Pick per-node thread/process concurrency from pending load + CPUs.

    Heuristic: leave headroom for OCR process pools; never exceed pending.
    Cap defaults to ``max(1, cpu_count // 2)`` so VLM/DI host locks stay healthy.
    """
    if pending <= 0:
        return max(1, min_workers)
    cpus = cpu_count if cpu_count is not None else (os.cpu_count() or 2)
    # Fleet-aware: more nodes → less local fan-out needed on each host.
    base = max(1, int(cpus) // 2)
    if node_count >= 4:
        base = max(1, base // 2)
    cap = max_workers if max_workers is not None else base
    # Env override for ops
    raw = (os.environ.get("CDP_AUTO_WORKERS_MAX") or "").strip()
    if raw.isdigit():
        cap = int(raw)
    return max(min_workers, min(int(cap), int(pending), max(1, base)))


def write_plan(plan: DistributionPlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2) + "\n", encoding="utf-8")


def read_plan(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
