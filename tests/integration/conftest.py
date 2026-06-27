import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from chat.model import Message
from files.model import File, FileStatus
from tests.conftest import test_workspace, test_channel


@pytest.fixture
def test_message(db_session, test_workspace, test_channel, test_user):
    msg = Message(
        id=uuid.uuid4(),
        workspace_id=test_workspace.id,
        channel_id=test_channel.id,
        sender_id=test_user.id,
        content="Hello",
    )
    db_session.add(msg)
    db_session.flush()
    return msg


def _make_file_in_db(db_session, workspace_id, channel_id=None, uploader_id=None, **overrides):
    """Helper to insert a FileAttachment into the test DB."""
    file_id = overrides.pop("id", uuid.uuid4())
    defaults = dict(
        id=file_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
        uploader_id=uploader_id,
        original_filename="test.txt",
        content_type="text/plain",
        size_bytes=100,
        checksum=uuid.uuid4().hex,
        processing_status=FileStatus.UPLOADED,
    )
    defaults.update(overrides)
    f = File(**defaults)
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
def mock_arq_pool():
    """Fake ARQ pool that records enqueue calls without hitting Redis."""
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    return pool


@pytest.fixture
def client(db_session, test_user, test_workspace, mock_storage, mock_arq_pool):
    """FastAPI TestClient with all dependencies overridden and lifespan disabled."""
    from fastapi.testclient import TestClient
    from auth.dependencies import active_user
    from auth.utils.session import verified_session
    from files.dependencies import workspace_membership, get_storage
    from app import app

    # Replace the lifespan with a no-op to avoid connecting to MinIO/Redis
    @asynccontextmanager
    async def _noop_lifespan(_app):
        _app.state.arq_pool = mock_arq_pool
        _app.state.minio_storage = mock_storage
        yield

    original_router = app.router
    original_lifespan = original_router.lifespan_context
    original_router.lifespan_context = _noop_lifespan

    app.dependency_overrides[active_user] = lambda: test_user
    app.dependency_overrides[verified_session] = lambda: None
    app.dependency_overrides[workspace_membership] = lambda: test_workspace
    app.dependency_overrides[get_storage] = lambda: mock_storage

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()
    original_router.lifespan_context = original_lifespan
