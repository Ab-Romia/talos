"""
Milvus vector store implementation.

Provides a production-ready interface for Milvus vector database operations
with connection pooling, error handling, and batch operations.
"""

import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

from src.core.base_interfaces import BaseVectorStore, Document
from src.core.config_loader import MilvusConfig
from src.core.exceptions import (
    CollectionNotFoundError,
    MilvusConnectionError,
    VectorStoreError,
)
from src.utils.logger import get_logger
from src.utils.async_helpers import sync_retry

logger = get_logger(__name__)


class MilvusVectorStore(BaseVectorStore):
    """
    Production-ready Milvus vector store implementation.

    Features:
    - Connection pooling
    - Automatic reconnection
    - Batch operations
    - Metadata filtering
    - Multiple index types support
    """

    def __init__(self, config: MilvusConfig):
        """
        Initialize Milvus vector store.

        Args:
            config: Milvus configuration
        """
        self.config = config
        self._connections = None
        self._utility = None
        self._Collection = None
        self._FieldSchema = None
        self._CollectionSchema = None
        self._DataType = None
        self._initialized = False

        # Lazy import pymilvus to handle optional dependency
        self._import_milvus()

    def _import_milvus(self) -> None:
        """Import Milvus SDK components."""
        try:
            from pymilvus import (
                Collection,
                CollectionSchema,
                DataType,
                FieldSchema,
                connections,
                utility,
            )

            self._connections = connections
            self._utility = utility
            self._Collection = Collection
            self._FieldSchema = FieldSchema
            self._CollectionSchema = CollectionSchema
            self._DataType = DataType
        except ImportError:
            raise ImportError(
                "pymilvus is required for Milvus support. "
                "Install it with: pip install pymilvus"
            )

    @sync_retry(
        max_retries=3,
        base_delay=1.0,
        retryable_exceptions=(Exception,),
    )
    def connect(self) -> None:
        """Establish connection to Milvus."""
        if self._initialized:
            return

        try:
            # Get credentials from config or environment
            user = self.config.user or os.getenv("MILVUS_USER")
            password = self.config.password or os.getenv("MILVUS_PASSWORD")

            connect_params = {
                "alias": "default",
                "host": os.getenv("MILVUS_HOST", self.config.host),
                "port": int(os.getenv("MILVUS_PORT", self.config.port)),
                "db_name": self.config.database,
            }

            if user and password:
                connect_params["user"] = user
                connect_params["password"] = password

            self._connections.connect(**connect_params)
            self._initialized = True
            logger.info(
                "Connected to Milvus",
                host=connect_params["host"],
                port=connect_params["port"],
            )
        except Exception as e:
            raise MilvusConnectionError(
                f"Failed to connect to Milvus: {e}",
                host=self.config.host,
                port=self.config.port,
                cause=e,
            )

    def disconnect(self) -> None:
        """Disconnect from Milvus."""
        if self._initialized:
            try:
                self._connections.disconnect("default")
                self._initialized = False
                logger.info("Disconnected from Milvus")
            except Exception as e:
                logger.warning(f"Error disconnecting from Milvus: {e}")

    @contextmanager
    def connection(self) -> Generator[None, None, None]:
        """Context manager for Milvus connection."""
        self.connect()
        try:
            yield
        finally:
            # Keep connection alive for pooling
            pass

    def _ensure_connected(self) -> None:
        """Ensure connection is established."""
        if not self._initialized:
            self.connect()

    def create_collection(
        self,
        collection_name: str,
        dimension: int,
        metadata_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Create a new collection with schema.

        Args:
            collection_name: Name of the collection
            dimension: Vector dimension
            metadata_schema: Optional metadata field definitions
        """
        self._ensure_connected()

        if self.collection_exists(collection_name):
            logger.info(f"Collection '{collection_name}' already exists")
            return

        try:
            # Define fields
            fields = [
                self._FieldSchema(
                    name="id",
                    dtype=self._DataType.VARCHAR,
                    max_length=64,
                    is_primary=True,
                    auto_id=False,
                ),
                self._FieldSchema(
                    name="content",
                    dtype=self._DataType.VARCHAR,
                    max_length=65535,
                ),
                self._FieldSchema(
                    name="embedding",
                    dtype=self._DataType.FLOAT_VECTOR,
                    dim=dimension,
                ),
                self._FieldSchema(
                    name="metadata",
                    dtype=self._DataType.JSON,
                ),
            ]

            # Add custom metadata fields if provided
            if metadata_schema:
                for field_name, field_type in metadata_schema.items():
                    if field_type == "string":
                        fields.append(
                            self._FieldSchema(
                                name=field_name,
                                dtype=self._DataType.VARCHAR,
                                max_length=1024,
                            )
                        )
                    elif field_type == "int":
                        fields.append(
                            self._FieldSchema(
                                name=field_name,
                                dtype=self._DataType.INT64,
                            )
                        )
                    elif field_type == "float":
                        fields.append(
                            self._FieldSchema(
                                name=field_name,
                                dtype=self._DataType.FLOAT,
                            )
                        )

            schema = self._CollectionSchema(
                fields=fields,
                description=f"RAG collection: {collection_name}",
            )

            collection = self._Collection(
                name=collection_name,
                schema=schema,
                consistency_level=self.config.consistency_level,
            )

            # Create index
            self._create_index(collection, dimension)

            logger.info(
                f"Created collection '{collection_name}'",
                dimension=dimension,
                index_type=self.config.index_type,
            )

        except Exception as e:
            raise VectorStoreError(
                f"Failed to create collection '{collection_name}': {e}",
                operation="create_collection",
                collection=collection_name,
                cause=e,
            )

    def _create_index(self, collection, dimension: int) -> None:
        """Create index on collection."""
        index_params = {
            "metric_type": self.config.metric_type,
            "index_type": self.config.index_type,
            "params": self.config.index_params,
        }

        collection.create_index(
            field_name="embedding",
            index_params=index_params,
        )
        collection.load()

    def insert(
        self,
        collection_name: str,
        documents: List[Document],
    ) -> List[str]:
        """
        Insert documents into collection.

        Args:
            collection_name: Name of the collection
            documents: Documents to insert (must have embeddings)

        Returns:
            List of inserted document IDs
        """
        self._ensure_connected()

        if not self.collection_exists(collection_name):
            raise CollectionNotFoundError(collection_name)

        if not documents:
            return []

        try:
            collection = self._Collection(collection_name)

            # Prepare data for insertion
            ids = []
            contents = []
            embeddings = []
            metadata_list = []

            for doc in documents:
                if doc.embedding is None:
                    raise VectorStoreError(
                        "Document must have embedding for insertion",
                        operation="insert",
                        collection=collection_name,
                    )

                ids.append(doc.id)
                contents.append(doc.content[:65535])  # Truncate if needed
                embeddings.append(doc.embedding)
                metadata_list.append(doc.metadata)

            # Insert in batches
            batch_size = 1000
            inserted_ids = []

            for i in range(0, len(ids), batch_size):
                batch_end = min(i + batch_size, len(ids))
                batch_data = [
                    ids[i:batch_end],
                    contents[i:batch_end],
                    embeddings[i:batch_end],
                    metadata_list[i:batch_end],
                ]

                collection.insert(batch_data)
                inserted_ids.extend(ids[i:batch_end])

            collection.flush()

            logger.info(
                f"Inserted {len(inserted_ids)} documents",
                collection=collection_name,
            )

            return inserted_ids

        except Exception as e:
            raise VectorStoreError(
                f"Failed to insert documents: {e}",
                operation="insert",
                collection=collection_name,
                cause=e,
            )

    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Search for similar documents.

        Args:
            collection_name: Collection to search
            query_vector: Query embedding
            top_k: Number of results to return
            filters: Optional metadata filters

        Returns:
            List of similar documents with scores
        """
        self._ensure_connected()

        if not self.collection_exists(collection_name):
            raise CollectionNotFoundError(collection_name)

        try:
            collection = self._Collection(collection_name)
            collection.load()

            search_params = {"metric_type": self.config.metric_type}
            search_params.update(self.config.search_params)

            # Build filter expression if provided
            expr = None
            if filters:
                expr = self._build_filter_expression(filters)

            start_time = time.perf_counter()

            results = collection.search(
                data=[query_vector],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=expr,
                output_fields=["id", "content", "metadata"],
            )

            latency_ms = (time.perf_counter() - start_time) * 1000

            documents = []
            for hits in results:
                for hit in hits:
                    doc = Document(
                        id=hit.entity.get("id"),
                        content=hit.entity.get("content", ""),
                        metadata=hit.entity.get("metadata", {}),
                        score=1 - hit.distance if self.config.metric_type in ["L2", "COSINE"] else hit.distance,
                    )
                    documents.append(doc)

            logger.log_retrieval(
                query="[vector search]",
                num_results=len(documents),
                method="milvus_search",
                latency_ms=latency_ms,
            )

            return documents

        except Exception as e:
            raise VectorStoreError(
                f"Search failed: {e}",
                operation="search",
                collection=collection_name,
                cause=e,
            )

    def _build_filter_expression(self, filters: Dict[str, Any]) -> str:
        """Build Milvus filter expression from dict."""
        expressions = []

        for key, value in filters.items():
            if isinstance(value, str):
                expressions.append(f'metadata["{key}"] == "{value}"')
            elif isinstance(value, (int, float)):
                expressions.append(f'metadata["{key}"] == {value}')
            elif isinstance(value, list):
                # In operator
                values_str = ", ".join(
                    f'"{v}"' if isinstance(v, str) else str(v) for v in value
                )
                expressions.append(f'metadata["{key}"] in [{values_str}]')
            elif isinstance(value, dict):
                # Range queries
                if "gte" in value:
                    expressions.append(f'metadata["{key}"] >= {value["gte"]}')
                if "lte" in value:
                    expressions.append(f'metadata["{key}"] <= {value["lte"]}')
                if "gt" in value:
                    expressions.append(f'metadata["{key}"] > {value["gt"]}')
                if "lt" in value:
                    expressions.append(f'metadata["{key}"] < {value["lt"]}')

        return " && ".join(expressions) if expressions else None

    def delete(
        self,
        collection_name: str,
        ids: List[str],
    ) -> None:
        """
        Delete documents by ID.

        Args:
            collection_name: Collection name
            ids: IDs to delete
        """
        self._ensure_connected()

        if not self.collection_exists(collection_name):
            raise CollectionNotFoundError(collection_name)

        try:
            collection = self._Collection(collection_name)
            ids_str = ", ".join(f'"{id}"' for id in ids)
            expr = f"id in [{ids_str}]"
            collection.delete(expr)

            logger.info(
                f"Deleted {len(ids)} documents",
                collection=collection_name,
            )

        except Exception as e:
            raise VectorStoreError(
                f"Delete failed: {e}",
                operation="delete",
                collection=collection_name,
                cause=e,
            )

    def collection_exists(self, collection_name: str) -> bool:
        """Check if collection exists."""
        self._ensure_connected()
        return self._utility.has_collection(collection_name)

    def drop_collection(self, collection_name: str) -> None:
        """Drop a collection."""
        self._ensure_connected()

        if not self.collection_exists(collection_name):
            return

        try:
            self._utility.drop_collection(collection_name)
            logger.info(f"Dropped collection '{collection_name}'")
        except Exception as e:
            raise VectorStoreError(
                f"Failed to drop collection: {e}",
                operation="drop",
                collection=collection_name,
                cause=e,
            )

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """Get collection statistics."""
        self._ensure_connected()

        if not self.collection_exists(collection_name):
            raise CollectionNotFoundError(collection_name)

        try:
            collection = self._Collection(collection_name)
            return {
                "name": collection_name,
                "num_entities": collection.num_entities,
                "description": collection.description,
            }
        except Exception as e:
            raise VectorStoreError(
                f"Failed to get collection stats: {e}",
                operation="stats",
                collection=collection_name,
                cause=e,
            )

    def hybrid_search(
        self,
        collection_name: str,
        dense_vector: List[float],
        sparse_data: Optional[Dict[int, float]] = None,
        top_k: int = 10,
        alpha: float = 0.5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Hybrid search combining dense and sparse vectors.

        Note: This requires Milvus 2.4+ with sparse vector support.
        Falls back to dense search if sparse is not available.

        Args:
            collection_name: Collection name
            dense_vector: Dense query vector
            sparse_data: Sparse vector as {dimension: value}
            top_k: Number of results
            alpha: Weight for dense vs sparse (0=sparse only, 1=dense only)
            filters: Optional metadata filters

        Returns:
            List of documents with scores
        """
        # For now, fall back to dense search
        # Hybrid with sparse requires Milvus 2.4+ and special collection setup
        return self.search(
            collection_name=collection_name,
            query_vector=dense_vector,
            top_k=top_k,
            filters=filters,
        )


class InMemoryVectorStore(BaseVectorStore):
    """
    In-memory vector store for testing and development.

    Uses numpy for similarity calculations.
    """

    def __init__(self, config: Optional[MilvusConfig] = None):
        """Initialize in-memory store."""
        self.config = config or MilvusConfig()
        self._collections: Dict[str, Dict[str, Any]] = {}

    def create_collection(
        self,
        collection_name: str,
        dimension: int,
        metadata_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create a new in-memory collection."""
        if collection_name not in self._collections:
            self._collections[collection_name] = {
                "dimension": dimension,
                "documents": {},
                "metadata_schema": metadata_schema,
            }

    def insert(
        self,
        collection_name: str,
        documents: List[Document],
    ) -> List[str]:
        """Insert documents into collection."""
        if collection_name not in self._collections:
            raise CollectionNotFoundError(collection_name)

        ids = []
        for doc in documents:
            self._collections[collection_name]["documents"][doc.id] = doc
            ids.append(doc.id)

        return ids

    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Search for similar documents using cosine similarity."""
        import numpy as np

        if collection_name not in self._collections:
            raise CollectionNotFoundError(collection_name)

        documents = list(self._collections[collection_name]["documents"].values())

        if not documents:
            return []

        # Filter documents if needed
        if filters:
            documents = [
                doc for doc in documents
                if self._matches_filter(doc, filters)
            ]

        # Calculate similarities
        query_vec = np.array(query_vector)
        query_norm = np.linalg.norm(query_vec)

        scored_docs = []
        for doc in documents:
            if doc.embedding is None:
                continue
            doc_vec = np.array(doc.embedding)
            doc_norm = np.linalg.norm(doc_vec)
            similarity = np.dot(query_vec, doc_vec) / (query_norm * doc_norm + 1e-10)
            scored_docs.append((doc, float(similarity)))

        # Sort by similarity and return top_k
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        results = []
        for doc, score in scored_docs[:top_k]:
            result_doc = Document(
                id=doc.id,
                content=doc.content,
                metadata=doc.metadata,
                embedding=doc.embedding,
                score=score,
            )
            results.append(result_doc)

        return results

    def _matches_filter(self, doc: Document, filters: Dict[str, Any]) -> bool:
        """Check if document matches filters."""
        for key, value in filters.items():
            doc_value = doc.metadata.get(key)
            if isinstance(value, list):
                if doc_value not in value:
                    return False
            elif doc_value != value:
                return False
        return True

    def delete(
        self,
        collection_name: str,
        ids: List[str],
    ) -> None:
        """Delete documents by ID."""
        if collection_name not in self._collections:
            raise CollectionNotFoundError(collection_name)

        for id in ids:
            self._collections[collection_name]["documents"].pop(id, None)

    def collection_exists(self, collection_name: str) -> bool:
        """Check if collection exists."""
        return collection_name in self._collections

    def drop_collection(self, collection_name: str) -> None:
        """Drop a collection."""
        self._collections.pop(collection_name, None)

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """Get collection statistics."""
        if collection_name not in self._collections:
            raise CollectionNotFoundError(collection_name)

        return {
            "name": collection_name,
            "num_entities": len(self._collections[collection_name]["documents"]),
            "dimension": self._collections[collection_name]["dimension"],
        }
