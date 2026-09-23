import { useEffect, useState } from "react";

type Shard = {
  node_index: number;
  node_id: string;
  item_count: number;
  items?: string[];
};

type WorkPlan = {
  total_items: number;
  node_count: number;
  strategy: string;
  local_workers_per_node: number;
  notes?: string[];
  shards: Shard[];
  load_balance?: { min_shard: number; max_shard: number; spread: number };
};

export function ScalePanel({ planUrl = "/reports/work_distribution_plan.json" }: { planUrl?: string }) {
  const [plan, setPlan] = useState<WorkPlan | null>(null);
  const [nodes, setNodes] = useState(4);
  const [preview, setPreview] = useState<WorkPlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(planUrl)
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((payload) => {
          if (!cancelled) {
            setPlan(payload);
            setError(null);
          }
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message);
        });
    };
    load();
    const id = window.setInterval(load, 20000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [planUrl]);

  useEffect(() => {
    let cancelled = false;
    fetch(`/scale/preview?nodes=${nodes}&count=${plan?.total_items || 600}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        if (!cancelled && payload) setPreview(payload);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [nodes, plan?.total_items]);

  const shown = preview || plan;

  return (
    <section className="ops-panel">
      <header className="ops-header">
        <div>
          <h3>Node-aware load distribution</h3>
          <p className="ops-sub">
            Claims shard with <code>sha256(id) % nodes</code>. Change node count — load rebalances
            automatically. Live plan from the active cascade run when present.
          </p>
        </div>
      </header>

      <div className="scale-controls">
        <label>
          Nodes
          <input
            type="range"
            min={1}
            max={16}
            value={nodes}
            onChange={(e) => setNodes(Number(e.target.value))}
          />
          <strong>{nodes}</strong>
        </label>
        {shown?.load_balance ? (
          <p className="ops-note">
            Spread {shown.load_balance.spread} (min {shown.load_balance.min_shard} / max{" "}
            {shown.load_balance.max_shard}) · workers/node {shown.local_workers_per_node}
          </p>
        ) : null}
      </div>

      {error && !shown ? <p className="ops-empty">No plan yet ({error}). Adjust nodes to preview.</p> : null}

      {shown ? (
        <div className="scale-bars">
          {shown.shards.map((s) => {
            const max = Math.max(...shown.shards.map((x) => x.item_count), 1);
            const pct = Math.round((s.item_count / max) * 100);
            return (
              <div key={s.node_index} className="scale-bar-row">
                <span className="scale-bar-label">{s.node_id}</span>
                <div className="scale-bar-track">
                  <div className="scale-bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <strong className="scale-bar-count">{s.item_count}</strong>
              </div>
            );
          })}
          <p className="ops-note">
            total {shown.total_items} · strategy {shown.strategy}
            {plan && !preview ? " · live run plan" : " · preview"}
          </p>
        </div>
      ) : null}
    </section>
  );
}
