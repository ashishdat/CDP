import { describe, expect, it } from "vitest";
import { parseReport, percent, signedDelta } from "./report";

const report = {
  field_count: 10,
  normalized_field_accuracy: 0.98,
  critical_field_accuracy: 1,
  critical_false_accept_rate: 0,
  perfect_claim_rate: 0.8,
  straight_through_processing_rate: 0.75,
  mismatches: [],
};

describe("report helpers", () => {
  it("validates the report contract", () => {
    expect(parseReport(report).field_count).toBe(10);
    expect(() => parseReport({ ...report, field_count: "10" })).toThrow("field_count");
  });

  it("formats percentages and point deltas", () => {
    expect(percent(0.98)).toContain("98");
    expect(signedDelta(0.9, 0.98)).toBe("+8.00 pp");
  });
});
