from collections.abc import Iterable

from langchain_classic.retrievers import (
    EnsembleRetriever,
    ContextualCompressionRetriever,
)
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore

from model.config import RagConfig
from model.config import global_rag_config

__all__ = ["get_retriever"]


# TODO: instead of passing boolean flags, pass reranker and retriever
#  add more config options
def get_retriever(
        vectorstore: VectorStore,
        documents: Iterable[Document],
        config: RagConfig = global_rag_config,
):
    dense_retriever = vectorstore.as_retriever(
        search_type="similarity", search_kwargs={"k": config.retrieval_top_k}
    )

    if config.use_hybrid_retrieval and documents:
        bm25_retriever = BM25Retriever.from_documents(documents)
        bm25_retriever.k = config.retrieval_top_k

        base_retriever = EnsembleRetriever(
            retrievers=[dense_retriever, bm25_retriever], weights=[0.5, 0.5]
        )
    else:
        base_retriever = dense_retriever

    if config.use_reranking:
        # TODO: make async:
        model = HuggingFaceCrossEncoder(
            model_name="cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
        compressor = CrossEncoderReranker(model=model, top_n=config.retrieval_top_k)
        return ContextualCompressionRetriever(
            base_compressor=compressor, base_retriever=base_retriever
        )

    return base_retriever
