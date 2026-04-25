from typing import override

from langchain_core.chat_history import (
    InMemoryChatMessageHistory,
    BaseChatMessageHistory,
)
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from config import RagConfig, get_effective_rag_config

__all__ = ["get_llm", "get_memory"]


def get_llm(
    config: RagConfig | None = None,
    provider: str = "openai",
    streaming: bool | None = None,
):
    c = config or get_effective_rag_config()
    if streaming is None:
        streaming = c.llm_streaming

    if provider == "openai":
        return ChatOpenAI(
            model=c.openai_model,
            temperature=c.llm_temperature,
            streaming=streaming,
            api_key=c.openai_api_key,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


class NullHistory(BaseChatMessageHistory):
    """A chat message history that does not store any messages."""

    @override
    def add_message(self, message: BaseMessage) -> None:
        pass

    @override
    def clear(self) -> None:
        pass


def get_memory(use_memory: bool = True) -> BaseChatMessageHistory:
    """
    Get chat message history memory.

    :param use_memory: Whether to use in-memory chat history or null history.
    :return: Chat message history instance.
    """
    if use_memory:
        return InMemoryChatMessageHistory()
    else:
        return NullHistory()
