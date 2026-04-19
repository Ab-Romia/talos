from backend.auth.perms import PermissionSet, Scope, ScopeContext, UserPermission


def perm(resource: str, action: str, scope: Scope, **context) -> UserPermission:
    scope_context = ScopeContext(**context) if context else None
    return UserPermission(
        resource=resource,
        action=action,
        scope=scope,
        scope_context=scope_context,
    )


def test_user_permission_subset_by_scope_order():
    own = perm("message", "send", Scope.OWN)
    channel = perm("message", "send", Scope.CHANNEL)
    workspace = perm("message", "send", Scope.WORKSPACE)
    any_scope = perm("message", "send", Scope.ANY)

    assert own <= channel
    assert channel <= workspace
    assert workspace <= any_scope
    assert not workspace <= channel


def test_user_permission_subset_checks_scope_context():
    required = perm("message", "send", Scope.OWN, workspace_id=1, channel_id=7)
    granted_matching = perm("message", "send", Scope.CHANNEL, workspace_id=1, channel_id=7)
    granted_wrong_channel = perm("message", "send", Scope.CHANNEL, workspace_id=1, channel_id=8)

    assert required <= granted_matching
    assert not required <= granted_wrong_channel


def test_user_permission_context_bound_permission_does_not_cover_global_requirement():
    global_requirement = perm("message", "send", Scope.CHANNEL)
    channel_specific = perm("message", "send", Scope.CHANNEL, workspace_id=1, channel_id=7)

    assert not global_requirement <= channel_specific


def test_permission_set_contains_uses_coverage_rules():
    granted = PermissionSet({perm("message", "send", Scope.WORKSPACE, workspace_id=1)})

    assert perm("message", "send", Scope.OWN, workspace_id=1, channel_id=3) in granted
    assert perm("message", "send", Scope.OWN, workspace_id=2, channel_id=3) not in granted


def test_permission_set_subset_uses_semantic_comparison():
    required = PermissionSet({perm("message", "send", Scope.CHANNEL, workspace_id=1, channel_id=5)})
    granted = PermissionSet({perm("message", "send", Scope.WORKSPACE, workspace_id=1)})

    assert required <= granted


def test_permission_set_add_normalizes_more_specific_permissions():
    own = perm("message", "send", Scope.OWN, workspace_id=1, channel_id=2)
    channel = perm("message", "send", Scope.CHANNEL, workspace_id=1, channel_id=2)

    merged = PermissionSet({own}) + PermissionSet({channel})

    assert own not in merged.permissions
    assert channel in merged.permissions
    assert len(merged.permissions) == 1


def test_permission_set_difference_removes_only_fully_covered_permissions():
    own = perm("message", "send", Scope.OWN, workspace_id=1, channel_id=2)
    any_scope = perm("message", "send", Scope.ANY)
    workspace = perm("message", "send", Scope.WORKSPACE, workspace_id=1)

    all_perms = PermissionSet({any_scope, own})
    remaining = all_perms - PermissionSet({workspace})

    # '*' is not fully removable by subtracting workspace-level coverage.
    assert any_scope in remaining.permissions
    # Own permission is covered by workspace-level permission in same workspace.
    assert own not in remaining.permissions


def test_from_str_defaults_scope_to_any():
    parsed = UserPermission.from_str("message:send")

    assert parsed.scope == Scope.ANY
    assert parsed.resource == "message"
    assert parsed.action == "send"

