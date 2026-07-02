from langchain_classic.chains.hyde.base import HypotheticalDocumentEmbedder
from langchain_openai import ChatOpenAI

from config import QUERY_REWRITE_PROMPT
from config import global_rag_config
from ..generation import get_llm
from ..vector_store import get_embeddings

__all__ = ["get_query_rewriter", "get_hyde_embeddings"]


# TODO: differentiate between query rewriter for retrieval vs generation
#  Use different llm/configs
def get_query_rewriter(config=global_rag_config):
    llm = get_llm(config=config)
    return QUERY_REWRITE_PROMPT | llm


def get_hyde_embeddings(config=global_rag_config):
    base_embeddings = get_embeddings(config=config)
    hyde_llm = ChatOpenAI(
        model=config.openai_model,
        temperature=0.0,
        max_completion_tokens=150,
        api_key=config.openai_api_key,
    )
    return HypotheticalDocumentEmbedder.from_llm(
        llm=hyde_llm, base_embeddings=base_embeddings, prompt_key="web_search"
    )
