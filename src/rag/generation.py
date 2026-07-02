from langchain_openai import ChatOpenAI

from config import global_rag_config, RagConfig

__all__ = ["get_llm"]


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
