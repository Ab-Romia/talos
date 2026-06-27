"""Jira Cloud REST v3 tools.

Plain async functions (module-level, typed, documented) so they register directly
into FastMCP and wrap cleanly as LangChain tools. The board/project come from
``cfg().jira`` so callers only pass what varies per call.
"""
import base64

import httpx

from config import cfg
from utils.logger import get_logger

logger = get_logger(__name__)


def _client() -> httpx.AsyncClient:
    jira = cfg().jira
    if jira is None:
        raise RuntimeError("Jira is not configured (set JIRA__* env vars).")

    token = base64.b64encode(
        f"{jira.email}:{jira.api_token.get_secret_value()}".encode()
    ).decode()
    return httpx.AsyncClient(
        base_url=jira.base_url.rstrip("/") + "/rest/api/3",
        headers={
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


def _adf(text: str) -> dict:
    """Wrap plain text in Atlassian Document Format (required for v3 bodies)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def jira_list_issues(jql: str | None = None, max_results: int = 20) -> list[dict]:
    """List Jira issues on the configured board/project.

    Args:
        jql: Optional JQL filter. Defaults to the configured project, newest first.
        max_results: Maximum number of issues to return (default 20).

    Returns a list of {key, summary, status} dicts.
    """
    jql = jql or f"project = {cfg().jira.project_key} ORDER BY created DESC"
    async with _client() as c:
        resp = await c.get(
            "/search/jql",
            params={"jql": jql, "maxResults": max_results, "fields": "summary,status"},
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
    return [
        {
            "key": i["key"],
            "summary": i["fields"]["summary"],
            "status": i["fields"]["status"]["name"],
        }
        for i in issues
    ]


async def jira_get_issue(issue_key: str) -> dict:
    """Fetch a single Jira issue's summary, description, status and comments.

    Args:
        issue_key: The issue key, e.g. "TAL-123".
    """
    async with _client() as c:
        resp = await c.get(
            f"/issue/{issue_key}",
            params={"fields": "summary,description,status,comment"},
        )
        resp.raise_for_status()
        f = resp.json()["fields"]
    return {
        "key": issue_key,
        "summary": f.get("summary"),
        "status": (f.get("status") or {}).get("name"),
        "description": f.get("description"),
        "comments": [
            {"author": (c.get("author") or {}).get("displayName"), "body": c.get("body")}
            for c in (f.get("comment") or {}).get("comments", [])
        ],
    }


async def jira_comment(issue_key: str, body: str) -> dict:
    """Add a comment to a Jira issue.

    Args:
        issue_key: The issue key, e.g. "TAL-123".
        body: Plain-text comment body.
    """
    async with _client() as c:
        resp = await c.post(f"/issue/{issue_key}/comment", json={"body": _adf(body)})
        resp.raise_for_status()
    return {"ok": True, "issue_key": issue_key}


async def jira_transition(issue_key: str, transition_name: str) -> dict:
    """Move a Jira issue to a new status by transition name (e.g. "In Progress", "Done").

    Args:
        issue_key: The issue key, e.g. "TAL-123".
        transition_name: Target transition name (case-insensitive).
    """
    async with _client() as c:
        resp = await c.get(f"/issue/{issue_key}/transitions")
        resp.raise_for_status()
        transitions = resp.json().get("transitions", [])
        match = next(
            (t for t in transitions if t["name"].lower() == transition_name.lower()),
            None,
        )
        if match is None:
            available = ", ".join(t["name"] for t in transitions)
            raise ValueError(
                f"No transition '{transition_name}' for {issue_key}. Available: {available}"
            )
        resp = await c.post(
            f"/issue/{issue_key}/transitions", json={"transition": {"id": match["id"]}}
        )
        resp.raise_for_status()
    return {"ok": True, "issue_key": issue_key, "status": transition_name}
