"""FastAPI wiring for `packages.security.rbac`. Kept separate from
`rbac.py` so the role/permission model itself has no framework
dependency and is trivially unit-testable.

`get_current_role` reads the role from an `X-User-Role` header -- a hook,
not a real identity provider (see rbac.py's module docstring). Swap this
one function for a JWT/OAuth claim lookup in a production deployment;
every route using `require_permission(...)` stays unchanged.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from packages.security.rbac import Permission, Role, role_has_permission


def get_current_role(x_user_role: str = Header(default=Role.VIEWER.value)) -> Role:
    try:
        return Role(x_user_role)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"unknown role '{x_user_role}'") from exc


def require_permission(permission: Permission):
    def dependency(role: Role = Depends(get_current_role)) -> Role:
        if not role_has_permission(role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"role '{role.value}' lacks permission '{permission.value}'",
            )
        return role

    return dependency
