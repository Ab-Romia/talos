import uuid
from datetime import timedelta
from functools import lru_cache
from typing import Callable
from unittest.mock import AsyncMock

import pytest
import sqlalchemy
import sqlalchemy.exc
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import app
from backend.auth.model import User, IdentityProvider, Issuer
from backend.auth.password import hash_password
from backend.auth.permissions.model import Role, RolePermission, Permission, PermissionScope
from backend.auth.utils.jwt import create_token
from backend.auth.utils.session import SessionClaims, Session as UserSession
from files.model import FileAttachment, ProcessingStatus
from files.storage import MinIOStorage
from model.messaging import Workspace, Channel


@pytest.fixture(scope="session", autouse=True)
def engine():
    """Create a single SQLAlchemy engine for the whole test session."""

    from model import Base as ModelBase

    engine = sqlalchemy.create_engine(
        "postgresql+psycopg://talos_app:kirowashere@localhost:5432/test"
    )

    # init db extension
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    ModelBase.metadata.drop_all(engine)
    ModelBase.metadata.create_all(engine)

    try:
        yield engine
    finally:
        ModelBase.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture(autouse=True, scope="session")
def db_session(engine):
    """Provide a per-test DB and override app dependency to return it."""
    from model import get_db

    with Session(engine) as db:
        def _db():
            try:
                yield db
            except Exception:
                db.rollback()
                raise

        try:
            app.dependency_overrides[get_db] = _db
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            app.dependency_overrides.pop(get_db, None)


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

    db_session.delete_all(users)
    db_session.commit()


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


@pytest.fixture
def test_session(db_session: Session, test_user: User) -> SessionClaims:
    from datetime import timezone, datetime
    session = UserSession(user_id=test_user.id)
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    return SessionClaims(
        sub=test_user.id,
        jti=session.id,
        exp=datetime.now(timezone.utc) + timedelta(days=30),
    )


@pytest.fixture
def auth_token(test_session) -> str:
    return create_token(test_session)


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
    """Fully mocked MinIOStorage. upload_file drains the stream the same
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

    db_session.delete(ws)
    db_session.commit()


@pytest.fixture
def test_channel(db_session: Session, test_workspace: Workspace):
    cr = Channel(
        name="general123",
        workspace_id=test_workspace.id,
    )
    db_session.add(cr)
    db_session.commit()

    yield cr
    db_session.delete(cr)
    db_session.commit()
