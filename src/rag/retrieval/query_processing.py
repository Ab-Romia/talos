from typing import override

from langchain_classic.chains.hyde.base import HypotheticalDocumentEmbedder
from langchain_classic.retrievers.multi_query import MultiQueryRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun as CallbackManager
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_openai import ChatOpenAI

from config import QUERY_REWRITE_PROMPT
from config import global_rag_config
from ..generation import get_llm
from ..vector_store import get_embeddings

__all__ = ["get_multiquery_retriever", "get_query_rewriter", "get_hyde_embeddings"]


class VerboseMultiQueryRetriever(MultiQueryRetriever):
    """Multi-query retriever that stores the last generated queries."""

    @override
    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManager):
        queries = self.generate_queries(query, run_manager)
        object.__setattr__(self, "last_generated_queries", queries)

        documents: list[Document] = []
        for q in queries:
            documents.extend(self.retriever.invoke(q))

        unique_docs: list[Document] = []
        seen_content: set[int] = set()
        for doc in documents:
            content_hash = hash(doc.page_content)
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_docs.append(doc)

        return unique_docs


def get_multiquery_retriever(base_retriever: BaseRetriever):
    return VerboseMultiQueryRetriever.from_llm(retriever=base_retriever, llm=get_llm())


# TODO: differentiate between query rewriter for retrieval vs generation
#  Use different llm/configs
def get_query_rewriter():
    llm = get_llm()
    return QUERY_REWRITE_PROMPT | llm


def get_hyde_embeddings():
    base_embeddings = get_embeddings()
    hyde_llm = ChatOpenAI(
        model="gpt-3.5-turbo",
        temperature=0.0,
        max_completion_tokens=150,
        api_key=global_rag_config.openai_api_key,
    )
    return HypotheticalDocumentEmbedder.from_llm(
        llm=hyde_llm, base_embeddings=base_embeddings, prompt_key="web_search"
    )
