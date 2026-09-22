#!/usr/bin/env python3
"""Seed a small document + OPEN review task for Evaluation UI E2E demos.

Works against the shared platform DATABASE_URL (MySQL in Compose or sqlite).
Placeholders are explicitly marked DEMO_SEED — not financial claim values.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.human_review_api.db.models import Base as ReviewBase  # noqa: E402
from apps.human_review_api.db.repository import ReviewTaskRepository  # noqa: E402
from apps.human_review_api.db.session import make_session_factory as make_review_sf  # noqa: E402
from apps.ingestion_api.db.models import DocumentORM, ExtractedFieldORM  # noqa: E402
from apps.ingestion_api.db.session import make_session_factory as make_ingest_sf  # noqa: E402
from packages.domain.review import ReviewTask  # noqa: E402

DEMO_NS = UUID("a7c0e2b1-4d5f-6a70-8b9c-0d1e2f3a4b5c")


def main() -> int:
    database_url = os.environ.get(
        "DATABASE_URL", "mysql+pymysql://idp:idp_dev_password@127.0.0.1:3306/idp"
    )
    ingest_sf = make_ingest_sf(database_url)
    bind = ingest_sf.kw["bind"]
    ReviewBase.metadata.create_all(bind)
    review_sf = make_review_sf(database_url)

    doc_id = uuid5(DEMO_NS, "demo-document")
    claim_id = uuid5(DEMO_NS, "demo-claim")
    field_id = uuid5(DEMO_NS, "demo-field-provider-npi")
    corr_id = uuid5(DEMO_NS, "demo-correlation")
    task_id = uuid5(DEMO_NS, f"task:{doc_id}:{field_id}")
    now = datetime.now(UTC)
    sha = hashlib.sha256(b"demo-seed-document").hexdigest()

    with ingest_sf() as session:
        if session.get(DocumentORM, doc_id) is None:
            session.add(
                DocumentORM(
                    document_id=doc_id,
                    tenant_id="prototype-ui",
                    correlation_id=corr_id,
                    source_filename="DEMO_SEED_cms1500.png",
                    detected_format="PNG",
                    bundle_type="A_CMS1500_SINGLE",
                    sha256=sha,
                    page_count=1,
                    status="NEEDS_REVIEW",
                    original_object={
                        "bucket": "idp-documents",
                        "key": f"demo/{sha}_DEMO_SEED_cms1500.png",
                        "content_type": "image/png",
                        "sha256": sha,
                    },
                    pipeline_version="0.1.0",
                    schema_version="1.0",
                    received_at=now,
                    updated_at=now,
                    claim_id=claim_id,
                )
            )
            session.add(
                ExtractedFieldORM(
                    field_id=field_id,
                    document_id=doc_id,
                    field_name="provider_npi",
                    raw_value="DEMO_SEED",
                    normalized_value="DEMO_SEED",
                    confidence=0.41,
                    page_number=1,
                    bounding_box={"x0": 0.1, "y0": 0.1, "x1": 0.3, "y1": 0.15},
                    extraction_method="DEMO_SEED",
                    model_name="demo",
                    model_version="0",
                    template_version="0",
                    validation_status="FAILED",
                    validation_reasons=["DEMO_SEED_REQUIRES_REVIEW"],
                    candidates=[],
                    is_critical=True,
                    disposition="HITL",
                    reference_evidence={},
                    created_at=now,
                )
            )
            session.commit()
            print(f"seeded document {doc_id}")
        else:
            print(f"document already present {doc_id}")

    with review_sf() as session:
        repo = ReviewTaskRepository(session)
        if repo.get(task_id) is None:
            repo.add(
                ReviewTask(
                    task_id=task_id,
                    claim_id=claim_id,
                    document_id=doc_id,
                    field_id=field_id,
                    field_name="provider_npi",
                    page_number=1,
                    ocr_candidates=["DEMO_SEED", "1234567890"],
                    validation_errors=["DEMO_SEED_REQUIRES_REVIEW", "fails NPI checksum"],
                    review_reason_codes=["DEMO_SEED"],
                    blocks_stp=True,
                    single_blocker_claim=True,
                    blocking_field_count=1,
                )
            )
            session.commit()
            print(f"seeded review task {task_id}")
        else:
            print(f"review task already present {task_id}")

    print(
        json.dumps(
            {
                "document_id": str(doc_id),
                "task_id": str(task_id),
                "open": "http://localhost:8180",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
