import uuid
from typing import Literal, Annotated

import fsspec
from fastapi import Path, HTTPException, Depends
from fsspec.asyn import AsyncFileSystem
from starlette import status

from config import cfg
from database import DatabaseDep
from workspace.model import Channel
from .. import errors


def filesystem(
        protocol_abbr: Literal["g", "m"],
        workspace_id: Annotated[uuid.UUID | None, Path(default_factory=lambda: None)],
        channel_id: Annotated[uuid.UUID | None, Path(default_factory=lambda: None)],
        db: DatabaseDep
) -> AsyncFileSystem:
    """Dependency provider for the async file storage backend."""
    match (workspace_id, channel_id):
        case (None, None):
            raise HTTPException(status.HTTP_400_BAD_REQUEST)
        case (None, channel_id):
            workspace_id: uuid.UUID = db.get_one(Channel, channel_id).workspace_id
        case _:
            pass

    assert workspace_id is not None  # for type checker

    match protocol_abbr:
        case "m":
            st = fsspec.filesystem("s3", config=cfg().minio)
            if hasattr(st, "connect") and callable(st.connect):
                st.connect()

            return st
        case "g":
            # TODO: support multiple GDrive accounts and/or per-user creds
            return fsspec.filesystem(
                "gdrive",
                client_creds=None,  # TODO
                user_creds=None,  # TODO
            )
        case _:
            raise errors.FileNotFound()


FSDep = Annotated[AsyncFileSystem, Depends(filesystem)]
