# Production-Ready Modular RAG System

A flexible, configuration-driven RAG (Retrieval-Augmented Generation) system with CLaRa-inspired optimizations.

## Architecture Overview

```
src/
├── core/                      # Core components
│   ├── config_loader.py       # Pydantic configuration models
│   ├── base_interfaces.py     # Abstract base classes
│   └── exceptions.py          # Custom exception hierarchy
│
├── indexing/                  # Vector storage & embeddings
│   ├── milvus_manager.py      # Milvus vector store
│   ├── embedding_service.py   # Multi-provider embeddings
│   └── index_builder.py       # Index management
│
├── ingestion/                 # Document processing
│   ├── document_loaders.py    # Multi-format loaders
│   ├── chunking_strategies.py # Semantic/fixed chunking
│   ├── metadata_extractors.py # Metadata extraction
│   └── pipeline.py            # Ingestion orchestration
│
├── retrieval/                 # Document retrieval
│   ├── retrievers/
│   │   ├── dense_retriever.py    # Vector similarity search
│   │   ├── hybrid_retriever.py   # Dense + BM25 with RRF
│   │   └── reranker.py           # Cross-encoder reranking
│   ├── query_processing/
│   │   ├── query_rewriter.py     # LLM query enhancement
│   │   └── query_expander.py     # Multi-query generation
│   └── compression/
│       └── context_compressor.py # CLaRa-inspired compression
│
├── generation/                # Response generation
│   ├── llm_service.py         # Multi-provider LLM support
│   ├── prompt_builder.py      # Template-based prompts
│   ├── response_parser.py     # Response validation
│   └── citation_handler.py    # Source citation
│
├── orchestration/             # Pipeline coordination
│   ├── rag_pipeline.py        # Main RAG orchestrator
│   ├── query_router.py        # Adaptive query routing
│   └── conversation_memory.py # Conversation state
│
└── utils/                     # Utilities
    ├── logger.py              # Structured logging
    ├── cache_manager.py       # Embedding & result cache
    └── async_helpers.py       # Async utilities
```

## Key Features

### Zero Hardcoding
All parameters are configurable via YAML files. No magic numbers or hardcoded values.

### CLaRa-Inspired Optimizations
- **Semantic Chunking**: Split documents based on meaning, not fixed size
- **Two-Stage Retrieval**: Dense retrieval → Cross-encoder reranking
- **Context Compression**: Reduce context while preserving relevance
- **Query Enhancement**: LLM-based query rewriting and expansion

### Modular Design
- Swap embedding providers (OpenAI, HuggingFace, Cohere)
- Swap LLM providers (OpenAI, Anthropic)
- Swap vector stores (Milvus, in-memory)
- Configure chunking strategies
- Enable/disable components via config

### Production Ready
- Comprehensive error handling
- Structured logging with metrics
- Connection pooling for Milvus
- Embedding caching
- Retry logic with exponential backoff

## Quick Start

```python
from src.orchestration.rag_pipeline import RAGPipeline

# Initialize with configuration
pipeline = RAGPipeline(config_path="config/rag_config_new.yaml")

# Ingest documents
pipeline.ingest(["Document 1 content", "Document 2 content"])

# Query
result = pipeline.query("What is in the documents?")
print(result.answer)
print(f"Sources: {len(result.sources)}")
```

## Configuration

See `config/rag_config_new.yaml` for all available options:

- Milvus connection settings
- Embedding model configuration
- Retrieval parameters
- Reranker settings
- LLM configuration
- Query processing options
- Chunking strategies
- Memory settings

## Components

### Retrievers
- **DenseRetriever**: Vector similarity search using embeddings
- **HybridRetriever**: Combines dense + BM25 with Reciprocal Rank Fusion

### Chunking Strategies
- **FixedChunker**: Fixed size chunks with overlap
- **RecursiveChunker**: Hierarchical splitting by separators
- **SemanticChunker**: Embedding-based semantic boundaries
- **SentenceChunker**: Sentence-level chunking
- **MarkdownChunker**: Structure-aware markdown splitting

### Query Processing
- Query rewriting for better retrieval
- Query expansion (multi-query generation)
- HyDE (Hypothetical Document Embedding)
- Step-back prompting
- Query decomposition

### Query Routing
Automatically classifies queries into types:
- FACTUAL, ANALYTICAL, COMPARATIVE
- PROCEDURAL, CONVERSATIONAL
- EXPLORATORY, UNCLEAR

Each type gets optimized pipeline settings.

## Examples

See the `examples/` directory:
- `basic_qa.py` - Simple Q&A
- `document_ingestion.py` - Document loading and chunking
- `advanced_retrieval.py` - Multi-stage retrieval comparison
