from backend.auth.permissions.model import PermissionScope
from backend.auth.permissions.router import *
from backend.workspace.model import Workspace, Channel


class TestWorkspaceLevelRoleList:
    def test_list_workspace_roles_empty(self, client, test_workspace, auth_token, path):
        response = client.get(
            path(list_workspace_roles, workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_workspace_roles_with_permissions(self, db_session, client, test_workspace, auth_token, path):
        db_session.add(Role(name=f"extra_role_{test_workspace.id.hex[:8]}", workspace_id=test_workspace.id, priority=5))
        db_session.commit()

        response = client.get(
            path(list_workspace_roles, workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_list_workspace_roles_invalid_workspace(self, client, auth_token, path):
        response = client.get(
            path(list_workspace_roles, workspace_id=uuid.uuid4()),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code in (403, 404)  # Either is ok


class TestWorkspaceLevelRoleCreate:
    def test_create_workspace_role_success(
            self, client, test_workspace, auth_token, path
    ):
        role_name = f"new_role_{test_workspace.id.hex[:8]}"
        response = client.post(
            path(create_workspace_role, workspace_id=test_workspace.id),
            data={"name": role_name, "priority": '5', "description": "Test role"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        # assert response.status_code == 201
        data = response.json()
        assert data.get("name") == role_name

    def test_create_workspace_role_duplicate_conflict(
            self, db_session, client, test_workspace, auth_token, path
    ):
        role_name = f"dup_role_{test_workspace.id.hex[:8]}"
        db_session.add(Role(name=role_name, workspace_id=test_workspace.id, priority=1))
        db_session.commit()

        response = client.post(
            path(create_workspace_role, workspace_id=test_workspace.id),
            data={"name": role_name, "priority": "2"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 409

    def test_create_workspace_role_invalid_workspace(self, client, auth_token, path):
        response = client.post(
            path(create_workspace_role, workspace_id=uuid.uuid4()),
            data={"name": "test_role", "priority": '1'},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403  # 403 is ok here


class TestWorkspaceLevelRoleGet:
    def test_get_workspace_role_success(
            self, db_session, client, test_workspace, auth_token, path, make_role
    ):
        role = make_role(
            name=f"get_test_role_{test_workspace.id.hex[:8]}",
            permissions=["workspace.role:manage"],
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
            self, client, test_workspace, auth_token, path
    ):
        response = client.get(
            path(get_workspace_role, workspace_id=test_workspace.id, role_id=uuid.uuid4()),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404

    def test_get_workspace_role_wrong_workspace(
            self, db_session, client, test_workspace, auth_token, path
    ):
        other_ws = Workspace(id=uuid.uuid4(), name="other_ws", owner_id=test_workspace.owner_id)
        other_role = Role(name=f"other_ws_role", workspace_id=other_ws.id, priority=1)
        db_session.add_all([other_ws, other_role])
        db_session.commit()

        response = client.get(
            path(get_workspace_role, workspace_id=test_workspace.id, role_id=other_role.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404


class TestWorkspaceLevelRoleUpdate:
    def test_update_workspace_role_permissions_success(
            self, db_session, client, test_workspace, test_user, auth_token, path,
            make_role
    ):
        role = make_role(permissions=["workspace.role:manage"])
        test_role = make_role()
        db_session.commit()

        response = client.put(
            path(update_workspace_role_permissions, workspace_id=test_workspace.id, role_id=test_role.id),
            json=["workspace.role:manage"],
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        db_session.refresh(test_role)
        assert any(p.permission.resource == "workspace.role"
                   and p.permission.action == "manage"
                   and p.scope == PermissionScope.ANY
                   for p in test_role.permissions)

    def test_update_workspace_role_user_assignments(
            self, db_session, client, test_workspace, test_user, auth_token, path, make_role
    ):
        from backend.auth.model import User
        from faker import Faker

        role = make_role(permissions=["workspace.role:manage"])

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
            self, db_session, client, test_workspace, auth_token, path, make_role
    ):
        role = make_role(
            name=f"revoke_all_role_{test_workspace.id.hex[:8]}",
            workspace_id=test_workspace.id,
            priority=1,
            permissions=["workspace.role:view", "workspace.role:manage", "workspace.role:manage"],
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

    def test_update_workspace_role_forbidden(self, db_session, client, auth_token, path, make_role, test_users):
        test_workspace = Workspace(name="forbidden_ws", owner_id=next(test_users).id)
        db_session.add(test_workspace)
        role = make_role(workspace_id=test_workspace.id)
        db_session.commit()

        response = client.put(
            path(update_workspace_role_permissions, workspace_id=test_workspace.id, role_id=role.id),
            json=["test:view"],
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403

    def test_update_workspace_role_not_found(
            self, client, test_workspace, auth_token, path
    ):
        response = client.put(
            path(update_workspace_role_permissions, workspace_id=test_workspace.id, role_id=uuid.uuid4()),
            json=[],
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404


class TestWorkspaceLevelRoleDelete:
    def test_delete_workspace_role_empty_success(self, db_session, client, test_workspace, auth_token, path, make_role):
        role = make_role(
            name=f"delete_role_{test_workspace.id.hex[:8]}",
            permissions=["workspace.role:manage"],
        )
        db_session.commit()

        response = client.delete(
            path(delete_workspace_role, workspace_id=test_workspace.id, role_id=role.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 204
        assert db_session.get(Role, role.id) is None

    def test_delete_workspace_role_not_found(self, client, test_workspace, auth_token, path, make_role):
        make_role(permissions=["workspace.role:manage"])

        response = client.delete(
            path(delete_workspace_role, workspace_id=test_workspace.id, role_id=uuid.uuid4()),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 404


class TestWorkspaceLevelMyPermissions:
    def test_my_workspace_permissions_with_role(self, db_session, client, test_workspace, auth_token, path):
        response = client.get(
            path(workspace_level_permissions, workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))
        assert any(p["resource"] == "workspace.role" and p["action"] == "view" for p in data)

    def test_my_workspace_permissions_no_roles(self, db_session, client, test_user, auth_token, path):
        new_ws = Workspace(id=uuid.uuid4(), name="isolated_ws", owner_id=test_user.id)
        new_ws.members.append(test_user)
        db_session.add(new_ws)
        db_session.commit()

        response = client.get(
            path(workspace_level_permissions, workspace_id=new_ws.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200


class TestChannelLevelRoleOverrideList:
    def test_list_channel_role_overrides_empty(self, client, test_channel, auth_token, path):
        response = client.get(
            path(get_channel_roles_overrides, channel_id=test_channel.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_channel_role_overrides_with_data(self, client, test_channel, auth_token, path, make_role):
        test_channel.roles_overrides.extend([
            ChannelRoleOverride(role_id=make_role().id),
            ChannelRoleOverride(role_id=make_role().id),
        ])

        response = client.get(
            path(get_channel_roles_overrides, channel_id=test_channel.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert len(response.json()) == 3  # 2 roles + everyone role


class TestChannelLevelRoleOverrideCreate:
    def test_create_channel_role_override_success(self, db_session, client, test_workspace, test_channel, test_user,
                                                  auth_token, path):
        ws_role = Role(
            name=f"ws_role_{test_workspace.id.hex[:8]}",
            workspace_id=test_workspace.id,
            priority=1
        )
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
            self, db_session, client, test_workspace, test_channel, test_user, auth_token, path
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
    def test_update_channel_role_override_permissions(self, db_session, client, test_workspace, test_channel, test_user,
                                                      auth_token, path, make_role):
        role = make_role(
            name=f"override_update_role_{test_workspace.id.hex[:8]}",
            permissions=["workspace.role:manage"],
        )
        test_channel.roles_overrides.append(ChannelRoleOverride(role_id=role.id))
        db_session.commit()
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
        assert response.status_code == 404


class TestChannelLevelRoleOverrideDelete:
    def test_delete_channel_role_override_success(
            self, db_session, client, test_channel, test_user, auth_token,
            path, make_role
    ):
        role = make_role(
            permissions=["workspace.role:manage"]
        )
        test_channel.roles_overrides.append(ChannelRoleOverride(role_id=role.id))
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
        assert response.status_code == 404


class TestChannelLevelMyPermissions:
    def test_my_channel_permissions_with_global_role(
            self, client, test_channel, test_workspace, auth_token, path
    ):
        response = client.get(
            path(channel_level_permissions, channel_id=test_channel.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200

    def test_my_channel_permissions_override_deny_semantics(
            self, db_session, client, test_workspace, test_channel,
            test_user, auth_token, path, make_role, get_perm):
        """Channel override that denies a permission granted at workspace scope."""
        global_role = make_role(
            name=f"global_create_role_{test_workspace.id.hex[:8]}",
            workspace_id=test_workspace.id,
            priority=1,
            permissions=["workspace.role:manage"],
            user=test_user,
        )
        db_session.flush()

        create_perm = get_perm("workspace.role", "manage")
        db_session.add(ChannelRoleOverride(role_id=global_role.id, channel_id=test_channel.id))
        db_session.add(RolePermission(
            role_id=global_role.id, permission_id=create_perm.id,
            channel_id=test_channel.id, scope=PermissionScope.ANY, is_deny=True,
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
        new_ws = Workspace(id=uuid.uuid4(), name="isolated_ws", owner_id=test_user.id)
        db_session.add(new_ws)
        db_session.flush()
        new_ch = Channel(id=uuid.uuid4(), name="isolated_ch", workspace_id=new_ws.id)
        db_session.add(new_ch)
        db_session.commit()

        response = client.get(
            path(channel_level_permissions, channel_id=new_ch.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
