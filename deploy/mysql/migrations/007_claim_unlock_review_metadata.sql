ALTER TABLE review_tasks
    ADD COLUMN claim_impact VARCHAR(128) NULL;
ALTER TABLE review_tasks
    ADD COLUMN blocks_stp TINYINT(1) NOT NULL DEFAULT 1;
ALTER TABLE review_tasks
    ADD COLUMN single_blocker_claim TINYINT(1) NOT NULL DEFAULT 0;
ALTER TABLE review_tasks
    ADD COLUMN blocking_field_count INT NOT NULL DEFAULT 0;
ALTER TABLE review_tasks
    ADD COLUMN claim_unlock_value DOUBLE NOT NULL DEFAULT 0;

CREATE INDEX ix_review_tasks_claim_unlock_priority
    ON review_tasks (single_blocker_claim, status, created_at);
