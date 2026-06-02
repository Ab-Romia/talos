import pytest
from fastapi import APIRouter, Depends

from backend.auth.permissions import ScopedPermission, PermissionSet, require_perms
from backend.auth.permissions.model import PermissionScope, Role, RolePermission
from backend.auth.permissions.service import permission_from_offset, bit_offset


class TestPermissionRegistry:
    def test_get_permission(self, get_perm):
        permission = get_perm("message", "send")
        assert permission is not None
        assert permission.resource == "message"
        assert permission.action == "send"

    def test_method_caches(self, db_session):
        methods = [
            (
                bit_offset,
                (db_session, ScopedPermission(resource="message", action="send", scope=PermissionScope.ANY),),
            ),
            (permission_from_offset, (db_session, PermissionScope.ANY.offset)),
        ]
        for method, method_args in methods:
            method.cache_clear()
            assert method(*method_args) is method(*method_args)

        permission_from_offset.cache_clear()
        test_perm = ScopedPermission(resource="message", action="send", scope=PermissionScope.ANY)
        bit_offset(db_session, test_perm)
        # Shouldn't care about db_session
        assert permission_from_offset(None, PermissionScope.ANY.offset) is test_perm  # noqa

    def test_bit_offset_returns_valid_offset(self, db_session):
        offset = bit_offset(
            db_session,
            ScopedPermission(resource="message", action="send", scope=PermissionScope.ANY)
        )
        assert offset == PermissionScope.ANY.offset

    def test_scope_layout_has_two_non_overlapping_halves(self):
        own_mask = PermissionScope.OWN.mask
        any_mask = PermissionScope.ANY.mask

        assert own_mask != 0
        assert any_mask != 0
        assert own_mask & any_mask == 0

    def test_bit_offset_returns_none_for_nonexistent_permission(self, db_session):
        offset = bit_offset(
            db_session,
            ScopedPermission(resource="nonexistent", action="send", scope=PermissionScope.ANY)
        )
        assert offset is None

    def test_bit_offset_case_sensitive(self, db_session):
        offset = bit_offset(
            db_session,
            ScopedPermission(resource="Message", action="Send", scope=PermissionScope.ANY)
        )
        assert offset is None

    def test_permission_from_offset_returns_all_bits(self, db_session, test_permissions):
        for offset, (resource, action, owner_allowed) in enumerate(test_permissions):
            # ANY bit
            expected_any = ScopedPermission(resource=resource, action=action, scope=PermissionScope.ANY)
            actual_any = permission_from_offset(db_session, offset + PermissionScope.ANY.offset)
            assert actual_any == expected_any

            # OWN bit only if owner_allowed
            actual_own = permission_from_offset(db_session, offset + PermissionScope.OWN.offset)
            if owner_allowed:
                expected_own = ScopedPermission(resource=resource, action=action, scope=PermissionScope.OWN)
                assert actual_own == expected_own
            else:
                assert actual_own is None

    def test_permission_from_offset_returns_none_for_invalid_bit(self, db_session):
        assert permission_from_offset(db_session, 999) is None

    def test_permission_from_offset_negative_offset(self, db_session):
        assert permission_from_offset(db_session, -1) is None


class TestPermissionParsing:
    @pytest.mark.parametrize(
        ("raw_permission", "expected_scope"),
        [
            pytest.param("message:send", PermissionScope.ANY, id="implicit_any"),
            pytest.param("message:send:*", PermissionScope.ANY, id="explicit_any"),
            pytest.param("message:send:any", PermissionScope.ANY, id="named_any"),
            pytest.param("message:send:own", PermissionScope.OWN, id="own"),
        ],
    )
    def test_from_str_parses_scope(self, raw_permission, expected_scope):
        parsed = ScopedPermission.from_str(raw_permission)
        assert parsed.scope == expected_scope
        assert parsed.resource == "message"
        assert parsed.action == "send"


class TestRequirePerms:
    def test_message_send_allowed(self, db_session):
        checker = require_perms("message:send")

        permission = ScopedPermission.from_str("message:send:any")
        perm_set = PermissionSet.from_permissions([permission], db=db_session)

        checker(user_permissions=perm_set, is_owner=False, db=db_session)

    def test_message_send_denied(self, db_session):
        checker = require_perms("message:send")
        from backend.auth.utils.errors import Forbidden

        with pytest.raises(Forbidden):
            checker(user_permissions=PermissionSet(), is_owner=False, db=db_session)

    def test_owner_allows_own_scope(self, db_session):
        checker = require_perms("message:send")
        permission = ScopedPermission.from_str("message:send:own")
        perm_set = PermissionSet.from_permissions([permission], db=db_session)

        checker(user_permissions=perm_set, is_owner=True, db=db_session)

    def test_non_owner_denies_own_scope(self, db_session):
        checker = require_perms("message:send")
        permission = ScopedPermission.from_str("message:send:own")
        perm_set = PermissionSet.from_permissions([permission], db=db_session)

        from backend.auth.utils.errors import Forbidden

        with pytest.raises(Forbidden):
            checker(user_permissions=perm_set, is_owner=False, db=db_session)


class TestEndpoint:
    @pytest.fixture(scope="function")
    def test_endpoint(self, client):
        import uuid

        path_name = f"test_require_perms_endpoint_{uuid.uuid4().hex}"
        path = f"/__/{{workspace_id}}/{path_name}"
        router = APIRouter()

        @router.get(path, dependencies=[Depends(require_perms("message:send"))])
        def endpoint(workspace_id: str):
            return workspace_id

        client.app.include_router(router)
        return path

    def test_valid_workspace(self, db_session, client, test_endpoint, test_workspace, test_user,
                             auth_token, get_perm):
        perm = ScopedPermission(resource="message", action="send", scope=PermissionScope.ANY)
        db_perm = get_perm(perm.resource, perm.action, perm.scope)
        assert db_perm is not None

        role = Role(name="test_role", workspace_id=test_workspace.id, priority=1)
        role.permissions.append(RolePermission(permission_id=db_perm.id, scope=PermissionScope.ANY))
        role.users.append(test_user)
        db_session.add(role)
        db_session.commit()

        response = client.get(
            test_endpoint.format(workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert response.json() == str(test_workspace.id)

    def test_invalid_workspace(self, client, test_endpoint, test_workspace, auth_token):
        response = client.get(
            test_endpoint.format(workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 403
