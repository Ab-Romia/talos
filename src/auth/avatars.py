import io
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, status
from PIL import Image
from starlette.responses import Response

from config import cfg
from database import DatabaseDep
from .dependencies import UserDep
from .model import User

router = APIRouter()

_AVATAR_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
_MAX_BYTES = 8 * 1024 * 1024
_SIZE = 256


def _key(user_id) -> str:
    return f"{cfg().minio.bucket}/avatars/{user_id}.png"


def avatar_url_for(user: User) -> str | None:
    """Public URL for a user's avatar, versioned so a change busts the cache."""
    version = (user.data or {}).get("avatar_version")
    return f"/api/auth/avatar/{user.id}?v={version}" if version else None


@router.post("/me/avatar")
async def upload_avatar(file: UploadFile, user: UserDep, db: DatabaseDep):
    """Store a square 256px PNG avatar for the caller and bump its version."""
    if (file.content_type or "") not in _AVATAR_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported image type")

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image is too large (8 MB max)")

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid image file")

    img = img.convert("RGB")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((_SIZE, _SIZE), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")

    from filesystem.documents import _fs
    _fs().pipe_file(_key(user.id), buf.getvalue())

    user.data = {**(user.data or {}), "avatar_version": int(datetime.now(timezone.utc).timestamp())}
    db.commit()
    return {"avatar_url": avatar_url_for(user)}


@router.delete("/me/avatar", status_code=status.HTTP_204_NO_CONTENT)
def delete_avatar(user: UserDep, db: DatabaseDep):
    data = dict(user.data or {})
    if data.pop("avatar_version", None) is not None:
        user.data = data
        db.commit()


@router.get("/avatar/{user_id}")
def get_avatar(user_id: UUID, db: DatabaseDep):
    """Public: stream a user's avatar so it renders in plain <img> tags."""
    u = db.get(User, user_id)
    if u is None or not (u.data or {}).get("avatar_version"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No avatar")

    from filesystem.documents import _fs
    try:
        with _fs().open(_key(user_id), "rb") as f:
            data = f.read()
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No avatar")

    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=31536000"})
