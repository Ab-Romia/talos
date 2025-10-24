import numpy as np
from openai import OpenAI
from typing import List, Tuple
from rank_bm25 import BM25Okapi
import re
import os


class HybridRetriever:
    """
    Hybrid retrieval combining dense (semantic) and sparse (BM25) search
    with Reciprocal Rank Fusion (RRF) for result combination.
    """

    def __init__(
        self,
        embedding_model: str = "text-embedding-3-small",
        dense_weight: float = 0.7,
        sparse_weight: float = 0.3,
        rrf_k: int = 20
    ):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")

        self.client = OpenAI(api_key=api_key)
        self.embedding_model = embedding_model
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        self.rrf_k = rrf_k

        self.knowledge_base = []
        self.embeddings = []
        self.bm25 = None
        self.tokenized_corpus = []

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text with proper handling of punctuation and stopwords."""
        text = text.lower()
        tokens = re.findall(r'\b\w+\b', text)
        return tokens

    def load_knowledge(self, file_path: str):
        """Load knowledge base and chunk it intelligently by sections."""
        # Clear any existing knowledge and embeddings first
        self.knowledge_base = []
        self.embeddings = []

        with open(file_path, 'r') as f:
            content = f.read()

        # Split by sections (## headers) for better context
        chunks = []
        current_chunk = []

        for line in content.split('\n'):
            if line.startswith('##') and current_chunk:
                # Save previous section
                chunk_text = '\n'.join(current_chunk).strip()
                if chunk_text:
                    chunks.append(chunk_text)
                current_chunk = [line]
            else:
                current_chunk.append(line)

        # Add the last chunk
        if current_chunk:
            chunk_text = '\n'.join(current_chunk).strip()
            if chunk_text:
                chunks.append(chunk_text)

        # If no sections found, fall back to paragraph chunking
        if len(chunks) < 2:
            paragraphs = content.split('\n\n')
            chunks = [p.strip() for p in paragraphs if p.strip()]

        self.knowledge_base = chunks
        print(f"Loaded {len(self.knowledge_base)} chunks from {file_path}")

        self.tokenized_corpus = [self._tokenize(doc) for doc in self.knowledge_base]
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        print("BM25 index created")

    def create_embeddings(self):
        """Create dense embeddings for knowledge base."""
        print("Creating dense embeddings...")
        for i, chunk in enumerate(self.knowledge_base):
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=chunk
            )
            embedding = response.data[0].embedding
            self.embeddings.append(embedding)

            if (i + 1) % 10 == 0:
                print(f"Processed {i + 1}/{len(self.knowledge_base)} chunks")

        self.embeddings = np.array(self.embeddings)
        print("Dense embeddings created")

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        method: str = "hybrid"
    ) -> List[Tuple[str, float]]:
        """
        Retrieve documents using specified method.
        """
        if method == "dense":
            return self._dense_retrieve(query, top_k)
        elif method == "sparse":
            return self._sparse_retrieve(query, top_k)
        else:
            return self._hybrid_retrieve(query, top_k)

    def _dense_retrieve(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        """Retrieve using dense embeddings."""
        response = self.client.embeddings.create(
            model=self.embedding_model,
            input=query
        )
        query_embedding = np.array(response.data[0].embedding)

        similarities = self._cosine_similarity(query_embedding, self.embeddings)
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            results.append((self.knowledge_base[idx], float(similarities[idx])))

        return results

    def _sparse_retrieve(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        """Retrieve using BM25 sparse search."""
        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((self.knowledge_base[idx], float(scores[idx])))

        if not results:
            for idx in top_indices:
                results.append((self.knowledge_base[idx], float(scores[idx])))

        return results

    def _hybrid_retrieve(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        """
        Retrieve using hybrid search with Reciprocal Rank Fusion.
        Retrieves larger pool from each method to ensure good coverage.
        """
        pool_size = min(max(top_k * 3, 15), len(self.knowledge_base))

        dense_results = self._dense_retrieve(query, pool_size)
        sparse_results = self._sparse_retrieve(query, pool_size)

        fused_scores = self._reciprocal_rank_fusion(
            dense_results,
            sparse_results
        )

        sorted_results = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

        return [(doc, score) for doc, score in sorted_results[:top_k]]

    def _reciprocal_rank_fusion(
        self,
        dense_results: List[Tuple[str, float]],
        sparse_results: List[Tuple[str, float]]
    ) -> dict:
        """
        Combine results using Reciprocal Rank Fusion (RRF).
        """
        fused_scores = {}

        for rank, (doc, _) in enumerate(dense_results):
            if doc not in fused_scores:
                fused_scores[doc] = 0
            fused_scores[doc] += self.dense_weight * (1 / (self.rrf_k + rank + 1))

        for rank, (doc, _) in enumerate(sparse_results):
            if doc not in fused_scores:
                fused_scores[doc] = 0
            fused_scores[doc] += self.sparse_weight * (1 / (self.rrf_k + rank + 1))

        return fused_scores

    def multi_query_retrieve(
        self,
        queries: List[str],
        top_k: int = 5,
        method: str = "hybrid"
    ) -> List[Tuple[str, float]]:
        """
        Retrieve using multiple query variations and fuse results.
        """
        all_results = []
        for query in queries:
            results = self.retrieve(query, top_k=top_k, method=method)
            all_results.append(results)

        fused_scores = {}
        for results in all_results:
            for rank, (doc, score) in enumerate(results):
                if doc not in fused_scores:
                    fused_scores[doc] = 0
                fused_scores[doc] += 1 / (self.rrf_k + rank + 1)

        sorted_results = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

        return [(doc, score) for doc, score in sorted_results[:top_k]]

    def retrieve_with_hyde(
        self,
        hypothetical_doc: str,
        original_query: str,
        top_k: int = 5
    ) -> List[Tuple[str, float]]:
        """
        Retrieve using HyDE - uses hypothetical document for dense search
        and original query for sparse search.
        """
        pool_size = min(max(top_k * 3, 15), len(self.knowledge_base))

        dense_results = self._dense_retrieve(hypothetical_doc, pool_size)
        sparse_results = self._sparse_retrieve(original_query, pool_size)

        fused_scores = self._reciprocal_rank_fusion(dense_results, sparse_results)

        sorted_results = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

        return [(doc, score) for doc, score in sorted_results[:top_k]]

    @staticmethod
    def _cosine_similarity(query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        """Compute cosine similarity between query and documents."""
        query_norm = np.linalg.norm(query_vec)
        doc_norms = np.linalg.norm(doc_vecs, axis=1)

        dot_products = np.dot(doc_vecs, query_vec)
        similarities = dot_products / (doc_norms * query_norm + 1e-10)

        return similarities

    def get_retrieval_stats(self) -> dict:
        """Get statistics about the retriever."""
        return {
            "num_documents": len(self.knowledge_base),
            "embedding_model": self.embedding_model,
            "dense_weight": self.dense_weight,
            "sparse_weight": self.sparse_weight,
            "rrf_k": self.rrf_k
        }
