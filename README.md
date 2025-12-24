# Talos: Modular RAG System

A production-ready Retrieval-Augmented Generation (RAG) system featuring modular architecture, hybrid retrieval, cross-encoder reranking, and advanced query processing capabilities. Built as a graduation project with emphasis on best practices and extensibility.

## Overview

Talos is a comprehensive RAG system that transforms your documents into intelligent conversations. The modular architecture allows you to swap components, configure parameters, and customize the pipeline to your needs without code changes.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Talos RAG Architecture                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌─────────────────┐  │
│  │  Document    │───▶│  Ingestion   │───▶│  Vector Store   │  │
│  │  Loaders     │    │  Pipeline    │    │  (Milvus)       │  │
│  └──────────────┘    └──────────────┘    └─────────────────┘  │
│                                                  │              │
│                           ┌──────────────────────┘              │
│                           ▼                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌─────────────────┐  │
│  │  Query       │───▶│  Hybrid      │───▶│  Cross-Encoder  │  │
│  │  Processor   │    │  Retriever   │    │  Reranker       │  │
│  └──────────────┘    └──────────────┘    └─────────────────┘  │
│                                                  │              │
│                           ┌──────────────────────┘              │
│                           ▼                                     │
│                      ┌──────────────┐                           │
│                      │  LLM Service │                           │
│                      │  (OpenAI)    │                           │
│                      └──────────────┘                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Features

### Core RAG Features
- **Modular Architecture**: Swap components and providers without code changes
- **Hybrid Retrieval**: Combines dense (semantic) and sparse (BM25) retrieval
- **Cross-Encoder Reranking**: Two-stage retrieval for improved relevance
- **Query Processing**: Query rewriting, expansion, and HyDE for better retrieval
- **Context Compression**: Reduce token usage while preserving relevance
- **Conversation Memory**: Multi-turn conversations with context awareness
- **Interactive CLI**: Comprehensive testing and demonstration interface

### Document Processing
- **Multiple Formats**: Support for PDF, TXT, Markdown, JSON, and more
- **Flexible Chunking**: Recursive, fixed-size, sentence-based strategies
- **Metadata Extraction**: Automatic extraction and enrichment
- **Batch Processing**: Efficient directory ingestion

### Production Ready
- **Configuration-Driven**: All parameters in YAML or environment variables
- **Logging & Monitoring**: Comprehensive structured logging
- **Error Handling**: Graceful degradation and informative errors
- **Type Safety**: Full Pydantic models and type hints
- **Extensible**: Easy to add new providers and strategies

## Quick Start

### Prerequisites

- Python 3.10+
- Docker (for Milvus vector store)
- OpenAI API key

### 1. Clone and Setup

```bash
git clone https://github.com/Ab-romia/gp-artifact.git
cd gp-artifact

# Copy environment configuration
cp .env.example .env
# Edit .env with your API keys
```

### 2. Install Dependencies

```bash
# Using uv (recommended)
pip install uv
uv venv
uv sync

# Or with pip
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Start Milvus Vector Store

```bash
docker compose up -d
```

### 4. Test the RAG System

```bash
# Interactive CLI
python rag_cli.py

# Load documents and query
/load /path/to/your/documents
What is this document about?
```

## Project Structure

```
gp-artifact/
├── src/                        # Modular RAG Implementation
│   ├── core/                   # Configuration & base classes
│   │   ├── config_loader.py    # Pydantic configuration models
│   │   ├── base_interfaces.py  # Abstract base classes
│   │   └── exceptions.py       # Custom exceptions
│   ├── indexing/               # Vector storage & embeddings
│   │   ├── milvus_manager.py   # Milvus vector store
│   │   ├── index_builder.py    # Indexing orchestration
│   │   └── embedding_service.py # Multi-provider embeddings
│   ├── ingestion/              # Document processing
│   │   ├── pipeline.py         # Ingestion orchestration
│   │   ├── document_loaders.py # File loaders
│   │   ├── chunking_strategies.py # Chunking methods
│   │   └── metadata_extractor.py # Metadata extraction
│   ├── retrieval/              # Document retrieval
│   │   ├── retrievers/
│   │   │   ├── dense_retriever.py   # Vector search
│   │   │   ├── sparse_retriever.py  # BM25 search
│   │   │   ├── hybrid_retriever.py  # Combined retrieval
│   │   │   └── reranker.py          # Cross-encoder reranking
│   │   └── query_processing/
│   │       ├── hyde.py              # HyDE query processing
│   │       ├── query_expander.py    # Query expansion
│   │       └── query_router.py      # Query classification
│   ├── generation/             # Response generation
│   │   └── llm_service.py      # LLM providers (OpenAI)
│   └── orchestration/          # Pipeline coordination
│       ├── rag_pipeline.py     # Main RAG orchestrator
│       └── memory.py           # Conversation memory
│
├── config/                     # Configuration files
│   ├── rag_config.yaml         # RAG pipeline configuration
│   └── prompts/                # Prompt templates
│       ├── answer_generation.txt
│       ├── query_rewriting.txt
│       └── query_classification.txt
│
├── rag_cli.py                  # Interactive CLI tool
├── docker-compose.yaml         # Milvus and dependencies
├── .env.example                # Environment template
└── requirements.txt            # Python dependencies
```

## Configuration

### Environment Variables

Key variables in `.env`:

```bash
# OpenAI API
OPENAI_API_KEY=sk-your-key

# Milvus Vector Store
MILVUS_HOST=localhost
MILVUS_PORT=19530

# Logging
LOG_LEVEL=INFO
```

### RAG Configuration

Edit `config/rag_config.yaml`:

```yaml
# Embedding configuration
embedding:
  provider: "huggingface"
  model_name: "sentence-transformers/all-MiniLM-L6-v2"
  dimension: 384
  normalize: true

# Retrieval configuration
retriever:
  top_k: 8
  dense_weight: 0.7
  sparse_weight: 0.3
  retrieval_method: "hybrid"  # dense, sparse, or hybrid

# Reranker configuration
reranker:
  enabled: true
  model: cross-encoder/ms-marco-MiniLM-L-6-v2
  top_n: 5

# Generator configuration
generator:
  provider: "openai"
  model_name: gpt-4o-mini
  temperature: 0.1
  max_tokens: 500

# Query processing
query_processor:
  enabled: true  # Query rewriting and expansion

# Orchestration
orchestration:
  routing_enabled: true  # Adaptive pipeline based on query type
  max_iterations: 3

# Chunking
chunking:
  strategy: "recursive"  # recursive, fixed, or sentence

# Milvus
milvus:
  collection_name: "rag_local"
  dimension: 384
```

## Interactive CLI

The `rag_cli.py` provides a comprehensive interface for testing the RAG system:

```bash
# Start interactive mode
python rag_cli.py

# Available commands:
/load <path>   - Load document(s)
/clear         - Clear conversation history
/info          - Show pipeline configuration
/verbose       - Toggle verbose output
/help          - Show help
/quit          - Exit
```

### CLI Features

- **Step-by-step visualization**: See each pipeline stage in action
- **Timing information**: Track performance of each component
- **Document inspection**: View retrieved and reranked documents
- **Source citations**: See which documents contributed to answers
- **Conversation memory**: Multi-turn conversations with context

## Technology Stack

### RAG Components
- **HuggingFace Transformers** - Embeddings and reranking
- **Sentence Transformers** - Semantic embeddings
- **OpenAI GPT-4** - Answer generation
- **Milvus** - Vector database
- **BM25** - Sparse retrieval (rank_bm25)

### Core Framework
- **Pydantic** - Configuration and data validation
- **PyYAML** - Configuration files
- **Python 3.10+** - Modern Python features

## RAG Pipeline Stages

### 1. Document Ingestion
```
Document → Loader → Chunker → Metadata Extractor → Index Builder → Vector Store
```

### 2. Query Processing
```
Query → Router → Processor (Rewrite/Expand/HyDE) → Enhanced Query
```

### 3. Retrieval
```
Enhanced Query → Dense Retriever (Semantic)
                → Sparse Retriever (BM25)
                → Hybrid Fusion → Top-K Documents
```

### 4. Reranking
```
Top-K Documents → Cross-Encoder → Top-N Most Relevant
```

### 5. Generation
```
Top-N Documents + Query + Memory → LLM → Answer with Citations
```

## Advanced Features

### Hybrid Retrieval
Combines semantic (dense) and keyword (sparse) search:
```python
# Dense: Find semantically similar content
# Sparse: Find exact keyword matches
# Hybrid: Weighted fusion of both
```

### Query Router
Automatically adapts pipeline based on query type:
- **Factual**: Direct retrieval and generation
- **Comparative**: Enhanced retrieval with multiple perspectives
- **Summarization**: Broader context gathering
- **Conversational**: Memory-aware processing

### HyDE (Hypothetical Document Embeddings)
Generates hypothetical answers to improve retrieval:
```
Query → LLM → Hypothetical Answer → Embed → Retrieve Similar
```

### Cross-Encoder Reranking
Two-stage retrieval for precision:
```
Stage 1: Fast retrieval (10-20 candidates)
Stage 2: Precise reranking (top 5)
```

## Performance Optimizations

- **Batch Processing**: Efficient embedding generation
- **Index Caching**: Reuse BM25 indices
- **Lazy Loading**: Components loaded on-demand
- **Connection Pooling**: Milvus connection reuse

## Development

### Running Tests

```bash
# Unit tests
pytest tests/

# Integration tests
pytest tests/integration/

# With coverage
pytest --cov=src tests/
```

### Adding New Components

1. **New Retriever**: Implement `BaseRetriever` interface
2. **New Chunker**: Implement `BaseChunker` interface
3. **New Embedder**: Implement `BaseEmbeddingService` interface
4. **New LLM**: Implement `BaseLLMService` interface

## Troubleshooting

### Common Issues

**Issue**: "Collection not found"
**Solution**: Documents need to be ingested first using `/load`

**Issue**: "Reranked to top 0 documents"
**Solution**: Check that documents were properly indexed (look for "Created X chunks")

**Issue**: "Failed to initialize BM25 index"
**Solution**: Ensure Milvus is running: `docker compose ps`

## Documentation

- **[Architecture Guide](docs/ARCHITECTURE.md)** - Detailed system design
- **[API Reference](docs/API.md)** - Component APIs
- **[Configuration Guide](docs/CONFIGURATION.md)** - All config options

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

This project is part of a graduation project for Talos AI-Powered RAG System.

---

**Talos RAG System** - Graduation Project 2025
