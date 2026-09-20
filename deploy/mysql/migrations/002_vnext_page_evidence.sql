-- CDP vNext Phase 2: backward-compatible evidence columns (MySQL).
-- Idempotent via scripts/apply_mysql_migrations.py (skips duplicate columns).

ALTER TABLE pages
    ADD COLUMN image_quality JSON NULL;

ALTER TABLE page_classifications
    ADD COLUMN registration_evidence JSON NULL;
