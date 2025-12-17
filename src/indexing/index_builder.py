"""
Index builder for creating and populating vector indexes.

Orchestrates document loading, chunking, embedding, and indexing.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.core.base_interfaces import BaseVectorStore, Document
from src.core.config_loader import RAGConfig
from src.core.exceptions import VectorStoreError
from src.indexing.embedding_service import EmbeddingService, create_embedding_service
from src.utils.logger import get_logger

logger = get_logger(__name__)


class IndexBuilder:
    """
    Builds and manages vector indexes.

    Handles the complete workflow from documents to indexed vectors.
    """

    def __init__(
        self,
        config: RAGConfig,
        vector_store: BaseVectorStore,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        """
        Initialize index builder.

        Args:
            config: RAG configuration
            vector_store: Vector store instance
            embedding_service: Optional embedding service (created from config if not provided)
        """
        self.config = config
        self.vector_store = vector_store
        self.embedding_service = embedding_service or create_embedding_service(
            config.embedding
        )

    def build_index(
        self,
        documents: List[Document],
        collection_name: Optional[str] = None,
        batch_size: int = 100,
    ) -> Dict[str, Any]:
        """
        Build index from documents.

        Args:
            documents: Documents to index
            collection_name: Collection name (uses config if not provided)
            batch_size: Batch size for processing

        Returns:
            Index statistics
        """
        collection_name = collection_name or self.config.milvus.collection_name
        start_time = time.perf_counter()

        # Create collection if needed
        if not self.vector_store.collection_exists(collection_name):
            self.vector_store.create_collection(
                collection_name=collection_name,
                dimension=self.embedding_service.get_dimension(),
            )

        # Process documents in batches
        total_indexed = 0
        total_documents = len(documents)

        logger.info(
            f"Starting indexing of {total_documents} documents",
            collection=collection_name,
        )

        for i in range(0, total_documents, batch_size):
            batch = documents[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_documents + batch_size - 1) // batch_size

            logger.info(
                f"Processing batch {batch_num}/{total_batches}",
                batch_size=len(batch),
            )

            # Generate embeddings for documents without them
            docs_needing_embeddings = [doc for doc in batch if doc.embedding is None]
            if docs_needing_embeddings:
                texts = [doc.content for doc in docs_needing_embeddings]
                embeddings = self.embedding_service.embed_documents(texts)

                for doc, embedding in zip(docs_needing_embeddings, embeddings):
                    doc.embedding = embedding

            # Insert into vector store
            try:
                self.vector_store.insert(collection_name, batch)
                total_indexed += len(batch)
            except VectorStoreError as e:
                logger.error(f"Failed to index batch: {e}")
                continue

        elapsed_time = time.perf_counter() - start_time

        stats = {
            "collection_name": collection_name,
            "total_documents": total_documents,
            "documents_indexed": total_indexed,
            "elapsed_seconds": round(elapsed_time, 2),
            "documents_per_second": round(total_indexed / elapsed_time, 2) if elapsed_time > 0 else 0,
        }

        logger.info(
            "Indexing completed",
            **stats,
        )

        return stats

    def add_documents(
        self,
        documents: List[Document],
        collection_name: Optional[str] = None,
    ) -> List[str]:
        """
        Add documents to existing index.

        Args:
            documents: Documents to add
            collection_name: Collection name

        Returns:
            List of inserted document IDs
        """
        collection_name = collection_name or self.config.milvus.collection_name

        if not self.vector_store.collection_exists(collection_name):
            raise VectorStoreError(
                f"Collection '{collection_name}' does not exist",
                operation="add_documents",
                collection=collection_name,
            )

        # Generate embeddings
        docs_needing_embeddings = [doc for doc in documents if doc.embedding is None]
        if docs_needing_embeddings:
            texts = [doc.content for doc in docs_needing_embeddings]
            embeddings = self.embedding_service.embed_documents(texts)

            for doc, embedding in zip(docs_needing_embeddings, embeddings):
                doc.embedding = embedding

        # Insert
        return self.vector_store.insert(collection_name, documents)

    def delete_documents(
        self,
        document_ids: List[str],
        collection_name: Optional[str] = None,
    ) -> None:
        """
        Delete documents from index.

        Args:
            document_ids: IDs of documents to delete
            collection_name: Collection name
        """
        collection_name = collection_name or self.config.milvus.collection_name
        self.vector_store.delete(collection_name, document_ids)

    def rebuild_index(
        self,
        documents: List[Document],
        collection_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Rebuild index from scratch.

        Drops existing collection and creates new one.

        Args:
            documents: Documents to index
            collection_name: Collection name

        Returns:
            Index statistics
        """
        collection_name = collection_name or self.config.milvus.collection_name

        # Drop existing collection
        if self.vector_store.collection_exists(collection_name):
            logger.info(f"Dropping existing collection '{collection_name}'")
            self.vector_store.drop_collection(collection_name)

        # Build new index
        return self.build_index(documents, collection_name)

    def get_index_stats(
        self,
        collection_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get index statistics.

        Args:
            collection_name: Collection name

        Returns:
            Index statistics
        """
        collection_name = collection_name or self.config.milvus.collection_name
        return self.vector_store.get_collection_stats(collection_name)
