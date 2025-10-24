"""
Retriever Module

Handles document retrieval using various strategies:
- Sparse retrieval (BM25, TF-IDF)
- Dense retrieval (embeddings + FAISS)
- Hybrid retrieval
"""

from .dense_retriever import DenseRetriever
from .hybrid_retriever import HybridRetriever

__all__ = ['DenseRetriever', 'HybridRetriever']