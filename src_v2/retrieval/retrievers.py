"""Document retrieval with hybrid search and reranking."""

from langchain_classic.retrievers import EnsembleRetriever, ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.retrievers import BM25Retriever
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from src_v2.config.settings import settings


def get_retriever(vectorstore, documents=None, use_hybrid=None, use_rerank=None):
    if use_hybrid is None:
        use_hybrid = settings.use_hybrid_retrieval
    if use_rerank is None:
        use_rerank = settings.use_reranking

    dense_retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": settings.retrieval_top_k}
    )

    if use_hybrid and documents:
        bm25_retriever = BM25Retriever.from_documents(documents)
        bm25_retriever.k = settings.retrieval_top_k

        base_retriever = EnsembleRetriever(
            retrievers=[dense_retriever, bm25_retriever],
            weights=[0.5, 0.5]
        )
    else:
        base_retriever = dense_retriever

    if use_rerank:
        model = HuggingFaceCrossEncoder(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
        compressor = CrossEncoderReranker(model=model, top_n=settings.retrieval_top_k)
        return ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=base_retriever
        )

    return base_retriever
