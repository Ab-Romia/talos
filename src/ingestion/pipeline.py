"""
Document ingestion pipeline.

Orchestrates document loading, chunking, metadata extraction, and indexing.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.core.base_interfaces import BaseVectorStore, Document
from src.core.config_loader import RAGConfig
from src.ingestion.document_loaders import DocumentLoader, create_loader
from src.ingestion.chunking_strategies import TextChunker, create_chunker
from src.ingestion.metadata_extractors import MetadataExtractor
from src.indexing.embedding_service import EmbeddingService, create_embedding_service
from src.indexing.index_builder import IndexBuilder
from src.utils.logger import get_logger

logger = get_logger(__name__)


class IngestionPipeline:
    """
    Complete document ingestion pipeline.

    Handles the full workflow from raw documents to indexed vectors.
    """

    def __init__(
        self,
        config: RAGConfig,
        vector_store: BaseVectorStore,
        embedding_service: Optional[EmbeddingService] = None,
        chunker: Optional[TextChunker] = None,
        metadata_extractor: Optional[MetadataExtractor] = None,
    ):
        """
        Initialize ingestion pipeline.

        Args:
            config: RAG configuration
            vector_store: Vector store for indexing
            embedding_service: Embedding service (created from config if not provided)
            chunker: Document chunker (created from config if not provided)
            metadata_extractor: Metadata extractor (default created if not provided)
        """
        self.config = config
        self.vector_store = vector_store

        # Initialize components
        self.embedding_service = embedding_service or create_embedding_service(
            config.embedding
        )
        self.chunker = chunker or create_chunker(
            config.chunking,
            embedding_service=self.embedding_service if config.chunking.strategy == "semantic" else None,
        )
        self.metadata_extractor = metadata_extractor or MetadataExtractor()

        # Index builder
        self.index_builder = IndexBuilder(
            config=config,
            vector_store=vector_store,
            embedding_service=self.embedding_service,
        )

    def ingest_file(
        self,
        file_path: Union[str, Path],
        collection_name: Optional[str] = None,
        additional_metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[dict[str, Any], list]:
        """
        Ingest a single file.

        Args:
            file_path: Path to file
            collection_name: Target collection
            additional_metadata: Extra metadata to add to all documents

        Returns:
            A tuple containing ingestion statistics and the ingested documents.
        """
        file_path = Path(file_path)

        # Create appropriate loader
        loader = create_loader(str(file_path))

        # Load and chunk
        documents = loader.load_and_chunk(str(file_path), self.chunker)

        # Add metadata
        if additional_metadata:
            for doc in documents:
                doc.metadata.update(additional_metadata)

        # Extract metadata
        documents = self.metadata_extractor.extract_batch(documents)

        # Index
        stats = self.index_builder.build_index(
            documents=documents,
            collection_name=collection_name,
        )

        logger.info(f"Ingested file: {file_path}", **stats)
        return stats, documents

    def ingest_directory(
        self,
        directory_path: Union[str, Path],
        glob_pattern: str = "*",
        recursive: bool = True,
        collection_name: Optional[str] = None,
        additional_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ingest all documents from a directory.

        Args:
            directory_path: Path to directory
            glob_pattern: File pattern to match
            recursive: Whether to search recursively
            collection_name: Target collection
            additional_metadata: Extra metadata

        Returns:
            Ingestion statistics
        """
        from src.ingestion.document_loaders import DirectoryLoader

        directory_path = Path(directory_path)

        # Create directory loader
        loader = DirectoryLoader(
            glob_pattern=glob_pattern,
            recursive=recursive,
        )

        # Load all documents
        documents = loader.load(str(directory_path))

        # Chunk documents
        chunked_documents = self.chunker.chunk_documents(documents)

        # Add metadata
        if additional_metadata:
            for doc in chunked_documents:
                doc.metadata.update(additional_metadata)

        # Extract metadata
        chunked_documents = self.metadata_extractor.extract_batch(chunked_documents)

        # Index
        stats = self.index_builder.build_index(
            documents=chunked_documents,
            collection_name=collection_name,
        )

        logger.info(f"Ingested directory: {directory_path}", **stats)
        return stats

    def ingest_texts(
        self,
        texts: List[str],
        metadata_list: Optional[List[Dict[str, Any]]] = None,
        collection_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest raw text strings.

        Args:
            texts: List of text content
            metadata_list: Optional metadata for each text
            collection_name: Target collection

        Returns:
            Ingestion statistics
        """
        if metadata_list is None:
            metadata_list = [{}] * len(texts)

        # Create documents
        documents = []
        for text, metadata in zip(texts, metadata_list):
            doc = Document(content=text, metadata=metadata)
            documents.append(doc)

        # Chunk
        chunked_documents = self.chunker.chunk_documents(documents)

        # Extract metadata
        chunked_documents = self.metadata_extractor.extract_batch(chunked_documents)

        # Index
        stats = self.index_builder.build_index(
            documents=chunked_documents,
            collection_name=collection_name,
        )

        return stats

    def ingest_documents(
        self,
        documents: List[Document],
        collection_name: Optional[str] = None,
        skip_chunking: bool = False,
    ) -> Dict[str, Any]:
        """
        Ingest pre-created Document objects.

        Args:
            documents: Documents to ingest
            collection_name: Target collection
            skip_chunking: If True, skip chunking step

        Returns:
            Ingestion statistics
        """
        # Chunk if needed
        if not skip_chunking:
            documents = self.chunker.chunk_documents(documents)

        # Extract metadata
        documents = self.metadata_extractor.extract_batch(documents)

        # Index
        return self.index_builder.build_index(
            documents=documents,
            collection_name=collection_name,
        )
