#!/usr/bin/env python3
"""
Basic Q&A Example

Demonstrates simple question-answering with the RAG pipeline.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def main():
    """Run basic Q&A example."""
    from src.orchestration.rag_pipeline import RAGPipeline
    from src.core.config_loader import load_config

    print("=" * 60)
    print("Basic RAG Q&A Example")
    print("=" * 60)

    # Load configuration
    config = load_config("config/rag_config_new.yaml")

    # Initialize pipeline
    print("\nInitializing RAG pipeline...")
    pipeline = RAGPipeline(config=config)

    # Display pipeline info
    print("\nPipeline Configuration:")
    info = pipeline.get_pipeline_info()
    for key, value in info.items():
        print(f"  {key}: {value}")

    # Ingest some sample documents
    print("\nIngesting sample documents...")
    sample_docs = [
        "The RAG (Retrieval-Augmented Generation) system combines retrieval and generation for accurate answers.",
        "Vector databases like Milvus store embeddings for efficient similarity search.",
        "Semantic chunking splits documents based on meaning rather than fixed size.",
        "Cross-encoder reranking improves relevance by scoring query-document pairs.",
        "CLaRa uses continuous latent representations for efficient document compression.",
    ]

    num_ingested = pipeline.ingest(sample_docs)
    print(f"Ingested {num_ingested} documents")

    # Ask questions
    questions = [
        "What is RAG?",
        "How does semantic chunking work?",
        "What is the purpose of reranking?",
    ]

    print("\n" + "=" * 60)
    print("Running Q&A")
    print("=" * 60)

    for question in questions:
        print(f"\nQuestion: {question}")
        print("-" * 40)

        result = pipeline.query(question, verbose=False)

        print(f"Answer: {result.answer}")
        print(f"Sources used: {len(result.sources)}")
        print(f"Latency: {result.total_latency_ms:.0f}ms")

    # Show memory stats
    print("\n" + "=" * 60)
    print("Session Statistics")
    print("=" * 60)
    stats = pipeline.get_memory_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
