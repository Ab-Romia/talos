import os
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from model import Base, get_db
from model.identity import User
from model.messaging import Workspace, Chatroom, Message
from files.models import FileAttachment, ProcessingStatus

TEST_DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://talos_app:password@localhost:5432/talos_test"
)


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DB_URL, echo=False)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        conn.commit()
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """Per-test session with rollback cleanup."""
    TestSession = sessionmaker(bind=test_engine)
    session = TestSession()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def test_user(db_session):
    user = User(
        id=uuid.uuid4(),
        username=f"test_{uuid.uuid4().hex[:8]}",
        primary_email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        email_verified=True,
        name="Test User",
        data={},
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def test_workspace(db_session, test_user):
    ws = Workspace(
        id=uuid.uuid4(),
        name=f"ws_{uuid.uuid4().hex[:8]}",
        owner_id=test_user.id,
    )
    db_session.add(ws)
    db_session.flush()
    return ws


@pytest.fixture
def test_chatroom(db_session, test_workspace):
    cr = Chatroom(
        id=uuid.uuid4(),
        name="general",
        workspace_id=test_workspace.id,
    )
    db_session.add(cr)
    db_session.flush()
    return cr


@pytest.fixture
def test_message(db_session, test_workspace, test_chatroom, test_user):
    msg = Message(
        id=uuid.uuid4(),
        workspace_id=test_workspace.id,
        chatroom_id=test_chatroom.id,
        sender_id=test_user.id,
        content="Hello",
    )
    db_session.add(msg)
    db_session.flush()
    return msg


def _make_file_in_db(db_session, workspace_id, chatroom_id=None, uploader_id=None, **overrides):
    """Helper to insert a FileAttachment into the test DB."""
    file_id = overrides.pop("id", uuid.uuid4())
    defaults = dict(
        id=file_id,
        workspace_id=workspace_id,
        chatroom_id=chatroom_id,
        uploader_id=uploader_id,
        original_filename="test.txt",
        content_type="text/plain",
        size_bytes=100,
        storage_key=f"workspaces/{workspace_id}/chatrooms/general/{file_id}.txt",
        checksum=uuid.uuid4().hex,
        processing_status=ProcessingStatus.UPLOADED,
    )
    defaults.update(overrides)
    f = FileAttachment(**defaults)
    db_session.add(f)
    db_session.flush()
    return f


@pytest.fixture
def make_file(db_session, test_user):
    """Factory fixture to create files in DB."""
    def _factory(workspace_id, **kwargs):
        kwargs.setdefault("uploader_id", test_user.id)
        return _make_file_in_db(db_session, workspace_id, **kwargs)
    return _factory


@pytest.fixture
def client(db_session, test_user, test_workspace, mock_storage):
    """FastAPI TestClient with all dependencies overridden and lifespan disabled."""
    from fastapi.testclient import TestClient
    from backend.auth.utils.helpers import active_user
    from files.dependencies import get_workspace_member, get_storage
    from app import app

    # Replace the lifespan with a no-op to avoid connecting to MinIO/Redis
    @asynccontextmanager
    async def _noop_lifespan(_app):
        _app.state.arq_pool = None
        _app.state.minio_storage = mock_storage
        yield

    original_router = app.router
    original_lifespan = original_router.lifespan_context
    original_router.lifespan_context = _noop_lifespan

    app.dependency_overrides[active_user] = lambda: test_user
    app.dependency_overrides[get_workspace_member] = lambda: test_workspace
    app.dependency_overrides[get_storage] = lambda: mock_storage
    app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()
    original_router.lifespan_context = original_lifespan
