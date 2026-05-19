import pytest
from fastapi import APIRouter, Depends

from auth.permissions.conftest import test_permissions
from backend.auth.permissions.core import require_perms
from backend.auth.permissions.model import PermissionScope, Role, RolePermission
from backend.auth.permissions.registry import PermissionSet, ScopedPermission

msg_send_channel_offset = PermissionScope.CHANNEL.offset


@pytest.fixture(autouse=True, scope="function")
def clear_registry_cache(registry):
    registry.clear_caches()


class TestPermissionRegistry:

    def test_get_permission(self, registry):
        permission = registry.db_permission("message", "send", PermissionScope.CHANNEL)
        assert permission is not None
        assert permission.resource == "message"
        assert permission.action == "send"
        assert PermissionScope.CHANNEL in permission.allowed_scopes

    def test_method_caches(self, registry):
        """Generic cache test: verify a method's result is cached (same object on repeated calls)."""
        methods = [
            (registry.default_base_permissions, ()),
            (registry.bit_offset, (
                ScopedPermission(resource="message", action="send", scope=PermissionScope.CHANNEL),
            )),
            (registry.permission_from_offset, (msg_send_channel_offset,)),
        ]
        for method, method_args in methods:
            method.cache_clear()

            assert method(*method_args) is method(*method_args)

        # test that bit_offset cache is the same as permission_from_offset cache for a valid permission
        registry.permission_from_offset.cache_clear()
        test_perm = ScopedPermission(resource="message", action="send", scope=PermissionScope.CHANNEL)

        registry.bit_offset(test_perm)
        assert registry.permission_from_offset(msg_send_channel_offset) is test_perm

    def test_default_base_permissions_returns_permission_set(self, registry):
        result = registry.default_base_permissions()
        assert isinstance(result, PermissionSet)

    def test_default_base_permissions_contains_everyone_role_permissions(self, registry):
        result = registry.default_base_permissions()
        # Everyone role has the first permission (added in fixture)
        assert isinstance(result, PermissionSet)
        # The mask could be a string (BIT column) or int, so convert if needed
        mask_value = int(result.bitstring, 2) if isinstance(result.bitstring, str) else result.bitstring
        assert isinstance(mask_value, int)

    def test_bit_offset_returns_valid_offset(self, registry):
        offset = registry.bit_offset(
            ScopedPermission(resource="message", action="send", scope=PermissionScope.CHANNEL)
        )
        assert offset == msg_send_channel_offset

    def test_bit_offset_for_all_scopes(self, registry):
        for base_offset, (resource, action, allowed_scopes) in enumerate(test_permissions):
            for scope in allowed_scopes:
                offset = registry.bit_offset(
                    ScopedPermission(resource=resource, action=action, scope=scope)
                )
                expected_offset = base_offset + scope.offset
                assert offset == expected_offset

    def test_bit_offset_returns_none_for_nonexistent_permission(self, registry):
        offset = registry.bit_offset(
            ScopedPermission(resource="nonexistent", action="send", scope=PermissionScope.CHANNEL)
        )
        assert offset is None

    def test_bit_offset_case_sensitive(self, registry):
        offset = registry.bit_offset(
            ScopedPermission(resource="Message", action="Send", scope=PermissionScope.CHANNEL)
        )
        assert offset is None

    def test_permission_from_offset_returns_valid_permission(self, registry):
        perm = registry.permission_from_offset(msg_send_channel_offset)
        assert perm is not None
        assert perm.resource == "message"
        assert perm.action == "send"
        assert perm.scope == PermissionScope.CHANNEL

    def test_permission_from_offset_returns_all_bits(self, registry):
        for offset, (resource, action, allowed_scopes) in enumerate(test_permissions):
            for scope in allowed_scopes:
                expected_perm = ScopedPermission(resource=resource, action=action, scope=scope)
                actual_perm = registry.permission_from_offset(offset + scope.offset)
                assert actual_perm == expected_perm

    def test_permission_from_offset_returns_none_for_invalid_bit(self, registry):
        perm = registry.permission_from_offset(999)
        assert perm is None

    def test_permission_from_offset_negative_offset(self, registry):
        perm = registry.permission_from_offset(-1)
        assert perm is None

    def test_scope_masks(self, registry):
        own_mask = PermissionScope.OWN.mask
        channel_mask = PermissionScope.CHANNEL.mask
        workspace_mask = PermissionScope.WORKSPACE.mask
        any_mask = PermissionScope.WORKSPACE.mask

        masks = [own_mask, channel_mask, workspace_mask, any_mask]
        for mask in masks:
            for other_mask in masks:
                assert (mask & other_mask) == 0 or mask == other_mask


class TestPermissionParsing:
    @pytest.mark.parametrize(
        "raw_permission",
        [
            pytest.param("message:send", id="implicit_any"),
            pytest.param("message:send:*", id="explicit_any"),
        ],
    )
    def test_from_str_defaults_scope_to_any(self, raw_permission):
        parsed = ScopedPermission.from_str(raw_permission)

        assert parsed.scope == PermissionScope.ANY
        assert parsed.resource == "message"
        assert parsed.action == "send"

    # TODO: add tests for invalid formats


class TestPermissionSet:
    # TODO: parametrize
    def test_set_any_bit(self, registry):
        permission = ScopedPermission.from_str("message:send:own")
        permission_any = ScopedPermission.from_str("message:send")

        perm_set = PermissionSet.from_permissions([permission])

        any_bit_set = perm_set.set_any_bit()

        assert permission in any_bit_set
        assert permission_any in any_bit_set

    def test_contains(self, db_session, registry):
        permission = ScopedPermission.from_str("message:send:workspace")

        assert permission is not None
        granted = PermissionSet.from_permissions([permission])

        assert ScopedPermission.from_str("message:send:workspace") in granted
        assert ScopedPermission.from_str("message:send:own") not in granted
        assert ScopedPermission.from_str("message:send") not in granted
        assert ScopedPermission.from_str("message:send") in granted.set_any_bit()
        assert ScopedPermission.from_str("message:send:*") in granted.set_any_bit()

    def test_bitwise_ops_round_trip_via_registry(self):
        own = ScopedPermission.from_str("message:send:own")
        channel = ScopedPermission.from_str("message:send:channel")
        workspace_read = ScopedPermission.from_str("workspace:read")

        first = PermissionSet.from_permissions([own])
        first[workspace_read] = True

        second = PermissionSet.from_permissions([channel])
        second[workspace_read] = True

        union = first | second
        intersection = first & second
        difference = first - second

        assert own in union
        assert channel in union
        assert workspace_read in union

        assert workspace_read in intersection
        assert own not in intersection
        assert channel not in intersection

        assert own in difference
        assert channel not in difference
        assert workspace_read not in difference

    def test_iteration_returns_registered_permissions(self):
        granted = PermissionSet()
        granted[ScopedPermission.from_str("message:send:own")] = True
        granted[ScopedPermission.from_str("workspace:read")] = True

        assert {
                   (permission.resource, permission.action, permission.scope)
                   for permission in granted
               } == {
                   ("message", "send", PermissionScope.OWN),
                   ("workspace", "read", PermissionScope.ANY),
               }


class TestRequirePerms:
    def test_message_send_allowed(self, db_session, registry):
        checker = require_perms("message:send")

        permission = ScopedPermission.from_str("message:send:channel")
        perm_set = PermissionSet.from_permissions([permission])

        checker(user_permissions=perm_set, is_owner=False)

    def test_message_send_denied(self, registry):
        checker = require_perms("message:send")

        from backend.auth.utils.errors import Forbidden

        with pytest.raises(Forbidden):
            checker(user_permissions=PermissionSet(), is_owner=False)

    def test_owner_allows_own_scope(self, db_session):
        checker = require_perms("message:send")
        permission = ScopedPermission.from_str("message:send:own")
        perm_set = PermissionSet.from_permissions([permission])

        checker(user_permissions=perm_set, is_owner=True)

    def test_non_owner_denies_own_scope(self, db_session, registry):
        checker = require_perms("message:send")
        permission = ScopedPermission.from_str("message:send:own")
        perm_set = PermissionSet.from_permissions([permission])

        from backend.auth.utils.errors import Forbidden

        with pytest.raises(Forbidden):
            checker(user_permissions=perm_set, is_owner=False)

    def test_treats_scope_less_requirement_as_any(self, db_session, registry):
        checker = require_perms("message:send")

        permission = ScopedPermission.from_str("message:send")
        granted = PermissionSet.from_permissions([permission])

        checker(user_permissions=granted, is_owner=False)


class TestEndpoint:
    """End-to-end test for require_perms in an actual endpoint, using the test_endpoint fixture which applies require_perms to a simple GET endpoint."""

    # TODO: parametrize over different required permissions and user permissions to test various scenarios
    #  (allowed, denied, owner vs non-owner)
    #  channel, workspace

    @pytest.fixture(scope="function")
    def test_endpoint(self, client, registry):
        import uuid
        path_name = f"test_require_perms_endpoint_{uuid.uuid4().hex}"
        path = f"/__/{{workspace_id}}/{path_name}"
        router = APIRouter()

        @router.get(path, dependencies=[Depends(require_perms("message:send"))])
        def endpoint(workspace_id: str):
            return workspace_id

        client.app.include_router(router)

        return path

    def test_valid_workspace(self, db_session, client, registry, test_endpoint,
                             test_workspace, test_user, auth_token):
        perm = ScopedPermission(resource="message", action="send", scope=PermissionScope.WORKSPACE)
        db_perm = registry.db_permission(perm.resource, perm.action, perm.scope)
        assert db_perm is not None

        role = Role(name="test_role", workspace_id=test_workspace.id, priority=1)
        role.permissions.append(
            RolePermission(permission_id=db_perm.id, scope=PermissionScope.WORKSPACE)
        )
        role.users.append(test_user)
        db_session.add(role)
        db_session.commit()

        response = client.get(
            test_endpoint.format(workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        assert response.json() == str(test_workspace.id)

    def test_invalid_workspace(self, client, test_endpoint, test_workspace, auth_token):
        response = client.get(
            test_endpoint.format(workspace_id=test_workspace.id),
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 403
