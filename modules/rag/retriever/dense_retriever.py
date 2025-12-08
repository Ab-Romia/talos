import numpy as np
from openai import OpenAI
from typing import List, Tuple
import os


class DenseRetriever:
    def __init__(self, embedding_model: str = "text-embedding-3-small"):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")

        self.client = OpenAI(api_key=api_key)
        self.embedding_model = embedding_model
        self.knowledge_base = []
        self.embeddings = []

    def load_knowledge(self, file_path: str):
        with open(file_path, 'r') as f:
            self.knowledge_base = [line.strip() for line in f if line.strip()]
        print(f"Loaded {len(self.knowledge_base)} chunks from {file_path}")

    def create_embeddings(self):
        print("Creating embeddings for knowledge base...")
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
        print("Embeddings created successfully")

    def retrieve(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
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

    @staticmethod
    def _cosine_similarity(query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        query_norm = np.linalg.norm(query_vec)
        doc_norms = np.linalg.norm(doc_vecs, axis=1)

        dot_products = np.dot(doc_vecs, query_vec)
        similarities = dot_products / (doc_norms * query_norm)

        return similarities
