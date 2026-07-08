"""GitHub REST tools for the implement-ticket -> open-PR loop.

Plain async functions over ``cfg().github`` (owner/repo/token). These expose the
read/branch/commit/PR primitives; the actual code-writing is done by the external
MCP host that calls these tools.
"""
import base64

import httpx

from config import cfg
from utils.logger import get_logger

logger = get_logger(__name__)


def _client() -> httpx.AsyncClient:
    gh = cfg().github
    if gh is None:
        raise RuntimeError("GitHub is not configured (set GITHUB__* env vars).")
    return httpx.AsyncClient(
        base_url=gh.api_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {gh.token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )


def _repo_path() -> str:
    gh = cfg().github
    return f"/repos/{gh.owner}/{gh.repo}"


async def github_get_file(path: str, ref: str | None = None) -> dict:
    """Read a file from the configured repo.

    Args:
        path: Path within the repo, e.g. "src/app.py".
        ref: Optional branch/tag/sha (defaults to the repo default branch).

    Returns {path, content (decoded text), sha}.
    """
    params = {"ref": ref} if ref else {}
    async with _client() as c:
        resp = await c.get(f"{_repo_path()}/contents/{path}", params=params)
        resp.raise_for_status()
        data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return {"path": path, "content": content, "sha": data["sha"]}


async def github_create_branch(new_branch: str, from_branch: str | None = None) -> dict:
    """Create a branch in the configured repo.

    Args:
        new_branch: Name of the branch to create.
        from_branch: Base branch to fork from (defaults to configured base branch).
    """
    base = from_branch or cfg().github.default_base_branch
    async with _client() as c:
        ref = await c.get(f"{_repo_path()}/git/ref/heads/{base}")
        ref.raise_for_status()
        sha = ref.json()["object"]["sha"]
        resp = await c.post(
            f"{_repo_path()}/git/refs",
            json={"ref": f"refs/heads/{new_branch}", "sha": sha},
        )
        resp.raise_for_status()
    return {"ok": True, "branch": new_branch, "from": base}


async def github_put_file(
    path: str, content: str, message: str, branch: str, sha: str | None = None
) -> dict:
    """Create or update a file on a branch (single commit).

    Args:
        path: Path within the repo.
        content: New file content (plain text).
        message: Commit message.
        branch: Branch to commit to.
        sha: Existing blob sha when updating a file; omit when creating.
    """
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    async with _client() as c:
        resp = await c.put(f"{_repo_path()}/contents/{path}", json=payload)
        resp.raise_for_status()
        commit = resp.json()["commit"]["sha"]
    return {"ok": True, "path": path, "branch": branch, "commit": commit}


async def github_open_pr(
    title: str, head: str, base: str | None = None, body: str = ""
) -> dict:
    """Open a pull request in the configured repo.

    Args:
        title: PR title.
        head: Source branch with the changes.
        base: Target branch (defaults to configured base branch).
        body: PR description.
    """
    base = base or cfg().github.default_base_branch
    async with _client() as c:
        resp = await c.post(
            f"{_repo_path()}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )
        resp.raise_for_status()
        pr = resp.json()
    return {"ok": True, "number": pr["number"], "url": pr["html_url"]}
