#!/usr/bin/env python3
"""
Advanced Retrieval Example

Demonstrates multi-stage retrieval with hybrid search and reranking.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def main():
    """Run advanced retrieval example."""
    from src.core.config_loader import load_config
    from src.core.base_interfaces import Document
    from src.indexing.milvus_manager import InMemoryVectorStore
    from src.indexing.embedding_service import create_embedding_service
    from src.retrieval.retrievers.dense_retriever import DenseRetriever
    from src.retrieval.retrievers.hybrid_retriever import HybridRetriever
    from src.retrieval.retrievers.reranker import CrossEncoderReranker

    print("=" * 60)
    print("Advanced Retrieval Example")
    print("=" * 60)

    # Load configuration
    config = load_config("config/rag_config_new.yaml")

    # Initialize components
    print("\nInitializing components...")

    embedding_service = create_embedding_service(config.embedding)
    vector_store = InMemoryVectorStore()

    # Create collection
    collection_name = "retrieval_example"
    vector_store.create_collection(
        collection_name=collection_name,
        dimension=embedding_service.get_dimension(),
    )

    # Create sample documents about different topics
    documents = [
        Document(
            content="Python is a high-level programming language known for its simplicity and readability. It supports multiple programming paradigms.",
            metadata={"topic": "programming", "language": "python"},
        ),
        Document(
            content="Machine learning models learn patterns from data to make predictions. Common algorithms include linear regression and neural networks.",
            metadata={"topic": "ml", "subtopic": "basics"},
        ),
        Document(
            content="Natural Language Processing (NLP) enables computers to understand and generate human language. It uses techniques like tokenization and embeddings.",
            metadata={"topic": "ml", "subtopic": "nlp"},
        ),
        Document(
            content="Vector databases store high-dimensional embeddings for efficient similarity search. Examples include Milvus, Pinecone, and Weaviate.",
            metadata={"topic": "databases", "type": "vector"},
        ),
        Document(
            content="RAG combines retrieval with generation to produce accurate, grounded responses. It first retrieves relevant documents then generates answers.",
            metadata={"topic": "ml", "subtopic": "rag"},
        ),
        Document(
            content="Docker containers package applications with their dependencies for consistent deployment across environments.",
            metadata={"topic": "devops", "tool": "docker"},
        ),
        Document(
            content="Cross-encoder rerankers score query-document pairs for more accurate relevance ranking than bi-encoders.",
            metadata={"topic": "ml", "subtopic": "retrieval"},
        ),
        Document(
            content="Semantic search finds documents based on meaning rather than exact keyword matching, using dense vector representations.",
            metadata={"topic": "ml", "subtopic": "search"},
        ),
    ]

    # Generate embeddings and insert
    print(f"\nIndexing {len(documents)} documents...")
    texts = [doc.content for doc in documents]
    embeddings = embedding_service.embed_documents(texts)

    for doc, embedding in zip(documents, embeddings):
        doc.embedding = embedding

    vector_store.insert(collection_name, documents)

    # Initialize retrievers
    dense_retriever = DenseRetriever(
        config=config.retriever,
        vector_store=vector_store,
        embedding_service=embedding_service,
        collection_name=collection_name,
    )

    hybrid_retriever = HybridRetriever(
        config=config.retriever,
        vector_store=vector_store,
        embedding_service=embedding_service,
        collection_name=collection_name,
        documents=documents,
    )

    # Initialize reranker
    reranker = CrossEncoderReranker(config.reranker)

    # Test queries
    queries = [
        "How does semantic search work?",
        "What is RAG and how does it improve AI responses?",
        "Explain vector databases",
    ]

    print("\n" + "=" * 60)
    print("Retrieval Comparison")
    print("=" * 60)

    for query in queries:
        print(f"\n{'=' * 60}")
        print(f"Query: {query}")
        print("=" * 60)

        # Dense retrieval
        print("\n--- Dense Retrieval ---")
        dense_result = dense_retriever.retrieve(query, top_k=5)
        for i, doc in enumerate(dense_result.documents[:3]):
            print(f"{i+1}. [Score: {doc.score:.3f}] {doc.content[:80]}...")

        # Hybrid retrieval
        print("\n--- Hybrid Retrieval (Dense + BM25) ---")
        hybrid_result = hybrid_retriever.retrieve(query, top_k=5)
        for i, doc in enumerate(hybrid_result.documents[:3]):
            print(f"{i+1}. [Score: {doc.score:.3f}] {doc.content[:80]}...")

        # With reranking
        print("\n--- After Cross-Encoder Reranking ---")
        reranked = reranker.rerank(query, hybrid_result.documents, top_n=3)
        for i, doc in enumerate(reranked):
            print(f"{i+1}. [Score: {doc.score:.3f}] {doc.content[:80]}...")

    print("\n" + "=" * 60)
    print("Retrieval Statistics")
    print("=" * 60)
    print(f"Dense retrieval latency: {dense_result.latency_ms:.0f}ms")
    print(f"Hybrid retrieval latency: {hybrid_result.latency_ms:.0f}ms")

    print("\nDone!")


if __name__ == "__main__":
    main()
