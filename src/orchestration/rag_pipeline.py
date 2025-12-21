"""
Main RAG pipeline orchestrator.

Coordinates all components for end-to-end RAG operations.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.core.base_interfaces import BaseRAGPipeline, BaseVectorStore, Document, QueryResult
from src.core.config_loader import RAGConfig, load_config
from src.core.exceptions import PipelineError, RetrievalError
from src.indexing.milvus_manager import MilvusVectorStore, InMemoryVectorStore
from src.indexing.embedding_service import EmbeddingService, create_embedding_service
from src.ingestion.pipeline import IngestionPipeline
from src.retrieval.retrievers.dense_retriever import DenseRetriever
from src.retrieval.retrievers.hybrid_retriever import HybridRetriever
from src.retrieval.retrievers.reranker import CrossEncoderReranker
from src.retrieval.query_processing.query_rewriter import QueryRewriter, HyDEQueryProcessor
from src.retrieval.query_processing.query_expander import QueryExpander
from src.retrieval.compression.context_compressor import ContextCompressor
from src.generation.llm_service import LLMService, create_llm_service
from src.generation.prompt_builder import PromptBuilder
from src.generation.citation_handler import CitationHandler
from src.orchestration.query_router import QueryRouter, QueryType
from src.orchestration.conversation_memory import ConversationMemory
from src.utils.logger import get_logger
from src.utils.cache_manager import CacheManager

logger = get_logger(__name__)


class RAGPipeline(BaseRAGPipeline):
    """
    Production-ready RAG pipeline orchestrator.

    Integrates all components for complete RAG functionality with:
    - Adaptive query routing
    - CLaRa-inspired optimizations
    - Multi-stage retrieval with reranking
    - Context compression
    - Conversation memory
    """

    def __init__(
        self,
        config: Optional[RAGConfig] = None,
        config_path: Optional[str] = None,
        vector_store: Optional[BaseVectorStore] = None,
        embedding_service: Optional[EmbeddingService] = None,
        llm_service: Optional[LLMService] = None,
    ):
        """
        Initialize RAG pipeline.

        Args:
            config: RAG configuration (loaded from path if not provided)
            config_path: Path to configuration file
            vector_store: Custom vector store (created from config if not provided)
            embedding_service: Custom embedding service
            llm_service: Custom LLM service
        """
        # Load configuration
        if config:
            self.config = config
        elif config_path:
            self.config = RAGConfig.from_yaml(config_path)
        else:
            self.config = load_config()

        logger.info("Initializing RAG Pipeline...")

        # Initialize components
        self._init_vector_store(vector_store)
        self._init_embedding_service(embedding_service)
        self._init_llm_service(llm_service)
        self._init_retrieval_components()
        self._init_generation_components()
        self._init_orchestration_components()

        # Cache manager
        self.cache = CacheManager()

        # Document tracking for BM25
        self._indexed_documents: List[Document] = []

        logger.info("RAG Pipeline initialized successfully")

    def _init_vector_store(self, vector_store: Optional[BaseVectorStore]) -> None:
        """Initialize vector store."""
        if vector_store:
            self.vector_store = vector_store
        else:
            # Use in-memory store by default for easier setup
            # Switch to MilvusVectorStore for production
            try:
                self.vector_store = MilvusVectorStore(self.config.milvus)
                self.vector_store.connect()
            except Exception as e:
                logger.warning(f"Milvus not available, using in-memory store: {e}")
                self.vector_store = InMemoryVectorStore(self.config.milvus)

    def _init_embedding_service(self, embedding_service: Optional[EmbeddingService]) -> None:
        """Initialize embedding service."""
        self.embedding_service = embedding_service or create_embedding_service(
            self.config.embedding
        )

    def _init_llm_service(self, llm_service: Optional[LLMService]) -> None:
        """Initialize LLM service."""
        self.llm_service = llm_service or create_llm_service(self.config.generator)

    def _init_retrieval_components(self) -> None:
        """Initialize retrieval components."""
        collection_name = self.config.milvus.collection_name

        # Dense retriever
        self.dense_retriever = DenseRetriever(
            config=self.config.retriever,
            vector_store=self.vector_store,
            embedding_service=self.embedding_service,
            collection_name=collection_name,
        )

        # Hybrid retriever
        self.hybrid_retriever = HybridRetriever(
            config=self.config.retriever,
            vector_store=self.vector_store,
            embedding_service=self.embedding_service,
            collection_name=collection_name,
        )

        # Populate BM25 index from vector store
        try:
            # We fetch documents to build the sparse index in memory
            # This is necessary because Milvus (in this config) is storing the dense vectors
            # but we need the raw text for BM25.
            if self.vector_store.collection_exists(collection_name):
                logger.info(f"Loading documents from '{collection_name}' for sparse index...")
                existing_docs = self.vector_store.get_all_documents(collection_name)
                
                if existing_docs:
                    self.hybrid_retriever.set_documents(existing_docs)
                    self._indexed_documents = existing_docs
                    logger.info(f"Initialized BM25 index with {len(existing_docs)} documents")
                else:
                    logger.info("No documents found in collection.")
        except Exception as e:
            logger.warning(f"Failed to initialize BM25 index: {e}")

        # Reranker
        self.reranker = None
        if self.config.reranker.enabled:
            self.reranker = CrossEncoderReranker(self.config.reranker)

        # Query processor
        self.query_processor = None
        if self.config.query_processor.enabled:
            self.query_processor = HyDEQueryProcessor(
                self.config.query_processor,
                self.llm_service,
            )

        # Query expander
        self.query_expander = QueryExpander(
            self.config.query_processor,
            self.llm_service,
        )

        # Context compressor
        self.context_compressor = None
        if self.config.compression.enabled:
            self.context_compressor = ContextCompressor(
                self.config.compression,
                self.llm_service,
                self.embedding_service,
            )

    def _init_generation_components(self) -> None:
        """Initialize generation components."""
        self.prompt_builder = PromptBuilder(self.config.prompts)
        self.citation_handler = CitationHandler()

    def _init_orchestration_components(self) -> None:
        """Initialize orchestration components."""
        # Query router
        self.query_router = None
        if self.config.orchestration.routing_enabled:
            self.query_router = QueryRouter(
                self.config.orchestration,
                self.config.knowledge_base.description,
                self.llm_service,
            )

        # Conversation memory
        self.memory = ConversationMemory(self.config.memory)

    def query(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        return_sources: bool = True,
        verbose: bool = False,
    ) -> QueryResult:
        """
        Execute a RAG query.

        Args:
            question: User question
            filters: Optional metadata filters
            return_sources: Whether to include source documents
            verbose: Enable verbose logging

        Returns:
            QueryResult with answer and metadata
        """
        start_time = time.perf_counter()

        try:
            # Step 1: Route query
            query_type = None
            pipeline_config = self._get_default_pipeline_config()

            if self.query_router:
                query_type_str = self.query_router.classify(question)
                query_type = query_type_str
                pipeline_config = self.query_router.get_pipeline_config(query_type_str)

                if verbose:
                    logger.info(f"Query type: {query_type}, Strategy: {pipeline_config.get('strategy')}")

            # Step 2: Process query
            processed_query = question
            processing_result = {}

            if self.query_processor and pipeline_config.get("use_query_processing"):
                conversation_context = None
                if self.memory.has_history():
                    conversation_context = self.memory.get_contextual_summary()

                processing_result = self.query_processor.process(question, conversation_context)
                processed_query = processing_result.get("processed_query", question)

                if verbose and processed_query != question:
                    logger.info(f"Processed query: {processed_query}")

            # Step 3: Retrieve documents
            retrieval_method = pipeline_config.get("retrieval_method", "hybrid")
            top_k = pipeline_config.get("retrieval_top_k", self.config.retriever.top_k)

            documents = self._retrieve(
                query=processed_query,
                method=retrieval_method,
                top_k=top_k,
                filters=filters,
                processing_result=processing_result,
                verbose=verbose,
            )

            # Step 4: Rerank if enabled
            if self.reranker and pipeline_config.get("use_reranking"):
                rerank_top_n = pipeline_config.get("reranker_top_n", self.config.reranker.top_n)
                documents = self.reranker.rerank(question, documents, top_n=rerank_top_n)

                if verbose:
                    logger.info(f"Reranked to {len(documents)} documents")

            # Step 5: Compress context if enabled
            if self.context_compressor and self.config.compression.enabled:
                documents = self.context_compressor.compress(question, documents)

                if verbose:
                    logger.info("Context compressed")

            # Step 6: Generate response
            conversation_history = None
            if self.memory.has_history() and pipeline_config.get("use_conversation_context"):
                conversation_history = self.memory.get_history(max_turns=3)

            # Handle case where no documents were retrieved
            if not documents:
                # Check if collection exists
                collection_name = self.config.milvus.collection_name
                if not self.vector_store.collection_exists(collection_name):
                    no_docs_answer = (
                        "I don't have any documents loaded yet. Please load some documents first using:\n"
                        "  /load <path>  - Load document(s) from a file or directory\n\n"
                        "Example: /load data/docs/sample.txt"
                    )
                else:
                    no_docs_answer = (
                        "I couldn't find any relevant documents to answer your question. "
                        "Try rephrasing your question or loading more relevant documents."
                    )

                return QueryResult(
                    answer=no_docs_answer,
                    sources=[],
                    query=question,
                    processed_query=processed_query if processed_query != question else None,
                    query_type=query_type,
                    total_latency_ms=(time.perf_counter() - start_time) * 1000,
                    metadata={"no_documents": True},
                )

            generation_result = self.llm_service.generate(
                query=question,
                context=documents,
                conversation_history=conversation_history,
            )

            # Step 7: Handle citations
            if return_sources:
                self.citation_handler.track_sources(documents)

            # Step 8: Update memory
            self.memory.add_turn(
                question=question,
                answer=generation_result.answer,
                metadata={
                    "query_type": query_type,
                    "processed_query": processed_query,
                    "num_sources": len(documents),
                },
                retrieved_context=documents if self.config.memory.include_context_in_history else None,
            )

            # Calculate total latency
            total_latency = (time.perf_counter() - start_time) * 1000

            return QueryResult(
                answer=generation_result.answer,
                sources=documents if return_sources else [],
                query=question,
                processed_query=processed_query if processed_query != question else None,
                query_type=query_type,
                retrieval_latency_ms=0,  # Would need to track separately
                generation_latency_ms=generation_result.latency_ms,
                total_latency_ms=total_latency,
                metadata={
                    "strategy": pipeline_config.get("strategy"),
                    "prompt_tokens": generation_result.prompt_tokens,
                    "completion_tokens": generation_result.completion_tokens,
                    "citations": self.citation_handler.get_citation_metadata(),
                },
            )

        except Exception as e:
            raise PipelineError(
                f"Query failed: {e}",
                stage="query",
                pipeline_type=self.config.pipeline_type,
                cause=e,
            )

    def _retrieve(
        self,
        query: str,
        method: str,
        top_k: int,
        filters: Optional[Dict[str, Any]],
        processing_result: Dict[str, Any],
        verbose: bool,
    ) -> List[Document]:
        """Execute retrieval with appropriate method."""
        # Check if collection exists
        collection_name = self.config.milvus.collection_name
        if not self.vector_store.collection_exists(collection_name):
            logger.warning(f"Collection '{collection_name}' does not exist. No documents to retrieve.")
            return []

        # Check for HyDE
        if processing_result.get("hypothetical_doc"):
            # Use hypothetical document for dense retrieval
            hyde_doc = processing_result["hypothetical_doc"]
            result = self.dense_retriever.retrieve(hyde_doc, top_k=top_k, filters=filters)
            documents = result.documents

            if verbose:
                logger.info(f"HyDE retrieval: {len(documents)} documents")
        elif method == "hybrid":
            result = self.hybrid_retriever.retrieve(query, top_k=top_k, filters=filters)
            documents = result.documents
        else:
            result = self.dense_retriever.retrieve(query, top_k=top_k, filters=filters)
            documents = result.documents

        # Handle step-back query
        if processing_result.get("step_back_query"):
            step_back_result = self.dense_retriever.retrieve(
                processing_result["step_back_query"],
                top_k=3,
                filters=filters,
            )
            # Add unique documents
            existing_ids = {doc.id for doc in documents}
            for doc in step_back_result.documents:
                if doc.id not in existing_ids:
                    documents.append(doc)

        # Handle sub-queries
        if processing_result.get("sub_queries"):
            for sub_query in processing_result["sub_queries"][:2]:  # Limit sub-queries
                sub_result = self.dense_retriever.retrieve(sub_query, top_k=3, filters=filters)
                existing_ids = {doc.id for doc in documents}
                for doc in sub_result.documents:
                    if doc.id not in existing_ids:
                        documents.append(doc)

        return documents

    def _get_default_pipeline_config(self) -> Dict[str, Any]:
        """Get default pipeline configuration."""
        return {
            "strategy": "default",
            "use_query_processing": self.config.query_processor.enabled,
            "retrieval_method": self.config.retriever.retrieval_method,
            "retrieval_top_k": self.config.retriever.top_k,
            "use_reranking": self.config.reranker.enabled,
            "reranker_top_n": self.config.reranker.top_n,
            "use_conversation_context": self.config.memory.enabled,
            "max_iterations": self.config.orchestration.max_iterations,
        }

    def ingest(
        self,
        documents: Union[List[Document], List[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Ingest documents into the system.

        Args:
            documents: Documents or text strings to ingest
            metadata: Optional metadata for all documents

        Returns:
            Number of documents ingested
        """
        # Convert strings to documents
        if documents and isinstance(documents[0], str):
            documents = [
                Document(content=text, metadata=metadata or {})
                for text in documents
            ]

        # Create collection if needed
        collection_name = self.config.milvus.collection_name
        if not self.vector_store.collection_exists(collection_name):
            self.vector_store.create_collection(
                collection_name=collection_name,
                dimension=self.embedding_service.get_dimension(),
            )

        # Generate embeddings
        texts = [doc.content for doc in documents]
        embeddings = self.embedding_service.embed_documents(texts)

        for doc, embedding in zip(documents, embeddings):
            doc.embedding = embedding

        # Insert into vector store
        self.vector_store.insert(collection_name, documents)

        # Update BM25 index for hybrid search
        self._indexed_documents.extend(documents)
        self.hybrid_retriever.set_documents(self._indexed_documents)

        logger.info(f"Ingested {len(documents)} documents")
        return len(documents)

    def ingest_file(
        self,
        file_path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ingest a file.

        Args:
            file_path: Path to file
            metadata: Optional metadata

        Returns:
            Ingestion statistics
        """
        from src.ingestion.pipeline import IngestionPipeline
        from src.ingestion.chunking_strategies import create_chunker

        chunker = create_chunker(
            self.config.chunking,
            self.embedding_service if self.config.chunking.strategy == "semantic" else None,
        )

        pipeline = IngestionPipeline(
            config=self.config,
            vector_store=self.vector_store,
            embedding_service=self.embedding_service,
            chunker=chunker,
        )

        return pipeline.ingest_file(file_path, additional_metadata=metadata)

    def get_pipeline_info(self) -> Dict[str, Any]:
        """Get information about the pipeline configuration."""
        return {
            "pipeline_type": self.config.pipeline_type,
            "embedding_model": self.config.embedding.model_name,
            "llm_model": self.config.generator.model_name,
            "retrieval_method": self.config.retriever.retrieval_method,
            "reranker_enabled": self.config.reranker.enabled,
            "reranker_model": self.config.reranker.model_name if self.config.reranker.enabled else None,
            "query_processing_enabled": self.config.query_processor.enabled,
            "routing_enabled": self.config.orchestration.routing_enabled,
            "compression_enabled": self.config.compression.enabled,
            "memory_enabled": self.config.memory.enabled,
            "collection_name": self.config.milvus.collection_name,
        }

    def clear_memory(self) -> None:
        """Clear conversation memory."""
        self.memory.clear()

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get conversation memory statistics."""
        return self.memory.get_session_stats()
