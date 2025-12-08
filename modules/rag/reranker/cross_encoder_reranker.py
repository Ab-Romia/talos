from sentence_transformers import CrossEncoder
from typing import List, Tuple
import numpy as np


class CrossEncoderReranker:
    """Reranks retrieved documents using a cross-encoder model"""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        Initialize the reranker with a cross-encoder model.

        Args:
            model_name: HuggingFace model name for the cross-encoder
        """
        print(f"Loading reranker model: {model_name}")
        self.model = CrossEncoder(model_name)
        print("Reranker model loaded successfully")

    def rerank(
        self,
        query: str,
        documents: List[Tuple[str, float]],
        top_n: int = 3
    ) -> List[Tuple[str, float]]:
        """
        Rerank documents based on relevance to query.

        Args:
            query: The search query
            documents: List of (document, score) tuples from retrieval
            top_n: Number of top documents to return after reranking

        Returns:
            List of (document, reranker_score) tuples, sorted by relevance
        """
        if not documents:
            return []

        # Extract just the document texts
        doc_texts = [doc for doc, _ in documents]

        # Create query-document pairs for cross-encoder
        pairs = [[query, doc] for doc in doc_texts]

        # Get relevance scores from cross-encoder
        scores = self.model.predict(pairs)

        # Combine documents with new scores
        reranked = list(zip(doc_texts, scores))

        # Sort by score (descending) and take top_n
        reranked.sort(key=lambda x: x[1], reverse=True)

        return reranked[:top_n]
