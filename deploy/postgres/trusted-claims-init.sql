-- Independently finalized evidence, separate from CDP extraction tables.
CREATE TABLE IF NOT EXISTS trusted_finalized_claim_fields (
    id BIGSERIAL PRIMARY KEY,
    claim_identifier VARCHAR(128) NOT NULL,
    document_identifier VARCHAR(128),
    field_name VARCHAR(128) NOT NULL,
    field_value TEXT NOT NULL,
    finalized_at TIMESTAMPTZ NOT NULL,
    source_record_version VARCHAR(64) NOT NULL,
    lineage_origin VARCHAR(64) NOT NULL,
    derived_from_cdp BOOLEAN NOT NULL DEFAULT TRUE,
    audit_reference VARCHAR(255) NOT NULL,
    CONSTRAINT uq_trusted_claim_field_version UNIQUE
        (claim_identifier, document_identifier, field_name, source_record_version)
);

CREATE INDEX IF NOT EXISTS ix_trusted_finalized_claim_lookup
    ON trusted_finalized_claim_fields (claim_identifier, finalized_at);

COMMENT ON TABLE trusted_finalized_claim_fields IS
    'Independent downstream values; CDP-derived rows are certification-ineligible';
