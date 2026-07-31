"""Security building blocks: malware-scan interface (Phase 1), RBAC hooks,
structured PHI redaction, and the retention/deletion workflow (Phase 5).
Signed object-store URLs are `packages.storage.object_store.ObjectStore.
signed_get_url` (Phase 1) -- used by `apps/human_review_api` for crop
access."""

from packages.security.malware_scan import MalwareScanner, NoOpMalwareScanner, ScanResult
from packages.security.rbac import (
    Permission,
    PermissionDeniedError,
    Role,
    require_permission,
    role_has_permission,
)
from packages.security.redaction import redact_phi_processor, redact_value
from packages.security.retention import (
    DocumentRetentionRepository,
    ObjectDeleter,
    RetentionPolicy,
    RetentionService,
)

__all__ = [
    "DocumentRetentionRepository",
    "MalwareScanner",
    "NoOpMalwareScanner",
    "ObjectDeleter",
    "Permission",
    "PermissionDeniedError",
    "RetentionPolicy",
    "RetentionService",
    "Role",
    "ScanResult",
    "redact_phi_processor",
    "redact_value",
    "require_permission",
    "role_has_permission",
]
