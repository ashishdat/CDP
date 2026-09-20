-- Phase 7: field-level decision evidence and reproducibility metadata (MySQL).

ALTER TABLE review_tasks
    ADD COLUMN review_reason_codes JSON NOT NULL DEFAULT (JSON_ARRAY());
ALTER TABLE review_tasks
    ADD COLUMN candidate_evidence JSON NOT NULL DEFAULT (JSON_ARRAY());
ALTER TABLE review_tasks
    ADD COLUMN reference_evidence JSON NOT NULL DEFAULT (JSON_ARRAY());
ALTER TABLE review_tasks
    ADD COLUMN registration_evidence JSON NOT NULL DEFAULT (JSON_OBJECT());
ALTER TABLE review_tasks
    ADD COLUMN system_recommendation VARCHAR(1024) NULL;
ALTER TABLE review_tasks
    ADD COLUMN evidence_versions JSON NOT NULL DEFAULT (JSON_OBJECT());
