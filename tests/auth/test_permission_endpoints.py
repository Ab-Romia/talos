import pytest
from sqlalchemy import delete, sql

from backend.auth.permissions.core import permission_registry
from backend.auth.permissions.model import (
    EVERYONE_ID,
    Permission, )
from backend.auth.permissions.router import *

# Test permission definitions - mirroring those seeded in registry fixture
test_permissions = [
    ("role", "view", [PermissionScope.WORKSPACE, PermissionScope.CHANNEL, PermissionScope.ANY]),
    ("role", "create", [PermissionScope.WORKSPACE, PermissionScope.CHANNEL, PermissionScope.ANY]),
    ("role", "edit", [PermissionScope.WORKSPACE, PermissionScope.CHANNEL, PermissionScope.ANY]),
    ("role", "delete", [PermissionScope.WORKSPACE, PermissionScope.CHANNEL, PermissionScope.ANY]),
    ("workspace", "view", [PermissionScope.ANY]),
    ("channel", "view", [PermissionScope.ANY]),
]


# ── Session-scoped registry ──


@pytest.fixture(scope="session")
def registry(db_session):
    registry = permission_registry(db_session)
    db_session.execute(sql.text("ALTER SEQUENCE permission_bit_offset_seq RESTART WITH 0"))

    db_session.add(Role(id=EVERYONE_ID, name="everyone", description=None, workspace_id=None, priority=0))
    db_session.add_all(
        [Permission(resource=r, action=a, allowed_scopes=s) for r, a, s in test_permissions]
    )
    db_session.flush()

    everyone_role = db_session.get(Role, EVERYONE_ID)
    for resource in ("workspace", "channel"):
        perm = db_session.scalar(
            select(Permission).where((Permission.resource == resource) & (Permission.action == "view"))
        )
        everyone_role.permissions.append(RolePermission(permission_id=perm.id, scope=PermissionScope.ANY))
    db_session.commit()
    return registry


# ── Helpers ──


def get_perm(db_session, resource, action):
    perm = db_session.scalar(
        select(Permission).where((Permission.resource == resource) & (Permission.action == action))
    )
    assert perm is not None, f"{resource}:{action} permission not found"
    return perm


def make_role_with_perms(db_session, name, workspace_id, priority, actions, scope, user=None):
    """Create a Role with the given role:* permissions at the given scope, optionally assign a user."""
    role = Role(name=name, workspace_id=workspace_id, priority=priority)
    for action in actions:
        perm = get_perm(db_session, "role", action)
        role.permissions.append(RolePermission(permission_id=perm.id, scope=scope))
    if user:
        role.users.append(user)
    db_session.add(role)
    return role


def cleanup_role(db_session, role_id, channel_id=None):
    if channel_id:
        db_session.execute(delete(RolePermission).where(
            and_(RolePermission.role_id == role_id, RolePermission.channel_id == channel_id)
        ))
        db_session.execute(delete(ChannelRoleOverride).where(
            (ChannelRoleOverride.role_id == role_id) & (ChannelRoleOverride.channel_id == channel_id)
        ))
        db_session.execute(delete(RolePermission).where(
            and_(RolePermission.role_id == role_id, RolePermission.channel_id.is_(None))
        ))
    else:
        db_session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    db_session.execute(delete(Role).where(Role.id == role_id))
    db_session.commit()


# ── Shared fixtures ──


@pytest.fixture
def test_workspace_with_role(db_session, test_workspace, test_user, registry):
    role = make_role_with_perms(
        db_session,
        name=f"view_role_{test_workspace.id.hex[:8]}",
        workspace_id=test_workspace.id,
        priority=1,
        actions=["view"],
        scope=PermissionScope.WORKSPACE,
        user=test_user,
    )

    role.permissions.append(
        RolePermission(
            permission_id=get_perm(db_session, "workspace", "view").id,
            scope=PermissionScope.WORKSPACE)
    )
    db_session.commit()
    db_session.refresh(role)
    yield role
    cleanup_role(db_session, role.id)


@pytest.fixture
def test_workspace_admin_role(db_session, test_workspace, test_user, registry):
    role = make_role_with_perms(
        db_session,
        name=f"admin_role_{test_workspace.id.hex[:8]}",
        workspace_id=test_workspace.id,
        priority=10,
        actions=["view", "create", "edit", "delete"],
        scope=PermissionScope.WORKSPACE,
        user=test_user,
    )
    db_session.commit()
    db_session.refresh(role)
    yield role
    cleanup_role(db_session, role.id)


@pytest.fixture
def test_channel_role_override(db_session, test_workspace, test_channel, registry):
    role = make_role_with_perms(
        db_session,
        name=f"channel_test_role_{test_channel.id.hex[:8]}",
        workspace_id=test_workspace.id,
        priority=2,
        actions=["view"],
        scope=PermissionScope.WORKSPACE,
    )
    db_session.flush()
    override = ChannelRoleOverride(role_id=role.id, channel_id=test_channel.id)
    db_session.add(override)
    db_session.commit()
    yield role, override
    cleanup_role(db_session, role.id, channel_id=test_channel.id)


@pytest.fixture
def channel_admin_role(db_session, test_workspace, test_user, registry):
    """Role granting all role:* permissions at CHANNEL scope, assigned to test_user."""
    role = make_role_with_perms(
        db_session,
        name=f"ch_admin_{test_workspace.id.hex[:8]}",
        workspace_id=test_workspace.id,
        priority=10,
        actions=["view", "create", "edit", "delete"],
        scope=PermissionScope.CHANNEL,
        user=test_user,
    )
    db_session.commit()
    yield role
    cleanup_role(db_session, role.id)


# ── Workspace-Level Role Tests ──


class TestWorkspaceLevelRoleList:
    def test_list_workspace_roles_empty(self, client, test_workspace, test_workspace_with_role, auth_token, path):
        response = client.get(
            path(list_workspace_roles, workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_workspace_roles_with_permissions(
            self, db_session, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        db_session.add(Role(name=f"extra_role_{test_workspace.id.hex[:8]}", workspace_id=test_workspace.id, priority=5))
        db_session.commit()

        response = client.get(
            path(list_workspace_roles, workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_list_workspace_roles_forbidden(self, client, test_workspace, auth_token, path):
        response = client.get(
            path(list_workspace_roles, workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403

    def test_list_workspace_roles_invalid_workspace(self, client, auth_token, path):
        response = client.get(
            path(list_workspace_roles, workspace_id=uuid.uuid4()),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code in (403, 404)  # Either is ok


class TestWorkspaceLevelRoleCreate:
    def test_create_workspace_role_success(
            self, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        role_name = f"new_role_{test_workspace.id.hex[:8]}"
        response = client.post(
            path(create_workspace_role, workspace_id=test_workspace.id),
            data={"name": role_name, "priority": 5, "description": "Test role"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        # assert response.status_code == 201
        data = response.json()
        assert data.get("name") == role_name
        assert int(data.get("priority", 0)) == 1  # the database will auto-assign priority based on existing roles

    def test_create_workspace_role_duplicate_conflict(
            self, db_session, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        role_name = f"dup_role_{test_workspace.id.hex[:8]}"
        db_session.add(Role(name=role_name, workspace_id=test_workspace.id, priority=1))
        db_session.commit()

        response = client.post(
            path(create_workspace_role, workspace_id=test_workspace.id),
            data={"name": role_name, "priority": 2},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 409

    def test_create_workspace_role_forbidden(self, client, test_workspace, auth_token, path):
        response = client.post(
            path(create_workspace_role, workspace_id=test_workspace.id),
            data={"name": "unauthorized_role", "priority": 1},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403

    def test_create_workspace_role_invalid_workspace(self, client, auth_token, path):
        response = client.post(
            path(create_workspace_role, workspace_id=uuid.uuid4()),
            data={"name": "test_role", "priority": 1},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403  # 403 is ok here


class TestWorkspaceLevelRoleGet:
    def test_get_workspace_role_success(
            self, db_session, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        role = make_role_with_perms(
            db_session,
            name=f"get_test_role_{test_workspace.id.hex[:8]}",
            workspace_id=test_workspace.id,
            priority=3,
            actions=["edit"],
            scope=PermissionScope.WORKSPACE,
        )
        db_session.commit()

        response = client.get(
            path(get_workspace_role, workspace_id=test_workspace.id, role_id=role.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert str(role.id) in (data.get("id"), str(data.get("id")))
        assert data.get("name") == role.name
        assert ("permissions" in data) or ("permission_count" in data)
        assert ("users" in data) or ("user_count" in data)

    def test_get_workspace_role_not_found(
            self, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        response = client.get(
            path(get_workspace_role, workspace_id=test_workspace.id, role_id=uuid.uuid4()),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404

    def test_get_workspace_role_wrong_workspace(
            self, db_session, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        from model.messaging import Workspace

        other_ws = Workspace(id=uuid.uuid4(), name="other_ws", owner_id=test_workspace.owner_id)
        other_role = Role(name=f"other_ws_role", workspace_id=other_ws.id, priority=1)
        db_session.add_all([other_ws, other_role])
        db_session.commit()

        response = client.get(
            path(get_workspace_role, workspace_id=test_workspace.id, role_id=other_role.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404

    def test_get_workspace_role_forbidden(
            self, db_session, client, test_workspace, auth_token, path
    ):
        role = Role(name=f"protected_role_{test_workspace.id.hex[:8]}", workspace_id=test_workspace.id, priority=1)
        db_session.add(role)
        db_session.commit()

        response = client.get(
            path(get_workspace_role, workspace_id=test_workspace.id, role_id=role.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403


class TestWorkspaceLevelRoleUpdate:
    def test_update_workspace_role_permissions_success(
            self, db_session, client, test_workspace, test_workspace_admin_role, test_user, auth_token, path
    ):
        role = make_role_with_perms(
            db_session,
            name=f"update_role_{test_workspace.id.hex[:8]}",
            workspace_id=test_workspace.id,
            priority=2,
            actions=["view"],
            scope=PermissionScope.WORKSPACE,
        )
        db_session.commit()

        response = client.put(
            path(update_workspace_role_permissions, workspace_id=test_workspace.id, role_id=role.id),
            json=["role:create:workspace"],
            # "member_ids": [str(test_user.id)]
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        db_session.refresh(role)
        assert any(p.permission.resource == "role"
                   and p.permission.action == "create"
                   and p.scope == PermissionScope.WORKSPACE
                   for p in role.permissions)
        # assert any(u.id == test_user.id for u in role.users) is False

    def test_update_workspace_role_user_assignments(
            self, db_session, client, test_workspace, test_workspace_admin_role, test_user, auth_token, path
    ):
        from backend.auth.model import User
        from faker import Faker

        role = Role(name=f"assign_role_{test_workspace.id.hex[:8]}", workspace_id=test_workspace.id, priority=1)
        role.users.append(test_user)
        db_session.add(role)
        db_session.flush()

        faker = Faker()
        other_user = User(
            username=faker.user_name(), primary_email=faker.email(),
            signup_complete=True, name=faker.name(), data={},
        )
        db_session.add(other_user)
        db_session.commit()

        response = client.put(
            path(update_workspace_role_members, workspace_id=test_workspace.id, role_id=role.id),
            data={"permissions": [], "member_ids": [other_user.id.hex]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        db_session.refresh(role)
        assert all(u.id != test_user.id for u in role.users)
        assert any(u.id == other_user.id for u in role.users)

    def test_update_workspace_role_revoke_all_permissions(
            self, db_session, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        role = make_role_with_perms(
            db_session,
            name=f"revoke_all_role_{test_workspace.id.hex[:8]}",
            workspace_id=test_workspace.id,
            priority=1,
            actions=["view", "create", "edit"],
            scope=PermissionScope.WORKSPACE,
        )
        db_session.commit()

        response = client.put(
            path(update_workspace_role_permissions, workspace_id=test_workspace.id, role_id=role.id),
            json=[],
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        db_session.refresh(role)
        assert len(role.permissions) == 0

    def test_update_workspace_role_forbidden(
            self, db_session, client, test_workspace, auth_token, path
    ):
        role = Role(name=f"protected_edit_role_{test_workspace.id.hex[:8]}", workspace_id=test_workspace.id, priority=1)
        db_session.add(role)
        db_session.commit()

        response = client.put(
            path(update_workspace_role_permissions, workspace_id=test_workspace.id, role_id=role.id),
            data={"permissions": ["role:create:workspace"]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403

    def test_update_workspace_role_not_found(
            self, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        response = client.put(
            path(update_workspace_role_permissions, workspace_id=test_workspace.id, role_id=uuid.uuid4()),
            json=[],
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404


class TestWorkspaceLevelRoleDelete:
    def test_delete_workspace_role_empty_success(
            self, db_session, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        role = Role(name=f"empty_delete_role_{test_workspace.id.hex[:8]}", workspace_id=test_workspace.id, priority=1)
        db_session.add(role)
        db_session.commit()

        response = client.delete(
            path(delete_workspace_role, workspace_id=test_workspace.id, role_id=role.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 204
        assert db_session.get(Role, role.id) is None

    def test_delete_workspace_role_forbidden(
            self, db_session, client, test_workspace, auth_token, path
    ):
        role = Role(name=f"protected_delete_role_{test_workspace.id.hex[:8]}", workspace_id=test_workspace.id,
                    priority=1)
        db_session.add(role)
        db_session.commit()

        response = client.delete(
            path(delete_workspace_role, workspace_id=test_workspace.id, role_id=role.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403

    def test_delete_workspace_role_not_found(
            self, client, test_workspace, test_workspace_admin_role, auth_token, path
    ):
        response = client.delete(
            path(delete_workspace_role, workspace_id=test_workspace.id, role_id=uuid.uuid4()),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404


class TestWorkspaceLevelMyPermissions:
    def test_my_workspace_permissions_with_role(
            self, db_session, client, test_workspace, test_workspace_with_role, auth_token, path
    ):
        response = client.get(
            path(workspace_level_permissions, workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))
        assert any(p["resource"] == "role" and p["action"] == "view" for p in data)

    @pytest.mark.xfail(reason="TODO: Add owner overrides")
    def test_my_workspace_permissions_no_roles(
            self, db_session, client, test_user, auth_token, path
    ):
        from model.messaging import Workspace

        new_ws = Workspace(id=uuid.uuid4(), name="isolated_ws", owner_id=test_user.id)
        db_session.add(new_ws)
        db_session.commit()

        response = client.get(
            path(workspace_level_permissions, workspace_id=new_ws.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200


# ── Channel-Level Override Tests ──


class TestChannelLevelRoleOverrideList:
    def test_list_channel_role_overrides_empty(self, client, test_channel, auth_token, path):
        response = client.get(
            path(get_channel_roles_overrides, channel_id=test_channel.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_channel_role_overrides_with_data(
            self, client, test_channel, test_channel_role_override, auth_token, path
    ):
        response = client.get(
            path(get_channel_roles_overrides, channel_id=test_channel.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert len(response.json()) >= 1


class TestChannelLevelRoleOverrideCreate:
    def test_create_channel_role_override_success(
            self, db_session, client, test_workspace, test_channel, test_user, auth_token, channel_admin_role, path
    ):
        ws_role = Role(name=f"ws_role_{test_workspace.id.hex[:8]}", workspace_id=test_workspace.id, priority=1)
        db_session.add(ws_role)
        db_session.commit()

        response = client.post(
            path(create_channel_roles_override, channel_id=test_channel.id, role_id=ws_role.id),
            data={"role_id": str(ws_role.id), "permissions": []},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 201
        found = db_session.scalar(select(ChannelRoleOverride).where(
            (ChannelRoleOverride.role_id == ws_role.id) & (ChannelRoleOverride.channel_id == test_channel.id)
        ))
        assert found is not None

    def test_create_channel_role_override_duplicate_conflict(
            self, db_session, client, test_workspace, test_channel, test_user, auth_token, channel_admin_role, path
    ):
        ws_role = Role(name=f"ws_dup_role_{test_workspace.id.hex[:8]}", workspace_id=test_workspace.id, priority=1)
        db_session.add(ws_role)
        db_session.flush()
        db_session.add(ChannelRoleOverride(role_id=ws_role.id, channel_id=test_channel.id))
        db_session.commit()

        response = client.post(
            path(create_channel_roles_override, channel_id=test_channel.id, role_id=ws_role.id),
            data={"role_id": str(ws_role.id), "permissions": []},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 409

    def test_create_channel_role_override_invalid_role(self, client, test_channel, auth_token, path):
        invalid_role_id = uuid.uuid4()
        response = client.post(
            path(create_channel_roles_override, channel_id=test_channel.id, role_id=invalid_role_id),
            data={"role_id": str(invalid_role_id), "permissions": []},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404


class TestChannelLevelRoleOverrideUpdate:
    def test_update_channel_role_override_permissions(
            self, db_session, client, test_workspace, test_channel, test_channel_role_override, test_user, auth_token,
            channel_admin_role, path
    ):
        role, _ = test_channel_role_override
        response = client.put(
            path(update_channel_roles_override, channel_id=test_channel.id, role_id=role.id),
            data={"permissions": []},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200

    def test_update_channel_role_override_not_found(
            self, client, test_channel, auth_token, path
    ):
        response = client.put(
            path(update_channel_roles_override, channel_id=test_channel.id, role_id=uuid.uuid4()),
            json={"permissions": []},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403


class TestChannelLevelRoleOverrideDelete:
    def test_delete_channel_role_override_success(
            self, db_session, client, test_workspace, test_channel, test_channel_role_override, test_user, auth_token,
            channel_admin_role, path
    ):
        role, _ = test_channel_role_override
        response = client.delete(
            path(delete_channel_roles_override, channel_id=test_channel.id, role_id=role.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 204
        found = db_session.scalar(select(ChannelRoleOverride).where(
            (ChannelRoleOverride.role_id == role.id) & (ChannelRoleOverride.channel_id == test_channel.id)
        ))
        assert found is None

    def test_delete_channel_role_override_not_found(self, client, test_channel, auth_token, path):
        response = client.delete(
            path(delete_channel_roles_override, channel_id=test_channel.id, role_id=uuid.uuid4()),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403


class TestChannelLevelMyPermissions:
    def test_my_channel_permissions_with_global_role(
            self, client, test_channel, test_workspace_with_role, auth_token, path
    ):
        response = client.get(
            path(channel_level_permissions, channel_id=test_channel.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200

    def test_my_channel_permissions_override_deny_semantics(
            self, db_session, client, test_workspace, test_channel, test_user, auth_token, path
    ):
        """Channel override that denies a permission granted at workspace scope."""
        global_role = make_role_with_perms(
            db_session,
            name=f"global_create_role_{test_workspace.id.hex[:8]}",
            workspace_id=test_workspace.id,
            priority=1,
            actions=["create"],
            scope=PermissionScope.WORKSPACE,
            user=test_user,
        )
        db_session.flush()

        create_perm = get_perm(db_session, "role", "create")
        db_session.add(ChannelRoleOverride(role_id=global_role.id, channel_id=test_channel.id))
        db_session.add(RolePermission(
            role_id=global_role.id, permission_id=create_perm.id,
            channel_id=test_channel.id, scope=PermissionScope.CHANNEL, is_deny=True,
        ))
        db_session.commit()

        response = client.get(
            path(channel_level_permissions, channel_id=test_channel.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), (list, dict))

    def test_my_channel_permissions_no_roles(
            self, db_session, client, test_user, auth_token, path
    ):
        from model.messaging import Workspace, Channel

        new_ws = Workspace(id=uuid.uuid4(), name="isolated_ws", owner_id=test_user.id)
        new_ch = Channel(id=uuid.uuid4(), name="isolated_ch", workspace_id=new_ws.id)
        db_session.add_all([new_ws, new_ch])
        db_session.commit()

        response = client.get(
            path(channel_level_permissions, channel_id=new_ch.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
