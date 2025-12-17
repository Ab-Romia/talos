"""
Custom exception hierarchy for the RAG system.

Provides specific exceptions for different failure modes to enable
proper error handling and debugging.
"""

from typing import Any, Dict, Optional


class RAGException(Exception):
    """Base exception for all RAG system errors."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.cause = cause

    def __str__(self) -> str:
        error_str = self.message
        if self.details:
            error_str += f" | Details: {self.details}"
        if self.cause:
            error_str += f" | Caused by: {self.cause}"
        return error_str


class ConfigurationError(RAGException):
    """Error in configuration loading or validation."""

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if config_key:
            details["config_key"] = config_key
        super().__init__(message, details=details, **kwargs)


class VectorStoreError(RAGException):
    """Error in vector store operations."""

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        collection: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if operation:
            details["operation"] = operation
        if collection:
            details["collection"] = collection
        super().__init__(message, details=details, **kwargs)


class MilvusConnectionError(VectorStoreError):
    """Error connecting to Milvus."""

    def __init__(
        self,
        message: str,
        host: Optional[str] = None,
        port: Optional[int] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if host:
            details["host"] = host
        if port:
            details["port"] = port
        super().__init__(message, operation="connect", **kwargs)


class CollectionNotFoundError(VectorStoreError):
    """Collection does not exist."""

    def __init__(self, collection_name: str, **kwargs):
        super().__init__(
            f"Collection '{collection_name}' not found",
            collection=collection_name,
            operation="access",
            **kwargs,
        )


class EmbeddingError(RAGException):
    """Error in embedding generation."""

    def __init__(
        self,
        message: str,
        model: Optional[str] = None,
        batch_size: Optional[int] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if model:
            details["model"] = model
        if batch_size:
            details["batch_size"] = batch_size
        super().__init__(message, details=details, **kwargs)


class EmbeddingRateLimitError(EmbeddingError):
    """Rate limit exceeded for embedding API."""

    def __init__(
        self,
        message: str = "Embedding API rate limit exceeded",
        retry_after: Optional[float] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__(message, details=details, **kwargs)


class RetrievalError(RAGException):
    """Error in document retrieval."""

    def __init__(
        self,
        message: str,
        query: Optional[str] = None,
        retrieval_method: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if query:
            details["query"] = query[:100] + "..." if len(query) > 100 else query
        if retrieval_method:
            details["method"] = retrieval_method
        super().__init__(message, details=details, **kwargs)


class GenerationError(RAGException):
    """Error in response generation."""

    def __init__(
        self,
        message: str,
        model: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if model:
            details["model"] = model
        if prompt_tokens:
            details["prompt_tokens"] = prompt_tokens
        super().__init__(message, details=details, **kwargs)


class GenerationRateLimitError(GenerationError):
    """Rate limit exceeded for generation API."""

    def __init__(
        self,
        message: str = "Generation API rate limit exceeded",
        retry_after: Optional[float] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__(message, details=details, **kwargs)


class DocumentLoadError(RAGException):
    """Error loading documents."""

    def __init__(
        self,
        message: str,
        source: Optional[str] = None,
        file_type: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if source:
            details["source"] = source
        if file_type:
            details["file_type"] = file_type
        super().__init__(message, details=details, **kwargs)


class UnsupportedFileTypeError(DocumentLoadError):
    """File type not supported by loader."""

    def __init__(
        self,
        file_type: str,
        supported_types: Optional[list] = None,
        **kwargs,
    ):
        message = f"Unsupported file type: {file_type}"
        details = kwargs.get("details", {})
        if supported_types:
            details["supported_types"] = supported_types
        super().__init__(message, file_type=file_type, details=details, **kwargs)


class ChunkingError(RAGException):
    """Error in document chunking."""

    def __init__(
        self,
        message: str,
        strategy: Optional[str] = None,
        document_length: Optional[int] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if strategy:
            details["strategy"] = strategy
        if document_length:
            details["document_length"] = document_length
        super().__init__(message, details=details, **kwargs)


class QueryProcessingError(RAGException):
    """Error in query processing."""

    def __init__(
        self,
        message: str,
        query: Optional[str] = None,
        processing_step: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if query:
            details["query"] = query[:100] + "..." if len(query) > 100 else query
        if processing_step:
            details["step"] = processing_step
        super().__init__(message, details=details, **kwargs)


class RerankerError(RAGException):
    """Error in document reranking."""

    def __init__(
        self,
        message: str,
        model: Optional[str] = None,
        num_documents: Optional[int] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if model:
            details["model"] = model
        if num_documents:
            details["num_documents"] = num_documents
        super().__init__(message, details=details, **kwargs)


class MemoryError(RAGException):
    """Error in conversation memory operations."""

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if operation:
            details["operation"] = operation
        super().__init__(message, details=details, **kwargs)


class PipelineError(RAGException):
    """Error in RAG pipeline execution."""

    def __init__(
        self,
        message: str,
        stage: Optional[str] = None,
        pipeline_type: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if stage:
            details["stage"] = stage
        if pipeline_type:
            details["pipeline_type"] = pipeline_type
        super().__init__(message, details=details, **kwargs)
