"""process_file: claim -> download (workspace-scoped) -> route -> stamp.
No Milvus/MinIO touched: storage and the document processor are faked."""
import uuid

import pytest
from sqlalchemy import select

from filesystem.model import File, FileStatus


@pytest.fixture
def uploaded_file(db_session, test_channel):
    f = File(
        id=uuid.uuid4(),
        workspace_id=test_channel.workspace_id,
        channel_id=test_channel.id,
        uploader_id=None,
        filename="note.txt",
        content_type="text/plain",
        size_bytes=10,
        sha256checksum="0" * 64,
        processing_status=FileStatus.UPLOADED,
        uri="minio://docs/note.txt",
    )
    db_session.add(f)
    db_session.commit()

    yield f

    # Committed rows persist in the test Postgres — explicit delete+commit
    # teardown per repo convention (conftest test_workspace/test_users).
    db_session.rollback()
    row = db_session.get(File, f.id)
    if row is not None:
        db_session.delete(row)
        db_session.commit()


class _FakeStorage:
    def __init__(self, config, workspace_id, channel_id=None):
        self.workspace_id = workspace_id
        self.channel_id = channel_id
        _FakeStorage.last = self


async def _fake_process_document(file_record, db, storage):
    _fake_process_document.called_with = (file_record.id, type(storage).__name__)


async def test_process_file_stamps_indexed_on_success(db_session, uploaded_file, monkeypatch):
    import processing.tasks as tasks

    monkeypatch.setattr(tasks, "MinIOFileSystem", _FakeStorage)
    monkeypatch.setattr("processing.documents.process_document", _fake_process_document)

    await tasks.process_file.original_func(uploaded_file.id)

    db_session.expire_all()
    row = db_session.scalar(select(File).where(File.id == uploaded_file.id))
    assert row.processing_status == FileStatus.INDEXED
    assert _FakeStorage.last.workspace_id == uploaded_file.workspace_id
    assert _FakeStorage.last.channel_id == uploaded_file.channel_id


async def test_process_file_stamps_failed_on_error(db_session, uploaded_file, monkeypatch):
    import processing.tasks as tasks

    monkeypatch.setattr(tasks, "MinIOFileSystem", _FakeStorage)

    async def _boom(file_record, db, storage):
        raise RuntimeError("parse exploded")
    monkeypatch.setattr("processing.documents.process_document", _boom)

    try:
        await tasks.process_file.original_func(uploaded_file.id)
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    db_session.expire_all()
    row = db_session.scalar(select(File).where(File.id == uploaded_file.id))
    assert row.processing_status == FileStatus.PROCESSING_FAILED
