from typing import override

from langchain_core.chat_history import (
    InMemoryChatMessageHistory,
    BaseChatMessageHistory,
)
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from config import global_rag_config, RagConfig

__all__ = ["get_llm", "get_memory"]


def get_llm(provider: str = "openai", streaming: bool | None = None,
            config: RagConfig = global_rag_config):
    if streaming is None:
        streaming = config.llm_streaming

    if provider == "openai":
        return ChatOpenAI(
            model=config.openai_model,
            temperature=config.llm_temperature,
            streaming=streaming,
            api_key=config.openai_api_key,
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
