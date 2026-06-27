"""Slack bolt app + FastAPI adapter.

Built only when Slack is configured, so the main app still boots without it. Event
listeners do the minimum (enqueue a task) and return, to satisfy Slack's 3s ack.
"""
import re

from config import cfg
from utils.logger import get_logger

logger = get_logger(__name__)

_MENTION = re.compile(r"<@[^>]+>\s*")

bolt_app = None
slack_handler = None


def _build():
    """Construct the bolt app + FastAPI handler. Returns (app, handler) or (None, None)."""
    if cfg().slack is None:
        logger.info("Slack not configured; skipping bolt app.")
        return None, None

    from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
    from slack_bolt.async_app import AsyncApp

    from integrations.slack import tasks

    app = AsyncApp(
        token=cfg().slack.bot_token.get_secret_value(),
        signing_secret=cfg().slack.signing_secret.get_secret_value(),
        process_before_response=True,
    )

    async def _enqueue(event: dict) -> None:
        text = _MENTION.sub("", event.get("text", "")).strip()
        if not text:
            return
        await tasks.run_agent_turn.kiq(
            slack_user=event.get("user", ""),
            channel=event["channel"],
            text=text,
            thread_ts=event.get("thread_ts") or event.get("ts"),
        )

    @app.event("app_mention")
    async def on_mention(event):
        await _enqueue(event)

    @app.event("message")
    async def on_message(event):
        # Only direct messages, and never react to bot/own messages (avoids loops).
        if event.get("channel_type") != "im" or event.get("bot_id"):
            return
        await _enqueue(event)

    return app, AsyncSlackRequestHandler(app)


bolt_app, slack_handler = _build()
