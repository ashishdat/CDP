ALTER TABLE extracted_fields
    ADD COLUMN candidates JSON NOT NULL DEFAULT (JSON_ARRAY());
