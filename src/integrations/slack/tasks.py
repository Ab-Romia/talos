"""Offloaded Slack agent turn.

The events webhook must return within Slack's 3-second window, so it only enqueues
this task. Here on the worker we run the (slow) embedded agent and post the reply.
"""
from broker import broker
from integrations import agent
from integrations.slack import service
from utils.logger import get_logger

logger = get_logger(__name__)


@broker.task()
async def run_agent_turn(
    slack_user: str, channel: str, text: str, thread_ts: str | None = None
) -> None:
    """Run the embedded agent for one Slack message and reply in-thread."""
    talos_user = service.resolve_talos_user(slack_user)
    logger.info("Slack turn", slack_user=slack_user, talos_user=talos_user, channel=channel)

    try:
        reply = await agent.answer(text)
    except Exception:
        logger.exception("Agent turn failed")
        reply = "Sorry — something went wrong while handling that."

    await service.post_message(channel, reply, thread_ts=thread_ts)
