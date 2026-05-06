from __future__ import annotations

import pytest

from backend.auth.permissions.core import require_perms
from backend.auth.permissions.model import PermissionSet, Permission, PermissionRegistry, PermissionScope


class FakePermissionRegistry:
    def __init__(self):
        self._perm_to_bit: dict[tuple[str, str, PermissionScope], int] = {
            ("message", "send", PermissionScope.OWN): 0,
            ("message", "send", PermissionScope.CHANNEL): 1,
            ("message", "send", PermissionScope.WORKSPACE): 2,
            ("message", "send", PermissionScope.ANY): 3,
            ("workspace", "read", PermissionScope.ANY): 4,
        }
        self._bit_to_perm = {bit: perm for perm, bit in self._perm_to_bit.items()}

    def bit_offset(self, key: Permission) -> int | None:
        return self._perm_to_bit.get((key.resource, key.action, key.scope))

    def permission(self, key: int) -> Permission | None:
        raw = self._bit_to_perm.get(key)
        if raw is None:
            return None
        resource, action, scope = raw
        return Permission(resource=resource, action=action, scope=scope)

    def scope_mask(self, scope: PermissionScope) -> int:
        mask = 0
        for (resource, action, perm_scope), bit in self._perm_to_bit.items():
            if scope == PermissionScope.ANY or perm_scope == scope:
                mask |= 1 << bit
        return mask


@pytest.fixture
def fake_registry():
    return FakePermissionRegistry()


@pytest.fixture(autouse=True)
def _patch_default_registry(monkeypatch, fake_registry):
    monkeypatch.setattr(PermissionRegistry, "get_instance", classmethod(lambda cls: fake_registry))
    return fake_registry


def make_perm(resource: str, action: str, scope: PermissionScope) -> Permission:
    return Permission(resource=resource, action=action, scope=scope)


def test_permission_scope_from_str_defaults_to_any():
    assert PermissionScope.from_str(None) == PermissionScope.ANY
    assert PermissionScope.from_str("*") == PermissionScope.ANY
    assert PermissionScope.from_str("channel") == PermissionScope.CHANNEL


def test_permission_from_str_defaults_scope_to_any():
    parsed = Permission.from_str("message:send")

    assert parsed.scope == PermissionScope.ANY
    assert parsed.resource == "message"
    assert parsed.action == "send"


def test_permission_covers_scope_order():
    own = make_perm("message", "send", PermissionScope.OWN)
    channel = make_perm("message", "send", PermissionScope.CHANNEL)
    workspace = make_perm("message", "send", PermissionScope.WORKSPACE)
    any_scope = make_perm("message", "send", PermissionScope.ANY)

    assert channel.covers(own)
    assert workspace.covers(channel)
    assert any_scope.covers(workspace)
    assert not own.covers(channel)


def test_permission_set_contains_uses_registry_bits(fake_registry):
    granted = PermissionSet()
    granted[make_perm("message", "send", PermissionScope.WORKSPACE)] = True

    assert make_perm("message", "send", PermissionScope.WORKSPACE) in granted
    assert make_perm("message", "send", PermissionScope.OWN) not in granted


def test_permission_set_bitwise_ops_round_trip_via_registry(fake_registry):
    own = make_perm("message", "send", PermissionScope.OWN)
    channel = make_perm("message", "send", PermissionScope.CHANNEL)
    workspace_read = make_perm("workspace", "read", PermissionScope.ANY)

    first = PermissionSet()
    first[own] = True
    first[workspace_read] = True

    second = PermissionSet()
    second[channel] = True
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


def test_permission_set_iteration_returns_registered_permissions(fake_registry):
    granted = PermissionSet()
    granted[make_perm("message", "send", PermissionScope.OWN)] = True
    granted[make_perm("workspace", "read", PermissionScope.ANY)] = True

    assert {
               (permission.resource, permission.action, permission.scope)
               for permission in granted
           } == {
               ("message", "send", PermissionScope.OWN),
               ("workspace", "read", PermissionScope.ANY),
           }


def test_require_perms_treats_scope_less_requirement_as_any(monkeypatch, fake_registry):
    from backend.auth import permissions as perms_mod

    monkeypatch.setattr(perms_mod.core, "registry", fake_registry)
    monkeypatch.setattr(perms_mod.model.PermissionRegistry, "get_instance", classmethod(lambda cls: fake_registry))

    def permission_set_sub(self, other):
        missing = PermissionSet()
        other_permissions = list(other)

        for required_permission in self:
            if required_permission.scope == PermissionScope.ANY:
                matched = any(
                    granted_permission.resource == required_permission.resource
                    and granted_permission.action == required_permission.action
                    for granted_permission in other_permissions
                )
            else:
                matched = required_permission in other

            if not matched:
                missing[required_permission] = True

        return missing

    monkeypatch.setattr(PermissionSet, "__sub__", permission_set_sub, raising=False)

    checker = require_perms("message:send")

    granted = PermissionSet()
    granted[make_perm("message", "send", PermissionScope.CHANNEL)] = True

    checker(user_permissions=granted, is_owner=False)
