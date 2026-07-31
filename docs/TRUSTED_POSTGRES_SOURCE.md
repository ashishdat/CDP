# Trusted PostgreSQL source

The trusted downstream table may share the existing PostgreSQL server, but it
is separate from CDP extraction tables. Only independently finalized records
with verifiable lineage are certification-eligible.

Configure `DOWNSTREAM_CLAIMS_DATABASE_URL`, `DOWNSTREAM_CLAIMS_TABLE`, and
`DOWNSTREAM_CLAIMS_SOURCE_SYSTEM` in `.env`. Production should use a read-only
database role for scanning and backfill.

For an already initialized PostgreSQL volume, create the table once:

```powershell
.\.venv\Scripts\python.exe -m evaluation.initialize_trusted_postgres
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m evaluation.source_readiness
```

Docker initializes new volumes automatically. Existing volumes require the
explicit initializer because `docker-entrypoint-initdb.d` runs only once.

Never copy CDP predictions into this table as truth. Rows with
`derived_from_cdp=true`, or lineage `CDP`, `AZURE`, or `OCR_CONSENSUS`, are
rejected by the holdout coordinator.
