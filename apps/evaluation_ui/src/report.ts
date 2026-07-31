import type { EvaluationReport } from "./types";

const requiredNumbers = [
  "field_count",
  "normalized_field_accuracy",
  "critical_field_accuracy",
  "critical_false_accept_rate",
  "perfect_claim_rate",
  "straight_through_processing_rate",
] as const;

export function parseReport(value: unknown): EvaluationReport {
  if (!value || typeof value !== "object") throw new Error("Report must be a JSON object.");
  const report = value as Record<string, unknown>;
  for (const key of requiredNumbers) {
    if (typeof report[key] !== "number") throw new Error(`Report is missing numeric '${key}'.`);
  }
  if (!Array.isArray(report.mismatches)) throw new Error("Report is missing 'mismatches'.");
  return value as EvaluationReport;
}

export function percent(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  }).format(value);
}

export function signedDelta(before: number, after: number): string {
  const points = (after - before) * 100;
  return `${points >= 0 ? "+" : ""}${points.toFixed(2)} pp`;
}
