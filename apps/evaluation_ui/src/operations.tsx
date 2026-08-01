import { percent } from "./report";
import type { EvaluationReport } from "./types";

function duration(value: number | null): string {
  if (value == null) return "Not metered";
  if (value < 60) return `${value.toFixed(2)}s`;
  return `${(value / 60).toFixed(2)}m`;
}

function money(value: number | null): string {
  if (value == null) return "Not metered";
  if (value === 0) return "$0.000000";
  return `$${value.toFixed(6)}`;
}

export function OperationsAndCost({ report }: { report: EvaluationReport }) {
  const operations = report.operational_metrics;
  const cost = report.cost_analysis;
  const optimizedCostPerPage = cost?.projected_optimized_cost_per_page_usd ?? cost?.total_cost_per_page_usd ?? null;
  const optimizedRunCost = cost?.projected_optimized_run_cost_usd ?? cost?.actual_run_cost_usd ?? null;
  if (!operations && !cost) return null;
  return (
    <section className="operations-section">
      <div className="section-intro compact-intro">
        <div><p className="eyebrow">Runtime economics</p><h2>Performance & cost analysis</h2><p>Measured values are separated from unmetered infrastructure so the totals remain auditable.</p></div>
      </div>
      {operations && <>
        <h3 className="subsection-title">Overall metrics</h3>
        <div className="operations-grid">
          <div><span>Total pages processed</span><strong>{operations.total_pages_processed.toLocaleString()}</strong></div>
          <div><span>Processing time</span><strong>{duration(operations.processing_time_seconds)}</strong></div>
          <div><span>Average latency</span><strong>{duration(operations.average_latency_seconds)}</strong></div>
          <div><span>Pages per second</span><strong>{operations.pages_per_second == null ? "Not metered" : operations.pages_per_second.toFixed(3)}</strong></div>
          <div><span>Validated accuracy</span><strong>{percent(operations.accuracy)}</strong></div>
          <div><span>Normalized precision</span><strong>{percent(operations.precision)}</strong></div>
          <div><span>Normalized recall</span><strong>{percent(operations.recall)}</strong></div>
        </div>
        {operations.measurement_note && <p className="measurement-note">{operations.measurement_note}</p>}
      </>}
      {cost && <>
        <div className="cost-heading"><h3 className="subsection-title">Optimized component cost per page</h3><div><span>Latest optimized total / page</span><strong>{money(optimizedCostPerPage)}</strong></div></div>
        <div className="cost-table-wrap"><table className="cost-table"><thead><tr><th>Component</th><th>Cost per page</th><th>Status</th><th>Measurement basis</th></tr></thead><tbody>
          {cost.components.map((component) => <tr key={component.name}><td><strong>{component.name}</strong></td><td className="cost-value">{money(component.name === "LLM" && cost.projected_optimized_cost_per_page_usd != null ? cost.projected_optimized_cost_per_page_usd : component.cost_per_page_usd)}</td><td><span className={`cost-status ${component.status.toLowerCase().replace("_", "-")}`}>{component.status.replace("_", " ")}</span></td><td>{component.name === "LLM" && cost.projected_optimized_cost_per_page_usd != null ? "Optimized crop-only LLM route projection." : component.basis}</td></tr>)}
          <tr className="cost-total"><td><strong>Total measured</strong></td><td className="cost-value"><strong>{money(cost.total_cost_per_page_usd)}</strong></td><td><span className="cost-status measured">MEASURED</span></td><td>Actual run estimate: {money(cost.actual_run_cost_usd)} · Invoice: {cost.actual_invoice_cost_usd == null ? "unavailable" : money(cost.actual_invoice_cost_usd)}</td></tr>
        </tbody></table></div>
        {cost.projected_optimized_run_cost_usd != null && <div className="cost-projection"><div><span>Optimized policy replay</span><strong>{money(optimizedRunCost)}</strong><small>Projected run cost</small></div><div><span>Optimized cost per page</span><strong>{money(optimizedCostPerPage)}</strong><small>Current-sample projection</small></div><p>Latest optimized projection only. It scales measured provider-token cost to the active local-first route count and is not an Azure invoice.</p></div>}
        {cost.measurement_note && <p className="measurement-note">{cost.measurement_note}</p>}
      </>}
    </section>
  );
}
