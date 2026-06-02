import uuid
from datetime import timedelta
from functools import lru_cache
from typing import Callable
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import app
from auth.model import User, IdentityProvider, Issuer
from auth.password import hash_password
from auth.utils.jwt import create_token
from auth.utils.session import SessionClaims, Session as UserSession
from files.model import FileAttachment, ProcessingStatus
from files.storage import MinIOStorage
from model import SessionLocal
from permissions.model import Role, RolePermission, Permission, PermissionScope, DEFAULT_EVERYONE_ROLE_ID, \
    STATIC_ROLE_ID, ScopedPermission
from workspace.model import Workspace, Channel


@pytest.fixture(scope="session", autouse=True)
async def init():
    from app import lifespan
    from model import engine, Base
    Base.metadata.drop_all(engine)

    async with lifespan(app):
        yield


@pytest.fixture(autouse=True)
def db_session():
    """Provide a per-test DB and override app dependency to return it."""
    from model import _get_db

    with SessionLocal() as db:
        try:
            app.dependency_overrides[_get_db] = lambda: db
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            app.dependency_overrides.pop(_get_db, None)


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def path(client: TestClient):
    def build_path(route: str | Callable, **path_params):
        if callable(route):
            route = route.__name__
        return client.app.url_path_for(route, **path_params)

    return build_path


@pytest.fixture
def test_users(db_session: Session):
    from faker import Faker
    faker = Faker()
    users = []

    def _create_user():
        while True:
            user = User(
                username=faker.user_name(),
                primary_email=faker.email(),
                signup_complete=True,
                name=faker.name(),
                data={},
                roles=[],
            )
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)

            users.append(user)
            yield user

    yield _create_user()

    try:
        db_session.rollback()
        db_session.delete_all(users)
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


@pytest.fixture
def test_user(test_users):
    """A single test user. Use test_users if you need multiple."""
    return next(test_users)


@lru_cache
def hash_pw_cached(pwd):
    return hash_password(pwd)


@pytest.fixture
def test_user_with_password(db_session: Session, test_user: User):
    password = "TestPassword123!"
    password_hash = hash_pw_cached(password)

    identity = IdentityProvider(
        user_id=test_user.id,
        issuer=Issuer.password,
        data={"hash": password_hash},
    )
    db_session.add(identity)
    db_session.commit()

    return test_user, password


def create_session(user: User, db: Session) -> SessionClaims:
    from datetime import timezone, datetime
    session = UserSession(user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    return SessionClaims(
        sub=user.id,
        jti=session.id,
        exp=datetime.now(timezone.utc) + timedelta(days=30),
    )


@pytest.fixture
def test_session(db_session: Session, test_user: User) -> SessionClaims:
    return create_session(test_user, db_session)


@pytest.fixture
def auth_token(test_session) -> str:
    return create_token(test_session)


@pytest.fixture
def auth_tokens(db_session):
    def _factory(user: User):
        session = create_session(user, db_session)
        return create_token(session)

    return _factory


@pytest.fixture
def sudo_auth_token(test_user: User, test_session: SessionClaims) -> str:
    from datetime import timezone, datetime
    claims = SessionClaims(
        sub=test_user.id,
        jti=test_session.jti,
        exp=datetime.now(timezone.utc) + timedelta(minutes=15),
        sudo_exp=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    return create_token(claims)


@pytest.fixture
def expired_token(test_user: User, test_session: SessionClaims) -> str:
    from datetime import timezone, datetime
    claims = SessionClaims(
        sub=test_user.id,
        jti=test_session.jti,
        exp=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    return create_token(claims)


@pytest.fixture
def mock_storage():
    """Fully mocked MinIOStorage. Upload_file drains the stream the same
    way minio-py does in prod, so the HashingReader actually hashes."""
    storage = AsyncMock(spec=MinIOStorage)
    storage.bucket_name = "talos-uploads"

    async def _drain_then_return(*, storage_key, data, size, content_type):
        while data.read(64 * 1024):
            pass
        return "test-etag"

    storage.upload_file = AsyncMock(side_effect=_drain_then_return)
    storage.download_file = AsyncMock(return_value=b"file content")
    storage.download_file_to_path = AsyncMock()
    storage.delete_file = AsyncMock()
    storage.ensure_bucket = AsyncMock()
    storage.generate_presigned_download_url = AsyncMock(
        return_value="http://localhost:9000/presigned"
    )
    storage.generate_presigned_upload_url = AsyncMock(
        return_value="http://localhost:9000/presigned-upload"
    )
    return storage


@pytest.fixture
def sample_file_record():
    """A FileAttachment with sensible defaults for unit tests."""
    file_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    return FileAttachment(
        id=file_id,
        workspace_id=workspace_id,
        channel_id=None,
        uploader_id=uuid.uuid4(),
        original_filename="test.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        checksum="abc123def456",
        processing_status=ProcessingStatus.UPLOADED,
    )


@pytest.fixture
def get_perm(db_session):
    def helper(resource, action, scope=PermissionScope.ANY):
        return db_session.scalar(
            select(Permission)
            .where(Permission.resource == resource)
            .where(Permission.action == action)
            .where(Permission.allowed_scopes.contains([scope]))
        )

    return helper


@pytest.fixture
def test_workspace(db_session: Session, test_user: User, get_perm):
    ws = Workspace(
        name=f"ws_{uuid.uuid4().hex[:8]}",
        owner_id=test_user.id,
    )
    db_session.add(ws)
    db_session.commit()

    role = Role(name=f"test_role_{ws.id.hex[:8]}", workspace_id=ws.id, priority=1)
    role.users.append(test_user)

    perms = [
        get_perm("workspace", "view"),
        get_perm("channel", "view"),
        get_perm("workspace.role", "view"),
        get_perm("workspace.role", "manage"),
    ]
    for perm in perms:
        role.permissions.append(RolePermission(permission_id=perm.id))

    db_session.add(role)
    db_session.commit()

    yield ws

    try:
        db_session.rollback()
        db_session.delete(ws)
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


@pytest.fixture
def make_channel(db_session: Session, test_workspace: Workspace):
    """Factory fixture to create Channels within the test workspace."""

    def _make_channel(name=None):
        if name is None:
            name = f"channel_{uuid.uuid4().hex[:8]}"

        ch = Channel(
            name=name,
            workspace_id=test_workspace.id,
        )
        db_session.add(ch)
        db_session.commit()
        return ch

    return _make_channel


@pytest.fixture
def test_channel(make_channel):
    """A single test channel. Use make_channel if you need multiple."""
    return make_channel()


@pytest.fixture(scope="session")
def test_permissions():
    return [
        ("message", "send", [*PermissionScope]),
        ("workspace", "view", [*PermissionScope]),
        ("channel", "view", [*PermissionScope]),
        ("workspace.role", "view", [*PermissionScope]),
        ("workspace.role", "manage", [*PermissionScope]),
        ("test", "view", [*PermissionScope]),

        # messaging
        ("channel.member", "view_presence", [*PermissionScope]),
        ("channel.message", "send", [*PermissionScope]),
        ("channel.message", "view_history", [*PermissionScope]),
    ]


@pytest.fixture
def make_role(db_session, test_user, get_perm, test_workspace):
    """Factory fixture to create a Role with permissions from "resource:action:scope" strings."""

    def _make_role(name=None, permissions=None, workspace_id=test_workspace.id, priority=1, user=test_user):
        if name is None:
            name = f"role_{uuid.uuid4().hex[:8]}"

        if permissions is None:
            permissions = []

        role = Role(name=name, workspace_id=workspace_id, priority=priority)

        for perm_str in permissions:
            scoped_perm = ScopedPermission.from_str(perm_str)
            perm = get_perm(scoped_perm.resource, scoped_perm.action)
            role.permissions.append(RolePermission(permission_id=perm.id, scope=scoped_perm.scope))

        db_session.add(role)
        db_session.flush()
        if user:
            role.users.append(user)
        return role

    return _make_role


@pytest.fixture(scope="session", autouse=True)
def registry(test_permissions):
    with SessionLocal() as db_session:
        everyone = Role(
            id=DEFAULT_EVERYONE_ROLE_ID,
            name="everyone",
            description=None,
            workspace_id=None,
            priority=0,
        )

        static = Role(
            id=STATIC_ROLE_ID,
            name="static",
            description="Static role, contains permissions that are always active regardless of workspace or channel.",
            workspace_id=None,
            priority=0,
        )
        permissions = [
            Permission(resource=resource, action=action, allowed_scopes=scopes)
            for resource, action, scopes
            in test_permissions
        ]
        db_session.add_all(permissions)
        db_session.flush()

        for perm in permissions:
            if PermissionScope.OWN in perm.allowed_scopes:
                static.permissions.append(RolePermission(permission_id=perm.id, scope=PermissionScope.OWN))

        db_session.add_all([everyone, static])
        db_session.commit()
