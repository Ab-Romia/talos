from datetime import timedelta

import pytest
import sqlalchemy
import sqlalchemy.exc
from functools import lru_cache
from fastapi.testclient import TestClient
from sqlalchemy import select, text, delete
from sqlalchemy.orm import Session

from app import app
from backend.auth.helpers import JWTClaims
from backend.auth.password import hash_password
from model.identity import User, Session as UserSession, IdentityProvider, Issuer
from utils.datetime import utcnow


@pytest.fixture(scope="session")
def engine():
    """Create a single SQLAlchemy engine for the whole test session.

    - Ensures citext extension exists
    - Creates all tables at session start
    - Drops all tables at session end to delete everything in the DB
    """
    from model import Base as ModelBase

    engine = sqlalchemy.create_engine(
        "postgresql+psycopg2://talos_app:kirowashere@localhost:5432/test"
    )

    # init db extension
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    # create schema for tests
    ModelBase.metadata.create_all(engine)

    try:
        yield engine
    finally:
        # Remove all tables / data at the end of the test session
        ModelBase.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session(engine):
    """Provide a per-test DB session and override app dependency to return it."""
    from model import get_db

    try:
        with Session(engine) as db:
            app.dependency_overrides[get_db] = lambda: db
            yield db
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="function")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def path(client: TestClient):
    def build_path(route_name: str, **path_params):
        return client.app.url_path_for(route_name, **path_params)

    return build_path


@pytest.fixture
def test_user(db_session: Session):
    from faker import Faker
    faker = Faker()

    user_name = faker.user_name()
    try:
        user = User(
            username=user_name,
            primary_email=faker.email(),
            email_verified=True,
            name=faker.name(),
            data={},
            roles=[],
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    except sqlalchemy.exc.IntegrityError:
        user = db_session.scalar(
            select(User)
            .where(User.username == user_name)
        ).one()

    yield user

    # Cleanup
    db_session.execute(delete(User).where(User.id == user.id))
    db_session.commit()


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
def test_session(db_session, test_user: User) -> UserSession:
    session = UserSession(
        user_id=test_user.id,
        expires_at=utcnow() + timedelta(days=30),
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


@pytest.fixture
def auth_token(test_user: User, test_session: UserSession) -> str:
    claims = JWTClaims(
        sub=test_user.id,
        jti=test_session.id,
        exp=test_session.expires_at,
    )
    return claims.to_jwt_string()


@pytest.fixture
def sudo_auth_token(test_user: User, test_session: UserSession) -> str:
    claims = JWTClaims(
        sub=test_user.id,
        jti=test_session.id,
        exp=utcnow() + timedelta(minutes=15),
        sudo=True,
    )
    return claims.to_jwt_string()


@pytest.fixture
def expired_token(test_user: User, test_session: UserSession) -> str:
    claims = JWTClaims(
        sub=test_user.id,
        jti=test_session.id,
        exp=utcnow() - timedelta(hours=1),
    )
    return claims.to_jwt_string()


# ── File upload fixtures ──

import os
import uuid
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://talos_app:password@localhost:5432/talos_test")

# Import identity/messaging models so SQLAlchemy can resolve relationships
import model.identity  # noqa: F401
import model.messaging  # noqa: F401

from files.models import FileAttachment, ProcessingStatus
from files.storage import MinIOStorage


@pytest.fixture
def mock_storage():
    """Fully mocked MinIOStorage."""
    storage = AsyncMock(spec=MinIOStorage)
    storage.bucket_name = "talos-uploads"
    storage.upload_file = AsyncMock(return_value="test-etag")
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
        chatroom_id=None,
        uploader_id=uuid.uuid4(),
        original_filename="test.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        storage_key=f"workspaces/{workspace_id}/chatrooms/general/{file_id}.pdf",
        checksum="abc123def456",
        processing_status=ProcessingStatus.UPLOADED,
    )
