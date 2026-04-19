from enum import Enum, auto
from typing import Annotated, Self

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.sql.operators import in_op

from backend.auth.utils import errors
from backend.auth.utils.session import SessionDep
from model import DatabaseDep
from model.identity import Permission, Role

perms = {
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
    workspace_id: int = None
    channel_id: int = None
    message_id: int = None


class Scope(Enum, int):
    OWN = auto()
    CHANNEL = auto()
    WORKSPACE = auto()
    ANY = auto()

    def __cmp__(self, other):
        if not isinstance(other, Scope):
            return NotImplemented
        return self.value - other.value


class UserPermission(BaseModel):
    resource: str
    action: str
    scope: Scope | None = None
    scope_context: ScopeContext | None = None

    @staticmethod
    def context_specificity(scope_context: ScopeContext | None) -> int:
        if scope_context is None:
            return 0
        return sum(
            value is not None
            for value in (
                scope_context.workspace_id,
                scope_context.channel_id,
                scope_context.message_id,
            )
        )

    @property
    def normalized_scope(self) -> Scope:
        return self.scope or Scope.ANY

    def _context_covers(self, other: "UserPermission") -> bool:
        # No context means global scope (covers all matching contexts).
        if self.scope_context is None:
            return True

        # Context-bound permission cannot satisfy a context-agnostic requirement.
        if other.scope_context is None:
            return False

        for field in ("workspace_id", "channel_id", "message_id"):
            own_value = getattr(self.scope_context, field)
            other_value = getattr(other.scope_context, field)

            if own_value is None:
                continue

            if other_value is None or own_value != other_value:
                return False

        return True

    def covers(self, other: "UserPermission") -> bool:
        if self.resource != other.resource or self.action != other.action:
            return False

        if self.normalized_scope < other.normalized_scope:
            return False

        return self._context_covers(other)

    def __le__(self, other: "UserPermission") -> bool:
        return other.covers(self)

    # TODO: assert that resource, action and scope are valid
    @staticmethod
    def from_str(perm_str: str) -> 'UserPermission':
        chunks = [chunk.strip() for chunk in perm_str.split(":")]
        if len(chunks) not in (2, 3):
            raise ValueError(
                "Invalid permission format. Expected 'resource:action[:scope]'."
            )

        resource, action = chunks[0], chunks[1]
        if not resource or not action:
            raise ValueError("Permission resource and action cannot be empty.")

        scope = Scope.ANY
        if len(chunks) == 3:
            raw_scope = chunks[2]
            try:
                scope = Scope(raw_scope)
            except ValueError as exc:
                raise ValueError(f"Unknown scope '{raw_scope}'.") from exc

        return UserPermission(resource=resource, action=action, scope=scope)

    def __str__(self):
        return f"{self.resource}:{self.action}:{self.scope.value if self.scope else '*'}"


class PermissionSet:
    def __init__(self, permissions: set[UserPermission]):
        self.permissions = self._normalize(permissions)

    @staticmethod
    def _sort_key(permission: UserPermission) -> tuple[int, int, str, str]:
        return (
            -permission.normalized_scope.value,
            UserPermission.context_specificity(permission.scope_context),
            permission.resource,
            permission.action,
        )

    @classmethod
    def _normalize(cls, permissions: set[UserPermission]) -> set[UserPermission]:
        normalized: set[UserPermission] = set()

        for permission in sorted(permissions, key=cls._sort_key):
            if any(existing.covers(permission) for existing in normalized):
                continue

            normalized = {
                existing for existing in normalized if not permission.covers(existing)
            }
            normalized.add(permission)

        return normalized

    def __contains__(self, item: UserPermission):
        return any(permission.covers(item) for permission in self.permissions)

    def __le__(self, other: Self):
        return all(permission in other for permission in self.permissions)

    def __add__(self, other: Self) -> Self:
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


def user_perms(
        scope_context: Annotated[ScopeContext, Depends(context_getter)],
        session: SessionDep,
        db: DatabaseDep) -> PermissionSet:
    user_permissions = db.scalars(
        select(func.distinct(Permission.name))
        .join(Role, Role.permissions)
        .where(in_op(session.sub, Role.users))
    )

    return PermissionSet({UserPermission.from_str(permission) for permission in user_permissions})


def require_perms(*required_permissions: str):
    """
    Processes permission requirements for a specific context to validate that the user has the
    necessary permissions. This function defines a permission validation system by combining
    a set of required permissions, a context getter, and a context validator, ensuring that
    the user satisfies permission prerequisites based on the given scope context.

    :param required_permissions: A variable list of permission strings that are required.
    :param context_getter: A callable responsible for retrieving the current scope's context.
    :param scope_validator: A function used to validate if a given permission is applicable
        within the specified context.
    :return: A function that validates user permissions by asserting that the required
        permissions are present within the user’s permissions based on the context.
    """

    required_perms = PermissionSet({UserPermission.from_str(p) for p in required_permissions})

    # TODO:
    #  - implement caching for user permissions
    #  - scopes (messages:edit:own vs messages:edit:*)

    def assert_perms(user_permissions: UserPermsDep):
        if not required_perms <= user_permissions:
            raise errors.Forbidden(missing_perms=required_perms - user_permissions)

    return assert_perms


UserPermsDep = Annotated[PermissionSet, Depends(user_perms)]
