"""Unit tests for node-aware work distribution."""

from __future__ import annotations

import pytest

from packages.work_distribution import (
    auto_local_workers,
    plan_distribution,
    resolve_topology,
    shard_for_node,
    stable_shard,
)


def test_stable_shard_is_deterministic_and_covers_all_nodes() -> None:
    items = [f"Group A/M048DOC.{i:03d}" for i in range(200)]
    nodes = 5
    buckets = {i: 0 for i in range(nodes)}
    for item in items:
        idx = stable_shard(item, nodes)
        assert 0 <= idx < nodes
        assert stable_shard(item, nodes) == idx
        buckets[idx] += 1
    # Spread within ±15% of fair share for n=200 / 5
    fair = len(items) / nodes
    assert min(buckets.values()) >= fair * 0.7
    assert max(buckets.values()) <= fair * 1.3


def test_shard_for_node_partitions_without_overlap() -> None:
    items = [f"claim-{i}" for i in range(100)]
    topo0 = resolve_topology(node_count=4, node_index=0)
    topo1 = resolve_topology(node_count=4, node_index=1)
    a = set(shard_for_node(items, topo0))
    b = set(shard_for_node(items, topo1))
    assert a.isdisjoint(b)
    all_shards = []
    for i in range(4):
        all_shards.extend(shard_for_node(items, resolve_topology(node_count=4, node_index=i)))
    assert sorted(all_shards) == sorted(items)


def test_plan_distribution_balances_load() -> None:
    items = [f"doc-{i}" for i in range(60)]
    plan = plan_distribution(items, node_count=3, local_workers_per_node=2)
    assert plan.total_items == 60
    assert plan.node_count == 3
    counts = [s.item_count for s in plan.shards]
    assert sum(counts) == 60
    assert max(counts) - min(counts) <= 8
    payload = plan.to_dict()
    assert payload["load_balance"]["spread"] == max(counts) - min(counts)


def test_resolve_topology_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDP_NODE_COUNT", "3")
    monkeypatch.setenv("CDP_NODE_INDEX", "2")
    topo = resolve_topology()
    assert topo.node_count == 3
    assert topo.node_index == 2


def test_auto_local_workers_scales_with_nodes() -> None:
    solo = auto_local_workers(pending=100, node_count=1, cpu_count=8, max_workers=8)
    fleet = auto_local_workers(pending=100, node_count=8, cpu_count=8, max_workers=8)
    assert solo >= fleet
    assert auto_local_workers(pending=0, node_count=2, cpu_count=8) == 1
    assert auto_local_workers(pending=2, node_count=1, cpu_count=16) <= 2


def test_single_node_gets_all_work() -> None:
    items = ["a", "b", "c"]
    topo = resolve_topology(node_count=1, node_index=0)
    assert shard_for_node(items, topo) == items
