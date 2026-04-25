from backend.auth.utils.helpers import UserDep
from fastapi import APIRouter
from model.identity import PlatformRole, Permission, User
from sqlalchemy import select
from model import DatabaseDep

router = APIRouter(prefix="/authorization", tags=["authorization"])


@router.get("/summary")
def authorization_summary(user: UserDep):
    role_rows: list[PlatformRole] = list(user.roles) if user.roles else []
    roles_out = [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "permission_ids": [str(p.id) for p in (r.permissions or [])],
        }
        for r in role_rows
    ]

    seen: set[str] = set()
    permissions: list[dict] = []
    for r in role_rows:
        for p in r.permissions or []:
            if p.name in seen:
                continue
            seen.add(p.name)
            permissions.append(
                {
                    "id": str(p.id),
                    "name": p.name,
                    "description": p.description,
                }
            )

    return {
        "user_id": str(user.id),
        "roles": roles_out,
        "permissions": permissions,
        "workspace_scopes": [
            {
                "workspace_id": None,
                "label": "All workspaces you own or are a member of",
                "access": "owner_full",
            }
        ],
        "resource_matrix": {
            "rows": [
                {
                    "resource": "Workspaces",
                    "actions": ["read", "write", "admin"],
                    "note": "Create and manage teams, members, and workspace settings",
                },
                {
                    "resource": "Chat",
                    "actions": ["read", "write"],
                    "note": "Post and read in channels you can access",
                },
                {
                    "resource": "Documents",
                    "actions": ["read", "write", "delete"],
                    "note": "Upload, search, and remove files in allowed workspaces",
                },
            ],
        },
    }


@router.get("/platform-roles")
def list_platform_roles(_user: UserDep, db: DatabaseDep):
    rows = db.scalars(select(PlatformRole).order_by(PlatformRole.name)).all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "permission_names": [p.name for p in (r.permissions or [])],
        }
        for r in rows
    ]


@router.get("/platform-permissions")
def list_all_permissions(_user: UserDep, db: DatabaseDep):
    rows = db.scalars(select(Permission).order_by(Permission.name)).all()
    return [
        {"id": str(p.id), "name": p.name, "description": p.description}
        for p in rows
    ]
