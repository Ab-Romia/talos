from typing import override

from langchain_core.chat_history import (
    InMemoryChatMessageHistory,
    BaseChatMessageHistory,
)
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from src.config import global_rag_config

__all__ = ["get_llm", "get_memory"]


def get_llm(provider: str = "openai", streaming: bool | None = None):
    if streaming is None:
        streaming = global_rag_config.llm_streaming

    if provider == "openai":
        return ChatOpenAI(
            model=global_rag_config.openai_model,
            temperature=global_rag_config.llm_temperature,
            streaming=streaming,
            api_key=global_rag_config.openai_api_key,
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

    Args:
        use_memory (bool): Whether to use in-memory chat history.
    """

    if use_memory:
        return InMemoryChatMessageHistory()
    else:
        return NullHistory()
