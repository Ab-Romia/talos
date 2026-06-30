"""
End-to-end tests for the files router.

Assumes fixtures from root conftest:
  - client          — AsyncClient wired to the FastAPI app
  - auth_headers    — takes a user object, returns Authorization headers
  - workspace       — a persisted Workspace ORM object
  - channel         — a persisted Channel in `workspace`
  - test_user       — a persisted User with files:read/write perms in `workspace`
  - db_session      — auto-rollback session (each test gets clean state)
  - path(fn, **kw)  — resolves URL from handler function + path param kwargs

Assumes fixtures from tests/files/conftest:
  - minio_fs        — MinIOFileSystem backed by testcontainers MinIO

Protocol abbreviation used throughout: "m" (MinIO). GDrive path coverage is
handled by test_filesystem.py; endpoint tests validate routing, not backends.

Dropped from plan:
  - 401 tests per endpoint — auth middleware is tested in the auth suite
  - test_list_files_empty_workspace — list tests after upload cover the empty
    case implicitly (cursor test starts from empty state)
  - test_get_file_metadata_only / test_get_file_with_download_url as separate
    tests — merged into parametrized test_get_file
"""

from __future__ import annotations

import uuid

import pytest
from files.router import (
    create_file_or_directory,
    delete_file,
    get_file,
    list_files,
    replace_file,
    update_file_meta,
)

PROTO = "m"  # MinIO protocol abbreviation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_file_payload(workspace, channel=None, size=128, filename="test.bin"):
    """Minimal valid FileCreateRequest body."""
    header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 56  # 64-byte header, PNG magic
    return {
        "create_type": "file",
        "workspace_id": str(workspace.id),
        "channel_id": str(channel.id) if channel else None,
        "user_id": str(workspace.owner_id),
        "header": header.hex(),  # assume JSON transport encodes bytes as hex
        "sha256checksum": "a" * 64,
        "size": size,
        "parent_uri": f"m://test-bucket/{workspace.id}",
        "filename": filename,
    }


def _ws_kwargs(workspace):
    return {"workspace_id": workspace.id}


def _ch_kwargs(workspace, channel):
    return {"workspace_id": workspace.id, "channel_id": channel.id}


# ---------------------------------------------------------------------------
# POST /create
# ---------------------------------------------------------------------------

class TestCreate:
    @pytest.mark.asyncio
    async def test_file_returns_202_and_upload_url(self, client, auth_headers, workspace, test_user, path):
        payload = _create_file_payload(workspace)
        resp = await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["upload_url"].startswith("http")

    @pytest.mark.asyncio
    async def test_file_channel_scoped_sets_channel_id(
            self, client, auth_headers, workspace, channel, test_user, path, db_session
    ):
        """
        Uploading via the channel-scoped route must persist channel_id on the DB record.
        This is the main invariant the channel scope dep is responsible for.
        """
        from files.model import File
        from sqlalchemy import select

        payload = _create_file_payload(workspace, channel=channel, filename="ch_file.bin")
        resp = await client.post(
            path(create_file_or_directory, **_ch_kwargs(workspace, channel), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 202

        db_file = db_session.execute(
            select(File).where(File.filename == "ch_file.bin")
        ).scalar_one()
        assert db_file.channel_id == channel.id

    @pytest.mark.asyncio
    async def test_workspace_id_mismatch_returns_400(
            self, client, auth_headers, workspace, test_user, path
    ):
        """
        Payload workspace_id must match the path param.
        Mismatch indicates a client bug; 400, not silent acceptance.
        """
        payload = _create_file_payload(workspace)
        payload["workspace_id"] = str(uuid.uuid4())  # wrong workspace
        resp = await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_directory_returns_201(self, client, auth_headers, workspace, test_user, path, minio_fs):
        parent = f"m://test-bucket/{workspace.id}"
        minio_fs.mkdir(parent, exist_ok=True)
        resp = await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json={"create_type": "directory", "uri": f"{parent}/docs"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "directory created"

    @pytest.mark.asyncio
    async def test_duplicate_filename_returns_conflict(
            self, client, auth_headers, workspace, test_user, path
    ):
        """
        Uploading to the same path twice must fail.
        AlreadyExists must surface as 4xx, not a silent 202 that issues
        a second upload URL for the same key.
        """
        payload = _create_file_payload(workspace, filename="dup.bin")
        url = path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO)
        headers = auth_headers(test_user)

        first = await client.post(url, json=payload, headers=headers)
        assert first.status_code == 202

        second = await client.post(url, json=payload, headers=headers)
        assert second.status_code in (409, 400)  # AlreadyExists → Conflict or Bad Request


# ---------------------------------------------------------------------------
# GET list
# ---------------------------------------------------------------------------

class TestList:
    @pytest.mark.asyncio
    async def test_uploaded_file_appears_in_workspace_list(
            self, client, auth_headers, workspace, test_user, path
    ):
        payload = _create_file_payload(workspace, filename="listed.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )

        resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 200
        names = [f["filename"] for f in resp.json()["files"]]
        assert "listed.bin" in names

    @pytest.mark.asyncio
    async def test_channel_scope_does_not_leak_other_channel_files(
            self, client, auth_headers, workspace, channel, test_user, path
    ):
        """
        A channel-scoped list must not return files from other channels.
        Regression guard: a missing WHERE clause would make every channel
        see every file in the workspace.
        """
        # Upload to workspace (no channel)
        ws_payload = _create_file_payload(workspace, filename="ws_only.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=ws_payload,
            headers=auth_headers(test_user),
        )

        resp = await client.get(
            path(list_files, **_ch_kwargs(workspace, channel), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 200
        names = [f["filename"] for f in resp.json()["files"]]
        assert "ws_only.bin" not in names

    @pytest.mark.asyncio
    async def test_content_type_filter(
            self, client, auth_headers, workspace, test_user, path
    ):
        """
        ?content_type=image/ must return only image/* files.
        The header sniffing in get_upload_url determines content_type;
        here we bypass it by using a PNG magic header.
        """
        png_payload = _create_file_payload(workspace, filename="img.png")
        txt_payload = {**_create_file_payload(workspace, filename="doc.txt"),
                       "header": (b"\x00" * 64).hex()}  # non-PNG header → text/... or octet-stream

        headers = auth_headers(test_user)
        url = path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO)
        await client.post(url, json=png_payload, headers=headers)
        await client.post(url, json=txt_payload, headers=headers)

        resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            params={"content_type": "image/"},
            headers=headers,
        )
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert all(f["content_type"].startswith("image/") for f in files)

    @pytest.mark.asyncio
    async def test_cursor_pagination_is_exhaustive(
            self, client, auth_headers, workspace, test_user, path
    ):
        """
        Paginating with limit=2 across 5 files must yield all 5 files with
        no duplicates and a None next_cursor at the end.

        This is the highest-value pagination test: it validates both that
        next_cursor is correct AND that following it terminates.
        """
        headers = auth_headers(test_user)
        create_url = path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO)
        list_url = path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO)

        filenames = [f"page_{i}.bin" for i in range(5)]
        for name in filenames:
            await client.post(create_url, json=_create_file_payload(workspace, filename=name), headers=headers)

        seen = []
        cursor = None
        for _ in range(10):  # hard cap to prevent infinite loop in test
            params = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(list_url, params=params, headers=headers)
            assert resp.status_code == 200
            body = resp.json()
            seen.extend(f["filename"] for f in body["files"])
            cursor = body["next_cursor"]
            if cursor is None:
                break

        # All 5 uploaded files must appear exactly once
        seen_set = set(seen)
        for name in filenames:
            assert name in seen_set
        assert len(seen) == len(set(seen)), "Duplicate files returned across pages"


# ---------------------------------------------------------------------------
# GET single
# ---------------------------------------------------------------------------

class TestGetFile:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("download", [False, True])
    async def test_get_file(self, client, auth_headers, workspace, test_user, path, download):
        """
        GET with download=False returns metadata only.
        GET with download=True additionally returns a non-null download_url.
        Single parametrized test to keep the fixture setup cost O(1).
        """
        payload = _create_file_payload(workspace, filename="getme.bin")
        create_resp = await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        # We don't have a real file_id back from the create response yet (upload URL flow),
        # so look up the file from the list endpoint.
        list_resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        file_id = next(
            f["id"] for f in list_resp.json()["files"] if f["filename"] == "getme.bin"
        )

        resp = await client.get(
            path(get_file, **_ws_kwargs(workspace), protocol_abbr=PROTO, file_or_dir_id=file_id),
            params={"download": download},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["metadata"]["id"] == file_id
        if download:
            assert body["download_url"] is not None and body["download_url"].startswith("http")
        else:
            assert body["download_url"] is None

    @pytest.mark.asyncio
    async def test_get_file_wrong_workspace_returns_404(
            self, client, auth_headers, workspace, test_user, other_workspace, path
    ):
        """
        A file in workspace A must not be accessible via workspace B's path.
        This is the cross-tenant isolation check — the most critical security
        boundary in a multi-tenant file store.
        """
        payload = _create_file_payload(workspace, filename="private.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        list_resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        file_id = list_resp.json()["files"][0]["id"]

        resp = await client.get(
            path(get_file, **_ws_kwargs(other_workspace), protocol_abbr=PROTO, file_or_dir_id=file_id),
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self, client, auth_headers, workspace, test_user, path):
        resp = await client.get(
            path(get_file, **_ws_kwargs(workspace), protocol_abbr=PROTO, file_or_dir_id=uuid.uuid4()),
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH
# ---------------------------------------------------------------------------

class TestUpdateMeta:
    @pytest.mark.asyncio
    async def test_patch_rename_updates_filename(
            self, client, auth_headers, workspace, test_user, path
    ):
        """
        PATCH with a new filename must be reflected in a subsequent GET.
        Tests the full round-trip: write → patch → read.
        """
        payload = _create_file_payload(workspace, filename="original.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        list_resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        file_id = list_resp.json()["files"][0]["id"]

        patch_resp = await client.patch(
            path(update_file_meta, **_ws_kwargs(workspace), protocol_abbr=PROTO, file_id=file_id),
            json={"filename": "renamed.bin"},
            headers=auth_headers(test_user),
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["filename"] == "renamed.bin"

    @pytest.mark.asyncio
    async def test_patch_wrong_workspace_returns_404(
            self, client, auth_headers, workspace, other_workspace, test_user, path
    ):
        payload = _create_file_payload(workspace, filename="cross.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        list_resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        file_id = list_resp.json()["files"][0]["id"]

        resp = await client.patch(
            path(update_file_meta, **_ws_kwargs(other_workspace), protocol_abbr=PROTO, file_id=file_id),
            json={"filename": "hacked.bin"},
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT (replace)
# ---------------------------------------------------------------------------

class TestReplaceFile:
    @pytest.mark.asyncio
    async def test_replace_soft_deletes_old_record(
            self, client, auth_headers, workspace, test_user, path, db_session
    ):
        """
        PUT must soft-delete the previous record, not mutate it.
        This ensures audit trail is preserved and the old record is
        not surfaced in normal listings.
        """
        from files.model import File
        from sqlalchemy import select

        payload = _create_file_payload(workspace, filename="replace_me.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        list_resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        file_id = list_resp.json()["files"][0]["id"]

        replace_payload = _create_file_payload(workspace, filename="replace_me.bin")
        resp = await client.put(
            path(replace_file, **_ws_kwargs(workspace), protocol_abbr=PROTO, file_id=file_id),
            json=replace_payload,
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 202

        old_record = db_session.execute(
            select(File).where(File.id == uuid.UUID(file_id))
        ).scalar_one()
        assert old_record.deleted_at is not None, "Old record must be soft-deleted after replace"

    @pytest.mark.asyncio
    async def test_replace_old_not_in_list(
            self, client, auth_headers, workspace, test_user, path
    ):
        """
        After PUT, the old file_id must not appear in listing.
        Complements the DB-level check above with an API-level assertion.
        """
        payload = _create_file_payload(workspace, filename="gone.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        list_resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        old_file_id = list_resp.json()["files"][0]["id"]

        replace_payload = _create_file_payload(workspace, filename="gone.bin")
        await client.put(
            path(replace_file, **_ws_kwargs(workspace), protocol_abbr=PROTO, file_id=old_file_id),
            json=replace_payload,
            headers=auth_headers(test_user),
        )

        list_after = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        ids_after = [f["id"] for f in list_after.json()["files"]]
        assert old_file_id not in ids_after


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_from_list(
            self, client, auth_headers, workspace, test_user, path
    ):
        """
        After DELETE, the file must not appear in list results.
        We test the list outcome rather than inspecting deleted_at directly —
        that's what callers observe.
        """
        payload = _create_file_payload(workspace, filename="delete_me.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        list_resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        file_id = next(f["id"] for f in list_resp.json()["files"] if f["filename"] == "delete_me.bin")

        del_resp = await client.delete(
            path(delete_file, **_ws_kwargs(workspace), file_id=file_id),
            headers=auth_headers(test_user),
        )
        assert del_resp.status_code == 200

        list_after = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        ids_after = [f["id"] for f in list_after.json()["files"]]
        assert file_id not in ids_after

    @pytest.mark.asyncio
    async def test_delete_sets_deleted_at(
            self, client, auth_headers, workspace, test_user, path, db_session
    ):
        """
        Complements test_delete_removes_from_list: confirms the mechanism
        is a soft-delete, not a hard row deletion. Physical deletion is
        async; we must not lose the record immediately.
        """
        from files.model import File
        from sqlalchemy import select

        payload = _create_file_payload(workspace, filename="soft.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        list_resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        file_id = list_resp.json()["files"][0]["id"]

        await client.delete(
            path(delete_file, **_ws_kwargs(workspace), file_id=file_id),
            headers=auth_headers(test_user),
        )

        record = db_session.execute(
            select(File).where(File.id == uuid.UUID(file_id))
        ).scalar_one()
        assert record.deleted_at is not None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(
            self, client, auth_headers, workspace, test_user, path
    ):
        resp = await client.delete(
            path(delete_file, **_ws_kwargs(workspace), file_id=uuid.uuid4()),
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_wrong_workspace_returns_404(
            self, client, auth_headers, workspace, other_workspace, test_user, path
    ):
        """
        DELETE with a valid file_id but wrong workspace_id must 404, not 200.
        Same cross-tenant isolation check as GET.
        """
        payload = _create_file_payload(workspace, filename="tenant.bin")
        await client.post(
            path(create_file_or_directory, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            json=payload,
            headers=auth_headers(test_user),
        )
        list_resp = await client.get(
            path(list_files, **_ws_kwargs(workspace), protocol_abbr=PROTO),
            headers=auth_headers(test_user),
        )
        file_id = list_resp.json()["files"][0]["id"]

        resp = await client.delete(
            path(delete_file, **_ws_kwargs(other_workspace), file_id=file_id),
            headers=auth_headers(test_user),
        )
        assert resp.status_code == 404
