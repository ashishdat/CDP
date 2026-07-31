export type Mismatch = {
  document_id: string;
  form_type: string;
  field_name: string;
  expected_value: string | null;
  extracted_value: string | null;
  normalized_value: string | null;
  ocr_confidence: number | null;
  validation_result: string;
  extraction_method: string;
  bounding_box: Record<string, number> | null;
  crop_reference: string | null;
  failure_category: string;
};

export type EvaluationReport = {
  report_metadata?: {
    dataset_label?: string;
    synthetic_demo?: boolean;
    generated_at?: string;
  };
  field_count: number;
  raw_exact_match_accuracy: number;
  normalized_field_accuracy: number;
  critical_field_accuracy: number;
  character_error_rate: number;
  missing_field_rate: number;
  false_accept_rate: number;
  critical_false_accept_rate: number;
  false_review_rate: number;
  perfect_claim_rate: number;
  straight_through_processing_rate: number;
  hitl_rate: number;
  accuracy_before_fallback: number;
  accuracy_after_fallback: number;
  accuracy_by_field: Record<string, number>;
  accuracy_by_form_type: Record<string, number>;
  accuracy_by_extraction_method: Record<string, number>;
  accuracy_by_image_quality_bucket: Record<string, number>;
  mismatches: Mismatch[];
};
