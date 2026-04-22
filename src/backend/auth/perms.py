import uuid
from typing import Annotated, Self

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select, or_

from backend.auth.utils import errors
from backend.auth.utils.session import SessionDep
from model import DatabaseDep
from model.identity import Permission, Role

PERMISSIONS = {
    "workspace": {
        "actions": [
            "create",
            "read",
            "update",
            "delete"
        ],
        "scope": ["*", "own"]
    },
    "audit_log": {
        "actions": ["read"],
        "scopes": ["workspace"]
    },
    "member": {
        "actions": [
            "invite"
            "kick",
            "ban",
            "change_nickname",
            "manage_nickname",
            "moderate",
        ],
        "scopes": ["workspace"]
    },
    "channel": {
        "actions": ["create", "read", "update", "delete"],
        "scopes": ["own", "channel"]
    },
    "mention": {
        "actions": ["*", "here", "roles", "members"],
        "scopes": ["channel"]

    },
    "message": {
        "actions": [
            "send",
            "manage",
            "embed_links",
            "attach_files",
            "voice",
            "poll",
            "pin"
        ],
        "scopes": ["own", "channel"]
    },
    "permission": {
        "actions": ["edit", "grant", "revoke"],
        "scopes": ["workspace"]
    },
    "meeting": {
        "actions": ["create", "join", "manage", "end",
                    "speak", "priority_speak", "request_to_speak",
                    "stream",
                    ],
        "scopes": ["workspace", "channel"],
        "subresources": {
            "member": {
                "actions": ["mute", "deafen", "move"],
                "scopes": ["workspace", "channel"]
            },
        }
    },
    "ai": {
        "actions": ["use", "manage"],
        "scopes": ["workspace", "channel"]
    },
    "commands": {
        "actions": ["use", "manage"],
        "scopes": ["workspace", "channel"]
    },
}


# TODO: plan:::
#  - perms dict -> binary bitmask
#    - scopes
#    - sub-resources
#  - set operations (union, intersection, difference)
#  - overrides (w/ allow/deny)
#  - default roles (admin, moderator, everyone)

class ScopeContext(BaseModel):
    workspace_id: uuid.UUID = None
    channel_id: uuid.UUID = None


class PermissionSet:
    def __init__(self, permissions: set[Permission]):
        self.permissions = self._normalize(permissions)

    @classmethod
    def _normalize(cls, permissions: set[Permission]) -> set[Permission]:
        """
        Remove redundant permissions from the set, keeping only the most general ones.
        E.g. "messages:edit:*" covers "messages:edit:own", so the latter can be removed.
        """
        # TODO: priority, denies, overrides

        # Asserts that permissions are sorted (most general first)
        # Most likely sorted from the database query
        sorted_permissions = sorted(
            permissions,
            key=lambda p: (-p.scope.value, p.priority, p.is_deny, p.id)
        )

        normalized: set[Permission] = set()
        for permission in sorted_permissions:
            if any(existing.covers(permission) for existing in normalized):
                continue

            normalized = {
                existing
                for existing in normalized
                if not permission.covers(existing)
            }
            normalized.add(permission)

        return normalized

    def __contains__(self, item: Permission):
        return any(permission.covers(item) for permission in self.permissions)

    def __le__(self, other: Self):
        return all(permission in other for permission in self.permissions)

    def __or__(self, other: Self) -> Self:
        return PermissionSet(self.permissions | other.permissions)

    def __sub__(self, other: Self) -> Self:
        return PermissionSet({
            permission
            for permission in self.permissions
            if permission not in other
        })

    def __iter__(self):
        return iter(self.permissions)

    def __len__(self) -> int:
        return len(self.permissions)


def context_getter(workspace_id: uuid.UUID, channel_id: uuid.UUID) -> ScopeContext:
    return ScopeContext(workspace_id=workspace_id,
                        channel_id=channel_id)


def user_perms(
        scope_context: Annotated[ScopeContext, Depends(context_getter)],
        session: SessionDep,
        db: DatabaseDep) -> PermissionSet:
    # TODO: caching, optimize query, prefetch permissions with roles
    user_permissions = db.scalars(
        select(Permission)
        .join(Role, Role.permissions)
        .where(Role.users.any(id=session.sub))
        .where(
            or_(Role.workspace_id == scope_context.workspace_id, Role.workspace_id.is_(None)),
            or_(Role.channel_id == scope_context.channel_id, Role.channel_id.is_(None))
        )
        .order_by(Permission.scope.desc(), Role.priority, Permission.is_deny, Permission.id)
    )

    return PermissionSet(set(user_permissions))


def require_perms(*required_permissions: str):
    """
    Processes permission requirements for a specific context to validate that the user has the
    necessary permissions. This function defines a permission validation system by combining
    a set of required permissions, a context getter, and a context validator, ensuring that
    the user satisfies permission prerequisites based on the given scope context.

    :param required_permissions: A variable list of permission strings that are required.

    :return: A function that validates user permissions by asserting that the required
        permissions are present within the user’s permissions based on the context.
    """

    required_perms = PermissionSet({Permission.from_str(p) for p in required_permissions})

    # TODO: implement caching for user permissions

    def assert_perms(user_permissions: Annotated[PermissionSet, Depends(user_perms)]):
        if not required_perms <= user_permissions:
            raise errors.Forbidden(missing_perms=required_perms - user_permissions)

    return assert_perms
