import uuid
from tempfile import TemporaryFile
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete

from files.model import FileAttachment, ProcessingStatus
from model.messaging import Workspace, Channel, Message


@pytest.fixture
def test_workspace(db_session, test_user):
    workspace = Workspace(
        name=f"ws_{uuid.uuid4().hex[:8]}",
        owner_id=test_user.id,
    )
    db_session.add(workspace)
    db_session.commit()

    yield workspace

    # Use raw delete to bypass ORM-level cascade handling that causes workspace_id -> NULL updates
    db_session.execute(delete(Workspace).where(Workspace.id == workspace.id))
    db_session.commit()


@pytest.fixture
def test_channel(db_session, test_workspace):
    channel = Channel(
        name="general",
        workspace_id=test_workspace.id,
    )
    db_session.add(channel)
    db_session.commit()

    yield channel

    db_session.delete(channel)
    db_session.commit()


@pytest.fixture
def test_message(db_session, test_workspace, test_channel, test_user):
    message = Message(
        workspace_id=test_workspace.id,
        channel_id=test_channel.id,
        sender_id=test_user.id,
        content="Hello",
    )
    db_session.add(message)
    db_session.commit()

    yield message

    db_session.delete(message)
    db_session.commit()


@pytest.fixture
def test_file_record(db_session, test_workspace, test_user):
    file_record = FileAttachment(
        workspace_id=test_workspace.id,
        uploader_id=test_user.id,
        original_filename="test.txt",
        content_type="text/plain",
        size_bytes=100,
        checksum=uuid.uuid4().hex,
        processing_status=ProcessingStatus.UPLOADED,
    )
    db_session.add(file_record)
    db_session.commit()

    yield file_record

    db_session.delete(file_record)
    db_session.commit()


@pytest.fixture
def indexed_file_record(db_session, test_file_record):
    test_file_record.processing_status = ProcessingStatus.INDEXED
    db_session.flush()
    return test_file_record


@pytest.fixture
def channel_file_record(db_session, test_file_record, test_channel):
    test_file_record.channel_id = test_channel.id
    db_session.flush()
    return test_file_record


@pytest.fixture
def file_service(test_storage, db_session):
    from files.service import FileService

    return FileService(storage=test_storage, db=db_session)


@pytest.fixture
def test_uploaded_file(filename="test.txt", content=b"test content"):
    mock = AsyncMock()
    mock.filename = filename

    tmp = TemporaryFile()
    tmp.write(content)
    tmp.seek(0)
    mock.file = tmp

    async def _read(size: int = -1) -> bytes:
        if size is None or size < 0:
            return tmp.read()
        return tmp.read(size)

    async def _seek(pos: int) -> None:
        tmp.seek(pos)

    mock.read = _read
    mock.seek = _seek

    return mock
