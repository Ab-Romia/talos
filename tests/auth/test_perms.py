import pytest
from fastapi import APIRouter, Depends
from sqlalchemy import delete, select

from backend.auth.permissions.core import permission_registry, require_perms
from backend.auth.permissions.model import (
    EVERYONE_ID,
    Permission,
    PermissionRegistry,
    PermissionScope,
    PermissionSet,
    Role, BITSTRING_LENGTH,
)

# TODO: define stable ordering of permissions

test_permissions = [
    ("message", "send", PermissionScope.OWN),
    ("message", "send", PermissionScope.CHANNEL),
    ("message", "send", PermissionScope.WORKSPACE),
    ("message", "send", PermissionScope.ANY),
    ("workspace", "read", PermissionScope.ANY)
]


@pytest.fixture(autouse=True, scope="function")
def clear_registry_cache(registry):
    registry.clear_caches()


@pytest.fixture(scope="session")
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
            Permission(resource=resource, action=action, scope=scope, bit_offset=i)
            for i, (resource, action, scope)
            in enumerate(test_permissions)
        ]
    )
    db_session.flush()
    # add first permission to everyone
    everyone_role = db_session.get(Role, EVERYONE_ID)
    everyone_role.permissions.append(
        db_session.scalars(select(Permission))
        .first()
    )
    db_session.commit()

    return registry


class TestPermissionRegistry:

    def test_get_permission(self, registry):
        permission = registry.get_permission("message", "send", PermissionScope.CHANNEL)
        assert permission is not None
        assert permission.resource == "message"
        assert permission.action == "send"
        assert permission.scope == PermissionScope.CHANNEL

    def test_method_caches(self, registry):
        """Generic cache test: verify a method's result is cached (same object on repeated calls)."""
        methods = [
            ("default_base_permissions", ()),
            ("bit_offset", ("message", "send", PermissionScope.CHANNEL)),
            ("permission_from_offset", (1,)),
            ("scope_mask", (PermissionScope.CHANNEL,)),
        ]
        for method_name, method_args in methods:
            method = getattr(registry, method_name)
            method.cache_clear()

            assert method(*method_args) is method(*method_args)

    def test_default_base_permissions_returns_permission_set(self, registry):
        result = registry.default_base_permissions()
        assert isinstance(result, PermissionSet)

    def test_default_base_permissions_contains_everyone_role_permissions(self, registry):
        result = registry.default_base_permissions()
        # Everyone role has the first permission (added in fixture)
        assert isinstance(result, PermissionSet)
        # The mask could be a string (BIT column) or int, so convert if needed
        mask_value = int(result.mask, 2) if isinstance(result.mask, str) else result.mask
        assert isinstance(mask_value, int)

    def test_bit_offset_returns_valid_offset(self, registry):
        offset = registry.bit_offset("message", "send", PermissionScope.CHANNEL)
        assert offset == 1

    def test_bit_offset_for_all_scopes(self, registry):
        for i, (resource, action, scope) in enumerate(test_permissions):
            offset = registry.bit_offset(resource, action, scope)
            assert offset == i

    def test_bit_offset_returns_none_for_nonexistent_permission(self, registry):
        offset = registry.bit_offset("nonexistent", "action", PermissionScope.ANY)
        assert offset is None

    def test_bit_offset_case_sensitive(self, registry):
        offset = registry.bit_offset("MESSAGE", "send", PermissionScope.CHANNEL)
        assert offset is None

    def test_permission_from_offset_returns_valid_permission(self, registry):
        perm = registry.permission_from_offset(1)
        assert perm is not None
        assert perm.resource == "message"
        assert perm.action == "send"
        assert perm.scope == PermissionScope.CHANNEL

    def test_permission_from_offset_returns_all_bits(self, registry):
        for i, (resource, action, scope) in enumerate(test_permissions):
            perm = registry.permission_from_offset(i)
            assert perm is not None
            assert perm.resource == resource
            assert perm.action == action
            assert perm.scope == scope

    def test_permission_from_offset_returns_none_for_invalid_bit(self, registry):
        perm = registry.permission_from_offset(999)
        assert perm is None

    def test_permission_from_offset_negative_offset(self, registry):
        perm = registry.permission_from_offset(-1)
        assert perm is None

    def test_scope_mask_own_scope(self, registry):
        mask = registry.scope_mask(PermissionScope.OWN)
        assert mask == 0b1

    def test_scope_mask_channel_scope(self, registry):
        mask = registry.scope_mask(PermissionScope.CHANNEL)
        assert mask == 0b10

    def test_scope_mask_workspace_scope(self, registry):
        mask = registry.scope_mask(PermissionScope.WORKSPACE)
        assert mask == 0b100

    def test_scope_mask_any_scope(self, registry):
        mask = registry.scope_mask(PermissionScope.ANY)
        # Should include all bits: OWN (0), CHANNEL (1), WORKSPACE (2), ANY (3), read (4)
        assert mask == 0b11111

    def test_scope_mask_is_integer(self, registry):
        mask = registry.scope_mask(PermissionScope.CHANNEL)
        assert isinstance(mask, int)


class TestPermissionParsing:
    @pytest.mark.parametrize(
        "raw_permission",
        [
            pytest.param("message:send", id="implicit_any"),
            pytest.param("message:send:*", id="explicit_any"),
        ],
    )
    def test_from_str_defaults_scope_to_any(self, raw_permission):
        parsed = Permission.from_str(raw_permission)

        assert parsed.scope == PermissionScope.ANY
        assert parsed.resource == "message"
        assert parsed.action == "send"

    # TODO: add tests for invalid formats


class TestPermissionSet:
    @pytest.mark.parametrize(
        "permission_source",
        [
            pytest.param("local", id="local_permission"),
            pytest.param("registry", id="registry_permission"),
        ],
    )
    def test_contains(self, db_session, registry: PermissionRegistry, permission_source):
        permissions = [
            Permission.from_str("message:send:workspace"),
            registry.get_permission("message", "send", PermissionScope.WORKSPACE),
            db_session.scalar(
                select(Permission)
                .where(Permission.resource == "message",
                       Permission.action == "send",
                       Permission.scope == PermissionScope.WORKSPACE)
            )
        ]

        for permission in permissions:
            assert permission is not None
            granted = PermissionSet.from_permission_list([permission])

            assert Permission.from_str("message:send:workspace") in granted
            assert Permission.from_str("message:send") not in granted
            assert Permission.from_str("message:send") in granted.collapse_scope()
            assert Permission.from_str("message:send:*") in granted.collapse_scope()

    def test_bitwise_ops_round_trip_via_registry(self):
        own = Permission.from_str("message:send:own")
        channel = Permission.from_str("message:send:channel")
        workspace_read = Permission.from_str("workspace:read")

        first = PermissionSet.from_permission_list([own])
        first[workspace_read] = True

        second = PermissionSet.from_permission_list([channel])
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
        granted[Permission.from_str("message:send:own")] = True
        granted[Permission.from_str("workspace:read")] = True

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

        permission = Permission.from_str("message:send:channel")
        perm_set = PermissionSet.from_permission_list([permission])

        checker(user_permissions=perm_set, is_owner=False)

    def test_message_send_denied(self, registry):
        checker = require_perms("message:send")

        from backend.auth.utils.errors import Forbidden

        with pytest.raises(Forbidden):
            checker(user_permissions=PermissionSet(), is_owner=False)

    def test_owner_allows_own_scope(self, db_session):
        checker = require_perms("message:send")
        permission = Permission.from_str("message:send:own")
        perm_set = PermissionSet.from_permission_list([permission])

        checker(user_permissions=perm_set, is_owner=True)

    def test_non_owner_denies_own_scope(self, db_session, registry):
        checker = require_perms("message:send")
        permission = Permission.from_str("message:send:own")
        perm_set = PermissionSet.from_permission_list([permission])

        from backend.auth.utils.errors import Forbidden

        with pytest.raises(Forbidden):
            checker(user_permissions=perm_set, is_owner=False)

    def test_treats_scope_less_requirement_as_any(self, db_session, registry):
        checker = require_perms("message:send")

        permission = Permission.from_str("message:send")
        granted = PermissionSet.from_permission_list([permission])

        checker(user_permissions=granted, is_owner=False)


class TestEndpoint:
    """End-to-end test for require_perms in an actual endpoint, using the test_endpoint fixture which applies require_perms to a simple GET endpoint."""

    # TODO: parametrize over different required permissions and user permissions to test various scenarios
    #  (allowed, denied, owner vs non-owner)
    #  channel, workspace

    @pytest.fixture(scope="class")
    def test_endpoint(self, client):
        path = "/__/{workspace_id}/test_require_perms_endpoint"
        router = APIRouter()

        @router.get(path,
                    dependencies=[Depends(require_perms("message:send"))])
        def endpoint(workspace_id: str):
            return workspace_id

        client.app.include_router(router)

        return path

    def test_valid_workspace(self, db_session, client, registry, test_endpoint,
                             test_workspace, test_user, auth_token):
        # Grant the user the required permission in the workspace
        permission = registry.get_permission("message", "send", PermissionScope.WORKSPACE)

        # TODO: this temporary until i add automatic mask generation
        mask = (["0"] * BITSTRING_LENGTH)
        mask[registry.bit_offset("message", "send", PermissionScope.WORKSPACE)] = "1"

        role = Role(name="test_role", workspace_id=test_workspace.id, priority=1,
                    # TODO:
                    allow_mask="".join(mask))
        role.permissions.append(permission)
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
