-- Local integration schema only. Loading CDP-derived values does not make them
-- independent truth; the backfill coordinator will reject such lineage.
CREATE TABLE IF NOT EXISTS finalized_claim_fields (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    claim_identifier VARCHAR(128) NOT NULL,
    document_identifier VARCHAR(128) NULL,
    field_name VARCHAR(128) NOT NULL,
    field_value TEXT NOT NULL,
    finalized_at DATETIME(6) NOT NULL,
    source_record_version VARCHAR(64) NOT NULL,
    lineage_origin VARCHAR(64) NOT NULL,
    derived_from_cdp BOOLEAN NOT NULL DEFAULT TRUE,
    audit_reference VARCHAR(255) NOT NULL,
    UNIQUE KEY uq_finalized_claim_field_version
        (claim_identifier, document_identifier, field_name, source_record_version),
    KEY ix_finalized_claim_lookup (claim_identifier, finalized_at)
);

CREATE USER IF NOT EXISTS 'holdout_reader'@'%' IDENTIFIED BY
    '${TRUSTED_CLAIMS_MYSQL_READER_PASSWORD}';
GRANT SELECT ON claims_truth.finalized_claim_fields TO 'holdout_reader'@'%';
FLUSH PRIVILEGES;
