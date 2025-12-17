#!/usr/bin/env python3
"""
Document Ingestion Example

Demonstrates how to ingest documents from files and directories.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def main():
    """Run document ingestion example."""
    from src.core.config_loader import load_config
    from src.core.base_interfaces import Document
    from src.indexing.milvus_manager import InMemoryVectorStore
    from src.indexing.embedding_service import create_embedding_service
    from src.ingestion.document_loaders import TextLoader, MarkdownLoader, DirectoryLoader
    from src.ingestion.chunking_strategies import create_chunker
    from src.ingestion.pipeline import IngestionPipeline

    print("=" * 60)
    print("Document Ingestion Example")
    print("=" * 60)

    # Load configuration
    config = load_config("config/rag_config_new.yaml")

    # Initialize components
    print("\nInitializing components...")

    embedding_service = create_embedding_service(config.embedding)
    vector_store = InMemoryVectorStore()

    # Create chunker (semantic chunking for best results)
    chunker = create_chunker(
        config.chunking,
        embedding_service if config.chunking.strategy == "semantic" else None,
    )

    print(f"Chunking strategy: {config.chunking.strategy}")
    print(f"Chunk size: {config.chunking.chunk_size}")
    print(f"Chunk overlap: {config.chunking.chunk_overlap}")

    # Create ingestion pipeline
    pipeline = IngestionPipeline(
        config=config,
        vector_store=vector_store,
        embedding_service=embedding_service,
        chunker=chunker,
    )

    # Example 1: Ingest raw texts
    print("\n" + "-" * 40)
    print("Example 1: Ingesting raw texts")
    print("-" * 40)

    texts = [
        """
        Machine Learning is a subset of artificial intelligence that enables
        systems to learn and improve from experience without being explicitly
        programmed. It focuses on developing algorithms that can access data
        and use it to learn for themselves.
        """,
        """
        Deep Learning is a subset of machine learning based on artificial
        neural networks. The learning process is called deep because the
        structure of neural networks consists of multiple input, output,
        and hidden layers.
        """,
    ]

    stats = pipeline.ingest_texts(
        texts=texts,
        metadata_list=[{"topic": "ML"}, {"topic": "DL"}],
        collection_name="example_collection",
    )

    print(f"Ingested {stats['documents_indexed']} chunks")
    print(f"Processing time: {stats['elapsed_seconds']:.2f}s")

    # Example 2: Using document loaders
    print("\n" + "-" * 40)
    print("Example 2: Using document loaders")
    print("-" * 40)

    # Create a sample text file
    sample_file = Path("/tmp/sample_doc.txt")
    sample_file.write_text("""
# Sample Document

This is a sample document for demonstrating the document loader.

## Section 1: Introduction

The document loader supports various file formats including
text files, markdown files, PDFs, and JSON files.

## Section 2: Features

- Multi-format support
- Automatic chunking
- Metadata extraction
- Batch processing

## Conclusion

Document ingestion is a crucial part of RAG systems.
    """)

    # Load with TextLoader
    loader = TextLoader()
    docs = loader.load(str(sample_file))
    print(f"Loaded {len(docs)} document(s)")

    # Chunk the documents
    chunked_docs = chunker.chunk_documents(docs)
    print(f"Created {len(chunked_docs)} chunk(s)")

    # Show chunks
    for i, chunk in enumerate(chunked_docs[:3]):  # Show first 3
        print(f"\nChunk {i + 1} ({len(chunk.content)} chars):")
        print(f"  {chunk.content[:100]}...")

    # Clean up
    sample_file.unlink()

    # Example 3: Directory loading
    print("\n" + "-" * 40)
    print("Example 3: Directory loader info")
    print("-" * 40)

    dir_loader = DirectoryLoader(glob_pattern="*.md", recursive=True)
    print(f"Supported extensions: {dir_loader.supported_extensions}")

    print("\nDone!")


if __name__ == "__main__":
    main()
