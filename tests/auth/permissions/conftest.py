import pytest
from sqlalchemy import delete, select

from backend.auth.permissions.core import permission_registry
from backend.auth.permissions.model import PermissionScope, Role, Permission, EVERYONE_ID, RolePermission

test_permissions = [
    ("message", "send", [*PermissionScope]),
    ("workspace", "read", [PermissionScope.ANY]),
    ("workspace", "write", [PermissionScope.ANY]),
    ("role", "view", [PermissionScope.WORKSPACE, PermissionScope.CHANNEL, PermissionScope.ANY]),
    ("role", "create", [PermissionScope.WORKSPACE, PermissionScope.CHANNEL, PermissionScope.ANY]),
    ("role", "edit", [PermissionScope.WORKSPACE, PermissionScope.CHANNEL, PermissionScope.ANY]),
    ("role", "delete", [PermissionScope.WORKSPACE, PermissionScope.CHANNEL, PermissionScope.ANY]),
    ("workspace", "view", [PermissionScope.ANY]),
    ("channel", "view", [PermissionScope.ANY]),
    ("test", "view", [*PermissionScope]),
]


@pytest.fixture(scope="session", autouse=True)
def registry(db_session):
    registry = permission_registry(db_session)

    db_session.execute(delete(Role))
    db_session.execute(delete(Permission))
    db_session.add(
        Role(
            id=EVERYONE_ID,
            name="everyone",
            description=None,
            workspace_id=None,
            priority=0,
        )
    )
    db_session.add_all(
        [
            Permission(resource=resource, action=action, allowed_scopes=allowed_scopes)
            for resource, action, allowed_scopes
            in test_permissions
        ]
    )
    db_session.flush()
    # add first permission to everyone
    everyone_role = db_session.get(Role, EVERYONE_ID)
    perm = db_session.scalar(select(Permission).where(Permission.bit_offset == 0))
    everyone_role.permissions.append(
        RolePermission(permission_id=perm.id, scope=PermissionScope.OWN)
    )
    db_session.commit()

    return registry
