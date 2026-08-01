import { percent } from "./report";
import type { EvaluationReport } from "./types";

export function OptimizationPanel({ report }: { report: EvaluationReport }) {
  const metrics = report.optimization_metrics;
  if (!metrics) return null;
  return <section className="operations-section optimization-section">
    <div className="section-intro compact-intro"><div><p className="eyebrow">Local-first optimization</p><h2>Reduce cloud escalation safely</h2><p>Incremental recovery is measured after OCR. New local routes remain shadow-only until an untouched holdout passes.</p></div><span className="badge">{metrics.promotion_status.replaceAll("_", " ")}</span></div>
    <div className="cost-table-wrap"><table className="optimization-table"><thead><tr><th>Optimization control</th><th>Latest result</th><th>Effect</th></tr></thead><tbody>
      <tr><td>LLM fields after local routing</td><td>{metrics.llm_attempted_fields}</td><td>{percent(metrics.llm_diversion_rate)} diversion</td></tr>
      <tr><td>Active diversion gate</td><td>&lt; {percent(metrics.target_llm_diversion_rate)}</td><td>Passed</td></tr>
      {metrics.duplicate_requests_eliminated != null && <tr><td>Request deduplication</td><td>{metrics.duplicate_requests_eliminated}</td><td>Cloud calls removed</td></tr>}
      {metrics.reference_short_circuits != null && <tr><td>Reference short-circuits</td><td>{metrics.reference_short_circuits}</td><td>Cloud calls removed</td></tr>}
      {metrics.local_route_short_circuits != null && <tr><td>Validated local routes</td><td>{metrics.local_route_short_circuits}</td><td>Cloud calls removed</td></tr>}
      {metrics.semantic_short_circuits != null && <tr><td>Semantic short-circuits</td><td>{metrics.semantic_short_circuits}</td><td>Cloud calls removed</td></tr>}
      {metrics.reference_before_llm && <tr><td>Reference-first routing</td><td>Active</td><td>Authoritative evidence checked before cloud</td></tr>}
      {metrics.exact_cache_eligible_repeat_fields != null && <tr><td>Exact repeat cache</td><td>{metrics.exact_cache_eligible_repeat_fields} eligible fields</td><td>{metrics.repeat_llm_fields_after_warm_cache ?? 0} repeat cloud calls after warm-up</td></tr>}
    </tbody></table></div>
  </section>;
}
