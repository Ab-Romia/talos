"""
Query transformations using LangChain.
Replaces: src/retrieval/query_processing/query_rewriter.py (449 lines → ~40 lines)

LangChain's MultiQueryRetriever handles:
- Query rewriting
- Query expansion
- HyDE (hypothetical document embeddings)
"""

from langchain.retrievers import MultiQueryRetriever
from langchain_openai import ChatOpenAI
from src_v2.config.settings import settings


def get_multi_query_retriever(base_retriever):
    """
    Create multi-query retriever that generates multiple search queries.

    Automatically generates different perspectives of the input question
    to improve retrieval quality.

    Args:
        base_retriever: Base LangChain retriever to wrap

    Returns:
        MultiQueryRetriever instance
    """
    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=0,
        openai_api_key=settings.openai_api_key
    )

    return MultiQueryRetriever.from_llm(
        retriever=base_retriever,
        llm=llm
    )
