"""Quick manual test for file upload flow — bypasses auth via dependency override.

Usage:
    PYTHONPATH=src uv run python scripts/test_upload.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from backend.auth.dependencies import active_user
from files.dependencies import get_workspace_member, get_storage
from model.base import get_db, SessionLocal, engine, Base
from model.identity import User
from model.messaging import Workspace
from files.models import FileAttachment  # noqa: F401
from files.storage import MinIOStorage
from config import config
from app import app


# --- Setup: create a real user + workspace in the DB ---
from sqlalchemy.orm import Session as SASession
from sqlalchemy import text

with SASession(engine) as s:
    s.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
    s.commit()
Base.metadata.create_all(engine)

user_id = uuid.uuid4()
ws_id = uuid.uuid4()

db = SessionLocal()

user = User(
    id=user_id,
    username=f"tester_{user_id.hex[:8]}",
    primary_email=f"tester_{user_id.hex[:8]}@test.com",
    email_verified=True,
    name="Test User",
    data={},
)
db.add(user)
db.flush()

ws = Workspace(id=ws_id, name=f"test_ws_{ws_id.hex[:8]}", owner_id=user.id)
db.add(ws)
db.commit()
db.refresh(user)
db.refresh(ws)

print(f"Created user {user_id} and workspace {ws_id}")

# --- Override auth + deps, use the same DB session ---
app.dependency_overrides[active_user] = lambda: user
app.dependency_overrides[get_workspace_member] = lambda: ws
app.dependency_overrides[get_db] = lambda: db

# Use REAL MinIO storage
cfg = config().minio
storage = MinIOStorage(
    internal_endpoint=cfg.internal_endpoint,
    external_endpoint=cfg.external_endpoint,
    access_key=cfg.access_key,
    secret_key=cfg.secret_key,
    secure=cfg.secure,
    bucket_name=cfg.bucket_name,
)
app.dependency_overrides[get_storage] = lambda: storage

# Disable lifespan (avoid reconnecting to MinIO/Redis/ARQ)
@asynccontextmanager
async def _noop_lifespan(_app):
    _app.state.arq_pool = None
    _app.state.minio_storage = storage
    yield

app.router.lifespan_context = _noop_lifespan

client = TestClient(app, raise_server_exceptions=False)

# --- Test 1: Upload a text file ---
print("\n--- Test 1: Upload text file ---")
resp = client.post(
    f"/api/workspaces/{ws_id}/files",
    files={"file": ("hello.txt", b"Hello from Talos upload test!", "text/plain")},
)
print(f"Status: {resp.status_code}")
if resp.status_code >= 400:
    print(f"Error: {resp.text}")
else:
    print(f"Response: {resp.json()}")

if resp.status_code == 202:
    file_id = resp.json()["file_id"]

    # --- Test 2: Get metadata ---
    print("\n--- Test 2: Get file metadata ---")
    resp2 = client.get(f"/api/workspaces/{ws_id}/files/{file_id}")
    print(f"Status: {resp2.status_code}")
    print(f"Response: {resp2.json()}")

    # --- Test 3: Get download URL ---
    print("\n--- Test 3: Get download URL ---")
    resp3 = client.get(f"/api/workspaces/{ws_id}/files/{file_id}/download")
    print(f"Status: {resp3.status_code}")
    print(f"Response: {resp3.json()}")

    # --- Test 4: List files ---
    print("\n--- Test 4: List workspace files ---")
    resp4 = client.get(f"/api/workspaces/{ws_id}/files")
    print(f"Status: {resp4.status_code}")
    data = resp4.json()
    print(f"Files: {len(data['files'])}, next_cursor: {data['next_cursor']}")

    # --- Test 5: Get status ---
    print("\n--- Test 5: Get processing status ---")
    resp5 = client.get(f"/api/workspaces/{ws_id}/files/{file_id}/status")
    print(f"Status: {resp5.status_code}")
    print(f"Response: {resp5.json()}")

    # --- Test 6: Soft delete ---
    print("\n--- Test 6: Soft delete ---")
    resp6 = client.delete(f"/api/workspaces/{ws_id}/files/{file_id}")
    print(f"Status: {resp6.status_code}")
    print(f"Deleted at: {resp6.json().get('deleted_at')}")

    # --- Test 7: Verify deleted file excluded from list ---
    print("\n--- Test 7: List after delete ---")
    resp7 = client.get(f"/api/workspaces/{ws_id}/files")
    print(f"Files after delete: {len(resp7.json()['files'])}")

print("\nAll done!")
app.dependency_overrides.clear()
client.close()
db.close()
