"""
Parametrized filesystem tests.

Each test runs against both MinIOFileSystem and GDriveFileSystem via the `fs`
fixture. Only the fsspec AbstractFileSystem / AsyncFileSystem interface is
used — no backend-specific methods, no SDK imports.

Skipped deliberately:
- Overwrite semantics: backend-defined, asserting them couples tests to
  implementation choices that may intentionally differ between backends.
- Signed URL reachability: sign() returns a presigned URL; whether it resolves
  is a network/infra concern, not a filesystem interface concern. We assert
  the string is non-empty and looks like a URL.
"""

from __future__ import annotations

import io

import pytest


# ---------------------------------------------------------------------------
# Existence and directory primitives
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_and_exists(fs, tmp_prefix):
    """A file put to a path must be visible via exists()."""
    path = f"{tmp_prefix}/hello.txt"
    await fs._put_file(io.BytesIO(b"hello"), path)
    assert await fs._exists(path)


@pytest.mark.asyncio
async def test_nonexistent_path_not_exists(fs, tmp_prefix):
    """exists() must return False for a path that was never written."""
    assert not await fs._exists(f"{tmp_prefix}/ghost.txt")


@pytest.mark.asyncio
async def test_mkdir_and_isdir(fs, tmp_prefix):
    """mkdir() must make isdir() return True for the created path."""
    dir_path = f"{tmp_prefix}/subdir"
    await fs._mkdir(dir_path)
    assert await fs._isdir(dir_path)


@pytest.mark.asyncio
async def test_file_is_not_dir(fs, tmp_prefix):
    """
    A regular file must not be reported as a directory.
    Guards against implementations that conflate the two.
    """
    path = f"{tmp_prefix}/file.bin"
    await fs._put_file(io.BytesIO(b"data"), path)
    assert not await fs._isdir(path)


# ---------------------------------------------------------------------------
# Content integrity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_and_cat_roundtrip(fs, tmp_prefix):
    """
    cat() must return exactly the bytes that were put.
    This is the core storage contract; if this fails, every higher-level
    test is unreliable.
    """
    payload = b"the quick brown fox" * 100
    path = f"{tmp_prefix}/content.bin"
    await fs._put_file(io.BytesIO(payload), path)
    result = await fs._cat_file(path)
    assert result == payload


@pytest.mark.asyncio
async def test_open_read_roundtrip(fs, tmp_prefix):
    """
    open(path, 'rb').read() must return the original bytes.
    Tests the file-object interface independently of _cat_file.
    """
    payload = b"\x00\x01\x02\x03" * 256
    path = f"{tmp_prefix}/binary.bin"
    await fs._put_file(io.BytesIO(payload), path)

    async with await fs.open_async(path, "rb") as f:
        result = await f.read()

    assert result == payload


@pytest.mark.asyncio
async def test_open_write_then_cat(fs, tmp_prefix):
    """
    Writing via open(path, 'wb') must be readable back via _cat_file.
    Validates that write-via-file-object and read-via-cat are consistent.
    """
    payload = b"written via open()"
    path = f"{tmp_prefix}/via_open.txt"

    async with await fs.open_async(path, "wb") as f:
        await f.write(payload)

    result = await fs._cat_file(path)
    assert result == payload


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_info_has_required_keys(fs, tmp_prefix):
    """
    info() must include name, size, and type.
    These are the three keys the service layer reads unconditionally.
    """
    path = f"{tmp_prefix}/meta.txt"
    await fs._put_file(io.BytesIO(b"x" * 42), path)
    meta = await fs._info(path)
    assert "name" in meta
    assert "size" in meta
    assert "type" in meta


@pytest.mark.asyncio
async def test_info_size_matches_uploaded_bytes(fs, tmp_prefix):
    """info()['size'] must equal the exact byte count uploaded."""
    payload = b"a" * 1337
    path = f"{tmp_prefix}/sized.bin"
    await fs._put_file(io.BytesIO(payload), path)
    meta = await fs._info(path)
    assert meta["size"] == len(payload)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ls_shows_uploaded_file(fs, tmp_prefix):
    """
    ls() on the parent directory must include a file after it is uploaded.
    Validates the listing pipeline used by list_files and directory GET.
    """
    dir_path = f"{tmp_prefix}/listing"
    await fs._mkdir(dir_path)
    file_path = f"{dir_path}/a.txt"
    await fs._put_file(io.BytesIO(b"a"), file_path)

    entries = await fs._ls(dir_path, detail=False)
    assert file_path in entries


@pytest.mark.asyncio
async def test_ls_multiple_files_all_appear(fs, tmp_prefix):
    """
    All files uploaded to a directory must appear in ls().
    A single-file ls test wouldn't catch off-by-one truncation bugs.
    """
    dir_path = f"{tmp_prefix}/multi"
    await fs._mkdir(dir_path)
    names = ["alpha.txt", "beta.txt", "gamma.txt"]
    for name in names:
        await fs._put_file(io.BytesIO(name.encode()), f"{dir_path}/{name}")

    entries = await fs._ls(dir_path, detail=False)
    for name in names:
        assert f"{dir_path}/{name}" in entries


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rm_removes_file(fs, tmp_prefix):
    """exists() must return False after rm()."""
    path = f"{tmp_prefix}/todelete.txt"
    await fs._put_file(io.BytesIO(b"bye"), path)
    await fs._rm_file(path)
    assert not await fs._exists(path)


@pytest.mark.asyncio
async def test_rm_nonexistent_raises(fs, tmp_prefix):
    """
    rm() on a missing path must raise FileNotFoundError.
    Silent no-ops would mask bugs where the wrong path is deleted.
    """
    with pytest.raises(FileNotFoundError):
        await fs._rm_file(f"{tmp_prefix}/does_not_exist.txt")


@pytest.mark.asyncio
async def test_rm_removes_from_ls(fs, tmp_prefix):
    """
    A deleted file must not appear in subsequent ls() calls.
    Separately from exists(), this validates listing cache invalidation.
    """
    dir_path = f"{tmp_prefix}/rmls"
    await fs._mkdir(dir_path)
    path = f"{dir_path}/victim.txt"
    await fs._put_file(io.BytesIO(b"victim"), path)
    await fs._rm_file(path)

    entries = await fs._ls(dir_path, detail=False)
    assert path not in entries


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_copy_produces_identical_content(fs, tmp_prefix):
    """copy() must produce a destination with identical bytes to the source."""
    src = f"{tmp_prefix}/src.bin"
    dst = f"{tmp_prefix}/dst.bin"
    payload = b"copy me"
    await fs._put_file(io.BytesIO(payload), src)
    await fs.copy(src, dst)
    assert await fs._cat_file(dst) == payload


@pytest.mark.asyncio
async def test_copy_source_still_exists(fs, tmp_prefix):
    """copy() must not remove the source (it is not a move)."""
    src = f"{tmp_prefix}/original.bin"
    dst = f"{tmp_prefix}/clone.bin"
    await fs._put_file(io.BytesIO(b"original"), src)
    await fs.copy(src, dst)
    assert await fs._exists(src)


# ---------------------------------------------------------------------------
# Signed URLs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sign_returns_nonempty_string(fs, tmp_prefix):
    """
    sign() must return a non-empty string for an existing file.
    We don't validate URL reachability — that's an infra concern.
    We do validate the string is URL-shaped so that clients aren't handed garbage.
    """
    path = f"{tmp_prefix}/signed.bin"
    await fs._put_file(io.BytesIO(b"sign me"), path)
    url = fs.sign(path, operation="get_object")
    assert isinstance(url, str) and url.startswith("http")
