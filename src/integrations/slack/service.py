"""Slack-side helpers: identity mapping and outbound messages.

Owns its own ``AsyncWebClient`` (built from config) so it doesn't depend on the bolt
app — the worker process posts replies through here without importing the HTTP app.
"""
import httpx
from slack_sdk.web.async_client import AsyncWebClient

from config import cfg
from utils.logger import get_logger

logger = get_logger(__name__)

_client: AsyncWebClient | None = None


def _web() -> AsyncWebClient:
    global _client
    if _client is None:
        _client = AsyncWebClient(token=cfg().slack.bot_token.get_secret_value())
    return _client


def resolve_talos_user(slack_user_id: str) -> str:
    """Map a Slack user id to a Talos user uuid (config map, with a default fallback)."""
    slack = cfg().slack
    return slack.user_map.get(slack_user_id, slack.default_talos_user_id)


async def post_message(channel: str, text: str, thread_ts: str | None = None) -> None:
    """Post a reply back to Slack."""
    await _web().chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)


async def fetch_thread(channel: str, thread_ts: str, limit: int = 20) -> list[dict]:
    """Fetch the messages of a Slack thread (oldest first).

    Needs the ``channels:history`` scope for channel threads (``im:history``
    covers DMs). Returns [] when history is unavailable so the agent turn
    still runs, just without context.
    """
    try:
        resp = await _web().conversations_replies(
            channel=channel, ts=thread_ts, limit=limit
        )
        return resp.get("messages") or []
    except Exception:
        logger.exception("Could not fetch Slack thread history", channel=channel)
        return []


async def fetch_channel_history(channel: str, limit: int = 15) -> list[dict]:
    """Recent top-level messages of a channel, oldest first.

    Used to give the agent context on top-level mentions (which have no
    thread of their own). Same ``channels:history`` scope as threads.
    """
    try:
        resp = await _web().conversations_history(channel=channel, limit=limit)
        return list(reversed(resp.get("messages") or []))  # newest-first -> oldest-first
    except Exception:
        logger.exception("Could not fetch Slack channel history", channel=channel)
        return []


async def download_file(url: str) -> bytes:
    """Download a Slack-hosted file. ``url_private*`` URLs require the bot token."""
    headers = {"Authorization": f"Bearer {cfg().slack.bot_token.get_secret_value()}"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.content
