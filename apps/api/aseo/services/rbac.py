"""Role-based access control matrix.

Org roles: owner > admin > editor > analyst > viewer. ``client`` is an agency client user
who may only see the workspaces they are explicitly assigned to and can read reports,
findings and approve changes only if granted a workspace role that allows it.
"""

from __future__ import annotations

ROLES = ["owner", "admin", "editor", "analyst", "viewer", "client"]
ROLE_RANK = {"owner": 50, "admin": 40, "editor": 30, "analyst": 20, "viewer": 10, "client": 5}

_ALL = set(ROLES)
_STAFF_WRITE = {"owner", "admin", "editor"}
_CONTRIB = {"owner", "admin", "editor", "analyst"}
_ADMIN = {"owner", "admin"}

PERMISSIONS: dict[str, set[str]] = {
    "org:read": _ALL,
    "org:manage": _ADMIN,
    "members:manage": _ADMIN,
    "billing:read": _ADMIN,
    "billing:manage": {"owner"},
    "workspace:read": _ALL,
    "workspace:manage": _ADMIN,
    "site:read": _ALL,
    "site:create": _STAFF_WRITE,
    "site:manage": _STAFF_WRITE,
    "connector:manage": _ADMIN,
    "crawl:run": _CONTRIB,
    "finding:read": _ALL,
    "finding:manage": _CONTRIB,
    "plan:create": _CONTRIB,
    "change:propose": _CONTRIB,
    "change:approve": _STAFF_WRITE,
    "change:execute": _STAFF_WRITE,
    "change:rollback": _STAFF_WRITE,
    "automation:read": _ALL - {"client"},
    "automation:manage": _ADMIN,
    "killswitch:toggle": _ADMIN,
    "content:write": _CONTRIB,
    "content:approve": _STAFF_WRITE,
    "copilot:use": _CONTRIB,
    "analytics:read": _ALL,
    "report:read": _ALL,
    "report:create": _CONTRIB,
    "audit:read": _ADMIN,
    "usage:read": _ADMIN,
    "settings:manage": _ADMIN,
}


def has_permission(role: str | None, permission: str) -> bool:
    if role is None:
        return False
    allowed = PERMISSIONS.get(permission)
    if allowed is None:
        raise KeyError(f"unknown permission {permission}")
    return role in allowed


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


def sees_all_workspaces(org_role: str) -> bool:
    return org_role in _ADMIN
