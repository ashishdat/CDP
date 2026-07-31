# Trusted MySQL claims source

The trusted source is deliberately separate from the CDP operational database.
Only independently finalized values may enter the official holdout.

## External MySQL

Create a read-only account with `SELECT` access to a view or table matching
`finalized_claim_fields`, then set:

```text
DOWNSTREAM_CLAIMS_DATABASE_URL=mysql+pymysql://holdout_reader:<secret>@<host>:3306/<database>
DOWNSTREAM_CLAIMS_TABLE=finalized_claim_fields
DOWNSTREAM_CLAIMS_SOURCE_SYSTEM=<approved-system-id>
```

The required columns are documented in
`deploy/mysql/trusted-claims-init.sql`. `derived_from_cdp` and
`lineage_origin` are mandatory safety fields. A finalized record generated
from CDP, Azure, or OCR consensus is rejected.

Run the readiness check:

```powershell
.\.venv\Scripts\python.exe -m evaluation.source_readiness
```

## Local integration profile

The local MySQL profile tests connectivity and schema behavior; its records are
not automatically authoritative:

```powershell
docker compose --profile trusted-source up -d trusted-claims-mysql
```

Use port `3307` from the Windows host and port `3306` from another Compose
container. Change both local passwords in `.env` before starting the service.
