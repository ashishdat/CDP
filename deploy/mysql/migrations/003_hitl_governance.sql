-- Phase 5: optimistic review concurrency and append-only audit evidence (MySQL).

ALTER TABLE review_tasks ADD COLUMN version INT NOT NULL DEFAULT 0;
ALTER TABLE review_tasks ADD COLUMN claimed_at DATETIME(6) NULL;

CREATE TABLE IF NOT EXISTS review_audit_events (
    audit_id CHAR(36) NOT NULL PRIMARY KEY,
    task_id CHAR(36) NOT NULL,
    document_id CHAR(36) NOT NULL,
    field_name VARCHAR(128) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    task_version INT NOT NULL,
    decision_hash VARCHAR(64) NULL,
    reason_code VARCHAR(128) NOT NULL,
    occurred_at DATETIME(6) NOT NULL,
    KEY ix_review_audit_task_id (task_id),
    KEY ix_review_audit_document_id (document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
