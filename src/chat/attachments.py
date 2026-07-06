import asyncio
import hashlib
import os
import uuid
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from starlette.responses import StreamingResponse

from auth.dependencies import UserDep
from auth.utils import jwt
from auth.utils.jwt import BaseJWTClaims
from config import cfg
from database import DatabaseDep
from filesystem.model import File, FileStatus
from utils.types import UUID as UUIDType
from workspace import require_perms as require
from workspace.model import Channel

attachments = APIRouter(tags=["attachments"])
media = APIRouter(tags=["attachments"])

_CHUNK = 1024 * 1024


class MediaClaims(BaseJWTClaims):
    """Short-lived, URL-safe grant to stream one attachment. Media elements
    (<img>/<video>) cannot send Authorization headers, so access rides a
    signed token in the query string — same pattern as the Drive proxy."""
    file_id: UUIDType


def _allowed_types() -> set[str]:
    f = cfg().files
    return set(f.document_mime_types) | set(f.image_mime_types) | set(f.video_mime_types)


def attachment_dict(f: File) -> dict:
    return {
        "id": str(f.id),
        "filename": f.filename,
        "content_type": f.content_type,
        "size_bytes": f.size_bytes,
    }


@attachments.post("/attachments", dependencies=[require("channel.message:send")], status_code=201)
async def upload_attachment(channel_id: UUID, file: UploadFile, user: UserDep, db: DatabaseDep):
    """Store a chat attachment (document / image / video). Attachments are
    plain files on MinIO — they are deliberately NEVER queued for RAG indexing."""
    content_type = file.content_type or "application/octet-stream"
    if content_type not in _allowed_types():
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail=f"Attachments of type {content_type} are not supported.")

    data = await file.read()
    if len(data) > cfg().files.attachment_max_size:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Attachment is too large (200 MB max).")

    workspace_id = db.scalar(select(Channel.workspace_id).where(Channel.id == channel_id))
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    from filesystem.documents import _fs

    file_id = uuid.uuid7()
    filename = os.path.basename(file.filename or "attachment")
    key = f"{cfg().minio.bucket}/{workspace_id}/chat/{file_id}/{filename}"
    await asyncio.to_thread(_fs().pipe_file, key, data)

    record = File(
        id=file_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
        uploader_id=user.id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        sha256checksum=hashlib.sha256(data).hexdigest(),
        processing_status=FileStatus.UPLOADED,
        uri=f"minio://{key}",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return attachment_dict(record)


def _is_previewable(content_type: str | None) -> bool:
    f = cfg().files
    ct = content_type or ""
    return ct in set(f.image_mime_types) or ct in set(f.video_mime_types)


@attachments.get("/attachments", dependencies=[require("channel:view")])
async def list_shared_files(channel_id: UUID, user: UserDep, db: DatabaseDep):
    """Every file shared in this conversation, newest first (WhatsApp-style).
    Access is `channel:view`, so DM/group participants — and only them — see it.
    Each entry carries a short-lived signed URL for viewing/downloading."""
    from auth.model import User

    rows = db.execute(
        select(File, User.name, User.username)
        .join(User, User.id == File.uploader_id, isouter=True)
        .where(
            File.channel_id == channel_id,
            File.deleted_at.is_(None),
        )
        .order_by(File.created_at.desc(), File.id.desc())
    ).all()

    items = []
    for f, uploader_name, uploader_username in rows:
        token = MediaClaims(file_id=f.id, exp=jwt.now() + timedelta(hours=2)).encode()
        items.append({
            **attachment_dict(f),
            "url": f"/api/media?token={token}",
            "previewable": _is_previewable(f.content_type),
            "uploader": (uploader_name or uploader_username) if (uploader_name or uploader_username) else None,
            "uploaded_by_me": f.uploader_id == user.id,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        })
    return items


@attachments.get("/attachments/{file_id}/url", dependencies=[require("channel:view")])
async def get_attachment_url(channel_id: UUID, file_id: UUID, db: DatabaseDep):
    """Mint a short-lived streaming URL for an attachment in this channel."""
    exists = db.scalar(
        select(File.id).where(
            File.id == file_id,
            File.channel_id == channel_id,
            File.deleted_at.is_(None),
        )
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    claims = MediaClaims(file_id=file_id, exp=jwt.now() + timedelta(hours=2))
    return {"url": f"/api/media?token={claims.encode()}"}


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header or not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].split(",")[0].strip()
    start_s, _, end_s = spec.partition("-")
    try:
        if start_s:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        else:
            # suffix range: last N bytes
            start = max(0, size - int(end_s))
            end = size - 1
    except ValueError:
        return None
    if start > end or start >= size:
        return None
    return start, min(end, size - 1)


@media.get("/media")
async def stream_media(token: str, db: DatabaseDep,
                       range: Annotated[str | None, Header()] = None):
    """Stream an attachment by signed token, honoring HTTP Range requests so
    video seeking works. Auth = token validity (see MediaClaims)."""
    try:
        claims = MediaClaims.decode(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired media token")

    record = db.get(File, claims.file_id)
    if record is None or record.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    from filesystem.documents import _fs
    fs = _fs()
    key = str(record.uri).removeprefix("minio://")
    size = record.size_bytes

    rng = _parse_range(range, size)
    start, end = rng if rng else (0, size - 1)
    length = end - start + 1

    def reader():
        with fs.open(key, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    # Sanitize the filename before it goes into a response header (strip quotes
    # and control chars that would allow header injection / break parsing).
    safe_name = "".join(c for c in (record.filename or "file") if c.isprintable() and c not in '"\\').strip() or "file"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": f'inline; filename="{safe_name}"',
        "Cache-Control": "private, max-age=3600",
        # Never let the browser MIME-sniff a stored file into something executable.
        "X-Content-Type-Options": "nosniff",
    }
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    return StreamingResponse(
        reader(),
        status_code=status.HTTP_206_PARTIAL_CONTENT if rng else status.HTTP_200_OK,
        media_type=record.content_type or "application/octet-stream",
        headers=headers,
    )
