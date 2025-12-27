from langchain_openai import ChatOpenAI
from src_v2.config.settings import settings


def get_llm(provider: str = "openai", streaming: bool | None = None):
    if streaming is None:
        streaming = settings.llm_streaming

    if provider == "openai":
        return ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.llm_temperature,
            streaming=streaming,
            openai_api_key=settings.openai_api_key
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
