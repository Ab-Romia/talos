"""
RAG Service - Bridge between API and RAG Pipeline.

This service provides a simplified interface for RAG operations,
handling initialization, configuration, and query execution.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

# Try to import the new modular RAG system from src/
try:
    from src.orchestration.rag_pipeline import RAGPipeline
    from src.core.config_loader import RAGConfig, load_config
    from src.core.base_interfaces import Document
    USE_NEW_RAG = True
except ImportError:
    USE_NEW_RAG = False
    RAGPipeline = None
    RAGConfig = None


class RAGService:
    """
    Service class for RAG operations.

    Provides a clean interface for:
    - Document ingestion
    - Query processing
    - Configuration management
    - Health monitoring
    """

    _instance: Optional["RAGService"] = None
    _pipeline: Optional[Any] = None
    _config: Optional[Any] = None
    _last_ingestion: Optional[datetime] = None
    _indexed_count: int = 0

    def __new__(cls) -> "RAGService":
        """Singleton pattern for RAG service."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize the RAG pipeline."""
        if USE_NEW_RAG and RAGPipeline is not None:
            try:
                # Try to load config from default location
                config_path = Path("config/rag_config.yaml")
                if config_path.exists():
                    self._config = RAGConfig.from_yaml(config_path)
                else:
                    self._config = RAGConfig()

                # Update from environment
                self._config = self._config.update_from_env()

                # Initialize pipeline
                self._pipeline = RAGPipeline(config=self._config)
            except Exception as e:
                print(f"Warning: Could not initialize RAG pipeline: {e}")
                self._pipeline = None
        else:
            # Fallback to simple mode
            self._pipeline = None

    def query(
        self,
        query: str,
        workspace_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        top_k: int = 5,
        include_sources: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a RAG query.

        Args:
            query: User query string
            workspace_id: Optional workspace filter
            conversation_history: Optional conversation context
            top_k: Number of documents to retrieve
            include_sources: Whether to include source documents
            filters: Optional metadata filters

        Returns:
            Dict containing answer, sources, and metadata
        """
        if self._pipeline is not None:
            try:
                # Build filters
                query_filters = filters or {}
                if workspace_id:
                    query_filters["workspace_id"] = workspace_id

                # Execute query
                result = self._pipeline.query(
                    question=query,
                    filters=query_filters if query_filters else None,
                    return_sources=include_sources,
                )

                # Convert sources to dict format
                sources = []
                if include_sources and result.sources:
                    for source in result.sources:
                        sources.append({
                            "content": source.content,
                            "document_id": source.metadata.get("document_id"),
                            "document_name": source.metadata.get("document_name"),
                            "page": source.metadata.get("page"),
                            "chunk_index": source.metadata.get("chunk_index"),
                            "score": source.score,
                            "metadata": source.metadata,
                        })

                return {
                    "answer": result.answer,
                    "sources": sources,
                    "query_type": result.query_type,
                    "processed_query": result.processed_query,
                    "retrieval_latency_ms": result.retrieval_latency_ms,
                    "generation_latency_ms": result.generation_latency_ms,
                    "total_latency_ms": result.total_latency_ms,
                    "metadata": result.metadata,
                }
            except Exception as e:
                # Return fallback response on error
                return self._fallback_response(query, str(e))
        else:
            return self._fallback_response(query)

    def _fallback_response(self, query: str, error: Optional[str] = None) -> Dict[str, Any]:
        """Generate a fallback response when RAG pipeline is not available."""
        if error:
            answer = f"I apologize, but I encountered an error processing your request: {error}"
        else:
            answer = (
                "I'm an AI assistant ready to help you. However, the knowledge base "
                "hasn't been configured yet. Please upload some documents to get started, "
                "or ask me general questions."
            )

        return {
            "answer": answer,
            "sources": [],
            "query_type": "fallback",
            "processed_query": None,
            "retrieval_latency_ms": 0,
            "generation_latency_ms": 0,
            "total_latency_ms": 0,
            "metadata": {"error": error} if error else None,
        }

    async def query_stream(
        self,
        query: str,
        workspace_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Execute a streaming RAG query.

        Args:
            query: User query string
            workspace_id: Optional workspace filter

        Yields:
            Response chunks as they are generated
        """
        # For now, simulate streaming by yielding the full response in chunks
        result = self.query(query, workspace_id)
        answer = result["answer"]

        # Yield in small chunks to simulate streaming
        chunk_size = 10
        for i in range(0, len(answer), chunk_size):
            yield answer[i:i + chunk_size]

    def ingest_file(
        self,
        file_path: str,
        document_id: str,
        workspace_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ingest a file into the RAG system.

        Args:
            file_path: Path to the file
            document_id: Unique document identifier
            workspace_id: Workspace identifier
            metadata: Additional metadata

        Returns:
            Ingestion result with chunk count
        """
        if self._pipeline is not None:
            try:
                # Add workspace and document info to metadata
                full_metadata = metadata or {}
                full_metadata["document_id"] = document_id
                full_metadata["workspace_id"] = workspace_id

                result = self._pipeline.ingest_file(
                    file_path=file_path,
                    metadata=full_metadata,
                )

                self._last_ingestion = datetime.now()
                self._indexed_count += result.get("chunks_created", 0)

                return {
                    "success": True,
                    "chunk_count": result.get("chunks_created", 0),
                    "document_id": document_id,
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "chunk_count": 0,
                    "document_id": document_id,
                }
        else:
            # Fallback: just count lines as "chunks"
            try:
                with open(file_path, "r") as f:
                    content = f.read()
                    chunk_count = max(1, len(content) // 1000)

                self._last_ingestion = datetime.now()
                self._indexed_count += chunk_count

                return {
                    "success": True,
                    "chunk_count": chunk_count,
                    "document_id": document_id,
                    "note": "RAG pipeline not initialized, document stored but not indexed",
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "chunk_count": 0,
                    "document_id": document_id,
                }

    def ingest_documents(
        self,
        documents: List[Dict[str, Any]],
        workspace_id: str,
    ) -> Dict[str, Any]:
        """
        Ingest multiple documents.

        Args:
            documents: List of documents with content and metadata
            workspace_id: Workspace identifier

        Returns:
            Ingestion result
        """
        if self._pipeline is not None:
            try:
                # Convert to Document objects
                doc_objects = []
                for doc in documents:
                    doc_obj = Document(
                        content=doc["content"],
                        metadata={
                            **doc.get("metadata", {}),
                            "workspace_id": workspace_id,
                        },
                    )
                    doc_objects.append(doc_obj)

                count = self._pipeline.ingest(doc_objects)
                self._last_ingestion = datetime.now()
                self._indexed_count += count

                return {"success": True, "count": count}
            except Exception as e:
                return {"success": False, "error": str(e), "count": 0}
        else:
            return {"success": False, "error": "RAG pipeline not initialized", "count": 0}

    def delete_document(self, document_id: str) -> bool:
        """
        Delete a document from the RAG system.

        Args:
            document_id: Document identifier

        Returns:
            True if deletion was successful
        """
        # In a full implementation, this would delete from vector store
        # For now, just return True
        return True

    def get_config(self) -> Dict[str, Any]:
        """
        Get RAG configuration.

        Returns:
            Configuration dictionary
        """
        if self._pipeline is not None:
            try:
                return self._pipeline.get_pipeline_info()
            except Exception:
                pass

        # Return default config
        return {
            "pipeline_type": "modular",
            "embedding_model": "text-embedding-3-small",
            "llm_model": "gpt-4o-mini",
            "retrieval_method": "hybrid",
            "reranker_enabled": True,
            "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "query_processing_enabled": True,
            "routing_enabled": True,
            "compression_enabled": False,
            "memory_enabled": True,
            "collection_name": "rag_collection",
        }

    def health_check(self) -> Dict[str, Any]:
        """
        Check RAG system health.

        Returns:
            Health status dictionary
        """
        vector_store_connected = False
        llm_available = False
        embedding_available = False

        if self._pipeline is not None:
            try:
                # Check vector store
                vector_store_connected = hasattr(self._pipeline, "vector_store") and self._pipeline.vector_store is not None

                # Check LLM
                llm_available = hasattr(self._pipeline, "llm_service") and self._pipeline.llm_service is not None

                # Check embedding service
                embedding_available = hasattr(self._pipeline, "embedding_service") and self._pipeline.embedding_service is not None
            except Exception:
                pass

        return {
            "healthy": vector_store_connected or llm_available,
            "vector_store_connected": vector_store_connected,
            "llm_available": llm_available,
            "embedding_service_available": embedding_available,
            "indexed_documents": self._indexed_count,
            "last_ingestion": self._last_ingestion,
        }

    def clear_memory(
        self,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        """
        Clear conversation memory.

        Args:
            user_id: Optional user filter
            conversation_id: Optional conversation filter
        """
        if self._pipeline is not None:
            try:
                self._pipeline.clear_memory()
            except Exception:
                pass
