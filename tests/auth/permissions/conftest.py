import uuid

import pytest

from backend.auth.permissions.model import PermissionScope, Role, Permission, DEFAULT_EVERYONE_ROLE_ID, RolePermission, \
    STATIC_ROLE_ID, ScopedPermission

test_permissions = [
    ("message", "send", [*PermissionScope]),
    ("workspace", "view", [*PermissionScope]),
    ("channel", "view", [*PermissionScope]),
    ("workspace.role", "view", [*PermissionScope]),
    ("workspace.role", "manage", [*PermissionScope]),
    ("test", "view", [*PermissionScope]),
]


@pytest.fixture
def make_role(db_session, test_user, get_perm, test_workspace):
    """Factory fixture to create a Role with permissions from "resource:action:scope" strings."""

    def _make_role(name=None, permissions=None, workspace_id=test_workspace.id, priority=1, user=test_user):
        if name is None:
            name = f"role_{uuid.uuid4().hex[:8]}"

        if permissions is None:
            permissions = []

        role = Role(name=name, workspace_id=workspace_id, priority=priority)

        for perm_str in permissions:
            scoped_perm = ScopedPermission.from_str(perm_str)
            perm = get_perm(scoped_perm.resource, scoped_perm.action)
            role.permissions.append(RolePermission(permission_id=perm.id, scope=scoped_perm.scope))

        db_session.add(role)
        db_session.flush()
        if user:
            role.users.append(user)
        return role

    return _make_role


@pytest.fixture(scope="session", autouse=True)
def register_permissions(db_session):
    everyone = Role(
        id=DEFAULT_EVERYONE_ROLE_ID,
        name="everyone",
        description=None,
        workspace_id=None,
        priority=0,
    )

    static = Role(
        id=STATIC_ROLE_ID,
        name="static",
        description="Static role, contains permissions that are always active regardless of workspace or channel.",
        workspace_id=None,
        priority=0,
    )
    permissions = [
        Permission(resource=resource, action=action, allowed_scopes=scopes)
        for resource, action, scopes
        in test_permissions
    ]
    db_session.add_all(permissions)
    db_session.flush()

    for perm in permissions:
        if PermissionScope.OWN in perm.allowed_scopes:
            static.permissions.append(RolePermission(permission_id=perm.id, scope=PermissionScope.OWN))

    db_session.add_all([everyone, static])
    db_session.commit()
