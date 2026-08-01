"""RBAC hooks, structured PHI redaction, and the retention/deletion
workflow (against fakes -- no real DB/object store needed)."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from packages.domain.audit import AuditEvent
from packages.domain.common import ObjectRef
from packages.domain.document import Document
from packages.domain.enums import AuditEventType, DocumentStatus, SourceFormat
from packages.security.rbac import (
    Permission,
    PermissionDeniedError,
    Role,
    require_permission,
    role_has_permission,
)
from packages.security.redaction import redact_phi_processor, redact_value
from packages.security.retention import RetentionPolicy, RetentionService

# --- RBAC -----------------------------------------------------------------


def test_admin_has_every_permission():
    for permission in Permission:
        assert role_has_permission(Role.ADMIN, permission)


def test_viewer_cannot_correct_fields():
    assert not role_has_permission(Role.VIEWER, Permission.CORRECT_FIELD)


def test_reviewer_can_correct_but_not_delete():
    assert role_has_permission(Role.REVIEWER, Permission.CORRECT_FIELD)
    assert not role_has_permission(Role.REVIEWER, Permission.DELETE_DOCUMENT)


def test_require_permission_raises_for_disallowed_role():
    with pytest.raises(PermissionDeniedError):
        require_permission(Role.VIEWER, Permission.CORRECT_FIELD)


def test_require_permission_passes_silently_when_allowed():
    require_permission(Role.ADMIN, Permission.DELETE_DOCUMENT)  # must not raise


# --- redaction -----------------------------------------------------------------


def test_redact_value_masks_known_phi_keys():
    result = redact_value({"patient_name": "Doe, John", "field_name": "patient_name"})
    assert result["patient_name"] == "[REDACTED]"
    assert result["field_name"] == "patient_name"  # key name itself is safe


def test_redact_value_recurses_into_nested_structures():
    result = redact_value(
        {
            "header_fields": [
                {"field_name": "patient_dob", "raw_value": "1990-01-01"},
                {"field_name": "total_charge", "raw_value": "175.00"},
            ]
        }
    )
    assert result["header_fields"][0]["raw_value"] == "[REDACTED]"
    assert result["header_fields"][1]["raw_value"] == "[REDACTED]"
    assert result["header_fields"][0]["field_name"] == "patient_dob"


def test_redact_phi_processor_redacts_top_level_event_dict():
    event = {"event": "field extracted", "npi": "1396827531", "confidence": 0.95}
    redacted = redact_phi_processor(None, "info", event)
    assert redacted["npi"] == "[REDACTED]"
    assert redacted["confidence"] == 0.95
    assert redacted["event"] == "field extracted"


def test_non_phi_values_pass_through_unchanged():
    result = redact_value({"document_id": "abc-123", "status": "PREPARED", "page_count": 3})
    assert result == {"document_id": "abc-123", "status": "PREPARED", "page_count": 3}


# --- retention -----------------------------------------------------------------


class FakeRetentionRepository:
    def __init__(self, documents: list[Document]) -> None:
        self._documents = {d.document_id: d for d in documents}
        self.deleted_ids: list[UUID] = []

    def find_received_before(self, tenant_id: str, cutoff: datetime) -> list[Document]:
        return [
            d
            for d in self._documents.values()
            if d.tenant_id == tenant_id and d.received_at < cutoff
        ]

    def delete(self, document_id: UUID) -> None:
        self.deleted_ids.append(document_id)
        self._documents.pop(document_id, None)


class FakeObjectDeleter:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_object(self, bucket: str, key: str) -> None:
        self.deleted.append((bucket, key))


def _document(tenant_id: str, received_at: datetime) -> Document:
    return Document(
        tenant_id=tenant_id,
        correlation_id=uuid4(),
        source_filename="claim.tiff",
        detected_format=SourceFormat.TIFF,
        sha256="a" * 64,
        status=DocumentStatus.COMPLETED,
        original_object=ObjectRef(bucket="idp-documents", key="documents/aa/bb/hash.tiff"),
        pipeline_version="0.1.0",
        schema_version="1.0",
        received_at=received_at,
    )


def test_retention_sweep_deletes_only_expired_documents_for_the_right_tenant():
    old_doc = _document("tenant-1", datetime(2020, 1, 1, tzinfo=UTC))
    recent_doc = _document("tenant-1", datetime(2030, 1, 1, tzinfo=UTC))
    other_tenant_doc = _document("tenant-2", datetime(2020, 1, 1, tzinfo=UTC))

    repo = FakeRetentionRepository([old_doc, recent_doc, other_tenant_doc])
    deleter = FakeObjectDeleter()
    service = RetentionService(repo, deleter)

    events = service.run_retention_sweep(
        RetentionPolicy(tenant_id="tenant-1", retention_days=30),
        as_of=datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert repo.deleted_ids == [old_doc.document_id]
    assert deleter.deleted == [("idp-documents", "documents/aa/bb/hash.tiff")]
    assert len(events) == 1
    assert events[0].event_type == AuditEventType.RECORD_DELETED
    assert events[0].document_id == old_doc.document_id


def test_retention_sweep_is_a_no_op_when_nothing_expired():
    repo = FakeRetentionRepository([_document("tenant-1", datetime(2030, 1, 1, tzinfo=UTC))])
    deleter = FakeObjectDeleter()
    service = RetentionService(repo, deleter)

    events = service.run_retention_sweep(
        RetentionPolicy(tenant_id="tenant-1", retention_days=30),
        as_of=datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert events == []
    assert deleter.deleted == []


def test_delete_document_writes_immutable_audit_event_with_no_raw_phi():
    doc = _document("tenant-1", datetime(2020, 1, 1, tzinfo=UTC))
    repo = FakeRetentionRepository([doc])
    deleter = FakeObjectDeleter()
    service = RetentionService(repo, deleter)

    event = service.delete_document(doc, actor="user:reviewer1")

    assert isinstance(event, AuditEvent)
    assert event.actor == "user:reviewer1"
    # audit details are ids/hashes/reasons only -- never raw claim data
    assert set(event.details.keys()) <= {"sha256", "reason"}
