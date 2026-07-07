"""Embedded LangChain agent that powers the Slack bot.

Minimal tool-calling loop built on ``llm.bind_tools`` (langchain-openai / core only —
no langgraph dependency). Reuses the existing OpenAI config via ``get_llm`` and binds
the Talos tools from the shared registry.
"""
import asyncio

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from integrations.tools import AGENT_TOOLS
from rag.generation import get_llm
from utils.logger import get_logger

logger = get_logger(__name__)

_SYSTEM = (
    "You are Talos, a helpful assistant operating inside a Slack workspace. "
    "Use the available tools to answer questions about the team's documents "
    "(rag_ask), read or post channel messages, and list files. "
    "Prefer rag_ask for any question that may be answered by uploaded documents, "
    "and cite the sources it returns. Keep replies concise and Slack-friendly."
)

_MAX_STEPS = 5
_TOOLS_BY_NAME = {fn.__name__: fn for fn in AGENT_TOOLS}

_llm_with_tools = None


def _llm():
    global _llm_with_tools
    if _llm_with_tools is None:
        # bind_tools infers each tool's schema from its type hints + docstring.
        _llm_with_tools = get_llm(streaming=False).bind_tools(AGENT_TOOLS)
    return _llm_with_tools


async def answer(text: str) -> str:
    """Run one agent turn over ``text`` and return the final reply."""
    messages = [SystemMessage(_SYSTEM), HumanMessage(text)]

    for _ in range(_MAX_STEPS):
        response = await _llm().ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return response.content or ""

        for call in response.tool_calls:
            fn = _TOOLS_BY_NAME.get(call["name"])
            try:
                if fn is None:
                    raise ValueError(f"Unknown tool: {call['name']}")
                result = fn(**call["args"])
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as exc:  # surface tool errors back to the model
                logger.exception("Tool failed", tool=call["name"])
                result = f"ERROR: {exc}"
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    return "Sorry, I couldn't complete that request."
