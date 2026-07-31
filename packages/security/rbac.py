"""RBAC hooks: role/permission model and a FastAPI dependency factory.

This is deliberately a *hook*, not a full auth system -- it reads a role
from a request header (`X-User-Role`) so it's wireable without picking an
identity provider up front. Swapping the header read in `get_current_role`
for a real JWT/OAuth claim lookup is the one place a production deployment
needs to change; every route's `require_permission(...)` dependency stays
the same.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    REVIEWER = "reviewer"
    VIEWER = "viewer"
    SERVICE = "service"  # machine-to-machine (workers, batch jobs)


class Permission(StrEnum):
    INGEST_DOCUMENT = "ingest_document"
    VIEW_CLAIM = "view_claim"
    REVIEW_FIELD = "review_field"
    CORRECT_FIELD = "correct_field"
    DELETE_DOCUMENT = "delete_document"
    ADMIN_CONFIG = "admin_config"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.REVIEWER: frozenset(
        {Permission.VIEW_CLAIM, Permission.REVIEW_FIELD, Permission.CORRECT_FIELD}
    ),
    Role.VIEWER: frozenset({Permission.VIEW_CLAIM}),
    Role.SERVICE: frozenset({Permission.INGEST_DOCUMENT, Permission.VIEW_CLAIM}),
}


class PermissionDeniedError(PermissionError):
    def __init__(self, role: Role, permission: Permission) -> None:
        super().__init__(f"role '{role.value}' lacks permission '{permission.value}'")
        self.role = role
        self.permission = permission


def role_has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def require_permission(role: Role, permission: Permission) -> None:
    if not role_has_permission(role, permission):
        raise PermissionDeniedError(role, permission)
