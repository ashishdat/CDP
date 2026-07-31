import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("evaluation dashboard", () => {
  it("loads a report and renders side-by-side mismatches", async () => {
    render(<App />);
    const input = screen.getAllByLabelText(/choose report|load evaluation json/i)[0];
    const file = new File(
      [JSON.stringify({
        field_count: 2,
        raw_exact_match_accuracy: 0.5,
        normalized_field_accuracy: 0.5,
        critical_field_accuracy: 1,
        character_error_rate: 0.1,
        missing_field_rate: 0,
        false_accept_rate: 0.5,
        critical_false_accept_rate: 0,
        false_review_rate: 0,
        perfect_claim_rate: 0,
        straight_through_processing_rate: 0,
        hitl_rate: 0.5,
        accuracy_before_fallback: 0.4,
        accuracy_after_fallback: 0.8,
        accuracy_by_field: { total_charge: 0.5 },
        accuracy_by_form_type: { CMS1500: 0.5 },
        accuracy_by_extraction_method: { REGIONAL_PADDLEOCR: 0.5 },
        accuracy_by_image_quality_bucket: { good: 0.5 },
        mismatches: [{
          document_id: "A-01", form_type: "CMS1500", field_name: "total_charge",
          expected_value: "100.00", extracted_value: "900.00", normalized_value: "900.00",
          ocr_confidence: 0.99, validation_result: "INVALID",
          extraction_method: "REGIONAL_PADDLEOCR", bounding_box: null,
          crop_reference: null, failure_category: "FALSE_ACCEPT",
        }],
      })],
      "evaluation.json",
      { type: "application/json" },
    );
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("Extraction accuracy")).toBeInTheDocument();
    expect(screen.getByText("100.00")).toBeInTheDocument();
    expect(screen.getByText("900.00")).toBeInTheDocument();
    expect(screen.getByText("FALSE_ACCEPT")).toBeInTheDocument();
  });
});
