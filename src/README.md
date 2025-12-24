# Talos RAG System - Production-Ready Modular Architecture

A flexible, configuration-driven RAG (Retrieval-Augmented Generation) system with CLaRa-inspired optimizations, designed for easy integration into any application.

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Complete Pipeline Flow](#complete-pipeline-flow)
- [Module Reference](#module-reference)
- [Key Features](#key-features)
- [CLaRa Implementation](#clara-implementation)
- [Reranker System](#reranker-system)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
- [Integration Guide](#integration-guide)
- [API Reference](#api-reference)

---

## Architecture Overview

```
src/
├── core/                          # Foundation layer
│   ├── base_interfaces.py         # Abstract contracts (13 interfaces)
│   ├── config_loader.py           # Pydantic configuration (13 config classes)
│   └── exceptions.py              # Exception hierarchy (12 exception types)
│
├── indexing/                      # Vector storage & embeddings
│   ├── milvus_manager.py          # Base Milvus + InMemory stores
│   ├── milvus_vector_store.py     # Optimized Milvus with index selection
│   ├── embedding_service.py       # OpenAI, HuggingFace, Cohere embeddings
│   ├── sparse_encoder.py          # BM25, TF-IDF, SPLADE encoders
│   └── index_builder.py           # Index orchestration
│
├── ingestion/                     # Document processing
│   ├── document_loaders.py        # PDF, TXT, MD, JSON loaders
│   ├── chunking_strategies.py     # 5 chunking strategies
│   ├── metadata_extractors.py     # Metadata extraction
│   └── pipeline.py                # Ingestion orchestration
│
├── retrieval/                     # Multi-stage retrieval
│   ├── retrievers/
│   │   ├── dense_retriever.py     # Vector similarity + Multi-query
│   │   ├── hybrid_retriever.py    # Dense + BM25 with RRF fusion
│   │   └── reranker.py            # CrossEncoder + Cohere rerankers
│   ├── query_processing/
│   │   ├── query_rewriter.py      # HyDE, step-back, decomposition
│   │   └── query_expander.py      # Multi-query expansion
│   └── compression/
│       └── context_compressor.py  # CLaRa-inspired compression (3 methods)
│
├── generation/                    # Response generation
│   ├── llm_service.py             # OpenAI + Anthropic LLMs
│   ├── prompt_builder.py          # Template management
│   ├── response_parser.py         # Response validation
│   └── citation_handler.py        # Source citation formatting
│
├── orchestration/                 # Pipeline coordination
│   ├── rag_pipeline.py            # Main RAG orchestrator
│   ├── query_router.py            # 7-type query classification
│   └── conversation_memory.py     # Multi-turn conversation
│
└── utils/                         # Support utilities
    ├── logger.py                  # Structured logging with metrics
    ├── cache_manager.py           # Embedding cache
    └── async_helpers.py           # Retry decorators
```

---

## Complete Pipeline Flow

### Document Ingestion Flow
```
┌─────────────────────────────────────────────────────────────────────────┐
│                         INGESTION PIPELINE                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Documents (PDF/TXT/MD/JSON)                                            │
│       │                                                                  │
│       ▼                                                                  │
│  ┌─────────────────┐                                                     │
│  │ DocumentLoaders │ ─── Load & parse content                            │
│  └────────┬────────┘                                                     │
│           ▼                                                              │
│  ┌─────────────────┐     ┌─────────────────────────────────────────┐    │
│  │ ChunkingStrategy│ ◄───│ Fixed │ Recursive │ Semantic │ Markdown │    │
│  └────────┬────────┘     └─────────────────────────────────────────┘    │
│           ▼                                                              │
│  ┌─────────────────┐                                                     │
│  │ MetadataExtract │ ─── Source, timestamps, structure                   │
│  └────────┬────────┘                                                     │
│           ▼                                                              │
│  ┌─────────────────┐     ┌───────────────────────────────────────┐      │
│  │ EmbeddingService│ ◄───│ OpenAI │ HuggingFace │ Cohere         │      │
│  └────────┬────────┘     └───────────────────────────────────────┘      │
│           ▼                                                              │
│  ┌─────────────────┐     ┌───────────────────────────────────────┐      │
│  │  VectorStore    │ ◄───│ Milvus (HNSW/IVF/DISKANN) │ InMemory  │      │
│  └─────────────────┘     └───────────────────────────────────────┘      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Query Processing Flow
```
┌─────────────────────────────────────────────────────────────────────────┐
│                          QUERY PIPELINE                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  User Query: "How does X work?"                                          │
│       │                                                                  │
│       ▼                                                                  │
│  ┌─────────────────┐                                                     │
│  │  QueryRouter    │ ─── Classify: FACTUAL/ANALYTICAL/PROCEDURAL/etc     │
│  └────────┬────────┘                                                     │
│           │ Returns: query_type + pipeline_config                        │
│           ▼                                                              │
│  ┌─────────────────┐     ┌───────────────────────────────────────┐      │
│  │ HyDEQueryProc   │ ◄───│ Rewrite │ HyDE │ Step-back │ Decompose│      │
│  └────────┬────────┘     └───────────────────────────────────────┘      │
│           │                                                              │
│           ▼                                                              │
│  ┌─────────────────┐     ┌───────────────────────────────────────┐      │
│  │   Retriever     │ ◄───│ Dense (vector) │ Hybrid (vector+BM25) │      │
│  └────────┬────────┘     └───────────────────────────────────────┘      │
│           │                                                              │
│           │ Retrieved documents (top-k)                                  │
│           ▼                                                              │
│  ┌─────────────────┐     ┌───────────────────────────────────────┐      │
│  │    Reranker     │ ◄───│ CrossEncoder │ Cohere API             │      │
│  └────────┬────────┘     └───────────────────────────────────────┘      │
│           │                                                              │
│           │ Reranked documents (top-n)                                   │
│           ▼                                                              │
│  ┌─────────────────┐     ┌───────────────────────────────────────┐      │
│  │ ContextCompress │ ◄───│ LLM Extract │ Embedding Filter │ Chain│ [CLaRa]
│  └────────┬────────┘     └───────────────────────────────────────┘      │
│           │                                                              │
│           │ Compressed context                                           │
│           ▼                                                              │
│  ┌─────────────────┐     ┌───────────────────────────────────────┐      │
│  │   LLMService    │ ◄───│ OpenAI (GPT-4) │ Anthropic (Claude)   │      │
│  └────────┬────────┘     └───────────────────────────────────────┘      │
│           │                                                              │
│           │ Generated answer                                             │
│           ▼                                                              │
│  ┌─────────────────┐                                                     │
│  │ CitationHandler │ ─── Format sources: [1], [Document 1], footnotes    │
│  └────────┬────────┘                                                     │
│           │                                                              │
│           ▼                                                              │
│  ┌─────────────────┐                                                     │
│  │ConversationMem  │ ─── Store turn for multi-turn conversations         │
│  └────────┬────────┘                                                     │
│           │                                                              │
│           ▼                                                              │
│  QueryResult { answer, sources, metadata }                               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Module Reference

### Core Module (`src/core/`)

| File | Purpose |
|------|---------|
| `base_interfaces.py` | 13 abstract base classes defining contracts |
| `config_loader.py` | Pydantic models for all configuration |
| `exceptions.py` | 12 specialized exception types |

**Key Interfaces:**
- `BaseVectorStore` - Vector database operations
- `BaseRetriever` - Document retrieval
- `BaseReranker` - Two-stage reranking
- `BaseContextCompressor` - CLaRa compression
- `BaseGenerator` - LLM generation
- `BaseRAGPipeline` - Full pipeline contract

### Indexing Module (`src/indexing/`)

| File | Purpose |
|------|---------|
| `milvus_manager.py` | `MilvusVectorStore` + `InMemoryVectorStore` |
| `milvus_vector_store.py` | `OptimizedMilvusVectorStore` with index selection |
| `embedding_service.py` | Multi-provider embeddings |
| `sparse_encoder.py` | BM25, TF-IDF, SPLADE for hybrid search |
| `index_builder.py` | Batch indexing orchestration |

**Supported Index Types:**
```python
IndexType.HNSW        # Best for <10M vectors, low latency
IndexType.IVF_FLAT    # Good for 10M-100M vectors
IndexType.IVF_SQ8     # Memory efficient
IndexType.IVF_PQ      # Maximum compression
IndexType.DISKANN     # Billion-scale, disk-based
IndexType.GPU_IVF_FLAT # GPU accelerated
```

### Retrieval Module (`src/retrieval/`)

#### Retrievers (`retrievers/`)
| Class | Description |
|-------|-------------|
| `DenseRetriever` | Vector similarity search |
| `MultiQueryRetriever` | Multiple query variations + fusion |
| `HybridRetriever` | Dense + BM25 with Reciprocal Rank Fusion |

#### Query Processing (`query_processing/`)
| Class | Description |
|-------|-------------|
| `QueryRewriter` | LLM-based query transformation |
| `HyDEQueryProcessor` | Hypothetical Document Embedding |
| `QueryExpander` | Multi-query generation, step-back, decomposition |

#### Compression (`compression/`)
| Class | Description |
|-------|-------------|
| `ContextCompressor` | CLaRa-inspired context reduction |

---

## Key Features

### 1. Zero Hardcoding
All parameters configurable via YAML:
```yaml
retriever:
  top_k: 10
  retrieval_method: hybrid
  dense_weight: 0.7
  sparse_weight: 0.3

reranker:
  enabled: true
  model_name: cross-encoder/ms-marco-MiniLM-L-6-v2
  top_n: 5
```

### 2. Multi-Provider Support
- **Embeddings**: OpenAI, HuggingFace, Cohere
- **LLMs**: OpenAI (GPT-4), Anthropic (Claude)
- **Vector Stores**: Milvus, In-Memory
- **Rerankers**: CrossEncoder, Cohere API

### 3. Adaptive Query Routing
7 query types with optimized settings:
| Query Type | Strategy | Features |
|------------|----------|----------|
| FACTUAL | Direct lookup | Dense retrieval, no rewriting |
| ANALYTICAL | Deep analysis | Hybrid, reranking, compression |
| COMPARATIVE | Multi-aspect | Query decomposition |
| PROCEDURAL | Step-by-step | Step-back prompting |
| CONVERSATIONAL | Context-aware | Conversation memory |
| EXPLORATORY | Broad search | Query expansion |
| UNCLEAR | Clarification | Fallback to factual |

### 4. Production Ready
- Comprehensive error handling with custom exceptions
- Structured logging with metrics
- Connection pooling for Milvus
- Embedding caching
- Retry logic with exponential backoff

---

## CLaRa Implementation

CLaRa (Context-aware Retrieval Augmentation) is implemented in `src/retrieval/compression/context_compressor.py`.

### Three Compression Methods

#### 1. LLM Extraction (`llm_extractor`)
Uses LLM to extract only relevant sentences:
```python
# Prompt template
"""Extract only the sentences from the following document
that are relevant to answering the question.

Question: {query}
Document: {content}

Relevant sentences:"""

# Result: Semantically filtered content
```

**Pros:** Best semantic understanding, highest quality
**Cons:** Higher latency, API costs per document

#### 2. Embeddings Filter (`embeddings_filter`)
Filters sentences by cosine similarity to query:
```python
# Algorithm:
1. Split document into sentences
2. Embed all sentences
3. Calculate cosine similarity with query
4. Keep sentences above threshold (default: 0.75)
```

**Pros:** Fast, no LLM calls, batch processing
**Cons:** May miss contextually important sentences

#### 3. LLM Chain Filter (`llm_chain_filter`)
Binary relevance judgment per document:
```python
# Prompt template
"""Is the following document relevant to answering the question?
Answer only 'yes' or 'no'.

Question: {query}
Document: {content}

Is relevant:"""

# Result: Keep or discard entire document
```

**Pros:** Quick filtering, preserves document integrity
**Cons:** All-or-nothing decision

### Configuration
```yaml
compression:
  enabled: true                    # Enable CLaRa
  method: llm_extractor            # llm_extractor | embeddings_filter | llm_chain_filter
  compression_ratio: 0.5           # Target ratio (0.1-1.0)
  similarity_threshold: 0.75       # For embeddings_filter
```

### Usage
```python
from src.retrieval.compression.context_compressor import ContextCompressor
from src.core.config_loader import CompressionConfig

config = CompressionConfig(enabled=True, method="embeddings_filter")
compressor = ContextCompressor(config, llm_service, embedding_service)

compressed_docs = compressor.compress(query, retrieved_docs)
# Returns documents with reduced content
```

---

## Reranker System

The reranker provides two-stage retrieval for improved precision, implemented in `src/retrieval/retrievers/reranker.py`.

### CrossEncoderReranker

Uses sentence-transformers cross-encoder model for scoring:

```python
from src.retrieval.retrievers.reranker import CrossEncoderReranker
from src.core.config_loader import RerankerConfig

config = RerankerConfig(
    enabled=True,
    model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",  # Fast, accurate
    top_n=5,
    relevance_threshold=0.0,
    use_gpu=False
)

reranker = CrossEncoderReranker(config)

# Rerank documents
reranked = reranker.rerank(
    query="What is machine learning?",
    documents=retrieved_docs,
    top_n=5
)
```

**How it works:**
1. Creates query-document pairs: `[(query, doc.content), ...]`
2. Cross-encoder scores each pair (considers full context)
3. Sorts by score descending
4. Filters by relevance threshold
5. Returns top-n documents with updated scores

**Available Models:**
| Model | Speed | Quality | Size |
|-------|-------|---------|------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Fast | Good | 80MB |
| `cross-encoder/ms-marco-MiniLM-L-12-v2` | Medium | Better | 120MB |
| `cross-encoder/ms-marco-TinyBERT-L-2-v2` | Fastest | Basic | 17MB |

### CohereReranker

Uses Cohere's commercial reranking API:

```python
from src.retrieval.retrievers.reranker import CohereReranker

reranker = CohereReranker(config, api_key_env="COHERE_API_KEY")
reranked = reranker.rerank(query, documents)
```

**Configuration:**
```yaml
reranker:
  enabled: true
  model_name: rerank-english-v3.0  # or rerank-multilingual-v3.0
  top_n: 5
  batch_size: 32
  relevance_threshold: 0.0
  use_gpu: false
```

---

## Quick Start

### Basic Usage

```python
from src.orchestration.rag_pipeline import RAGPipeline

# Initialize pipeline
pipeline = RAGPipeline(config_path="config/rag_config.yaml")

# Ingest documents
pipeline.ingest([
    "Machine learning is a subset of artificial intelligence...",
    "Neural networks are computational models inspired by the brain..."
])

# Or ingest from file
pipeline.ingest_file("documents/research.pdf")

# Query
result = pipeline.query("What is machine learning?")
print(result.answer)
print(f"Sources: {len(result.sources)}")
print(f"Latency: {result.total_latency_ms:.2f}ms")
```

### Using the CLI

```bash
python rag_cli.py

# Commands:
/load data/docs/           # Load documents
/info                      # Show pipeline configuration
/verbose                   # Toggle detailed output
/clear                     # Clear conversation history
/quit                      # Exit

# Then just type questions:
You> What is machine learning?
```

### Advanced Usage

```python
# Custom configuration
from src.core.config_loader import RAGConfig

config = RAGConfig(
    retriever=RetrieverConfig(
        retrieval_method="hybrid",
        top_k=20,
        dense_weight=0.7
    ),
    reranker=RerankerConfig(
        enabled=True,
        top_n=5
    ),
    compression=CompressionConfig(
        enabled=True,
        method="embeddings_filter"
    ),
    query_processor=QueryProcessorConfig(
        enabled=True,
        hyde=True,          # Enable HyDE
        step_back=True      # Enable step-back prompting
    )
)

pipeline = RAGPipeline(config=config)
```

---

## Configuration Reference

### Complete Configuration Structure

```yaml
# config/rag_config.yaml

# Vector Store
milvus:
  host: localhost
  port: 19530
  collection_name: rag_collection
  index_type: HNSW              # HNSW | IVF_FLAT | IVF_SQ8 | DISKANN
  metric_type: COSINE           # COSINE | L2 | IP
  index_params:
    M: 16
    efConstruction: 256

# Embeddings
embedding:
  provider: openai              # openai | huggingface | cohere
  model_name: text-embedding-3-small
  dimension: 1536
  batch_size: 32

# Retrieval
retriever:
  top_k: 10
  retrieval_method: hybrid      # dense | hybrid
  dense_weight: 0.7
  sparse_weight: 0.3
  rrf_k: 60
  similarity_threshold: 0.0

# Reranking
reranker:
  enabled: true
  model_name: cross-encoder/ms-marco-MiniLM-L-6-v2
  top_n: 5
  relevance_threshold: 0.0
  use_gpu: false

# Context Compression (CLaRa)
compression:
  enabled: false                # Enable for production
  method: llm_extractor         # llm_extractor | embeddings_filter | llm_chain_filter
  compression_ratio: 0.5
  similarity_threshold: 0.75

# LLM Generation
generator:
  provider: openai              # openai | anthropic
  model_name: gpt-4o-mini
  temperature: 0.1
  max_tokens: 1000

# Query Processing
query_processor:
  enabled: true
  rewriting: true               # LLM query enhancement
  hyde: false                   # Hypothetical document
  step_back: false              # Broader context queries
  decomposition: false          # Break complex queries

# Orchestration
orchestration:
  routing_enabled: true         # Query type classification
  max_iterations: 3

# Chunking
chunking:
  strategy: semantic            # fixed | recursive | semantic | sentence | markdown
  chunk_size: 1000
  chunk_overlap: 200

# Conversation
memory:
  enabled: true
  max_history: 10
```

---

## Integration Guide

### Integrating into Your Application

#### 1. As a Python Module

```python
# your_app/rag_service.py
from src.orchestration.rag_pipeline import RAGPipeline
from src.core.config_loader import RAGConfig

class RAGService:
    def __init__(self, config_path: str):
        self.pipeline = RAGPipeline(config_path=config_path)

    def answer_question(self, question: str, filters: dict = None):
        result = self.pipeline.query(question, filters=filters)
        return {
            "answer": result.answer,
            "sources": [s.metadata for s in result.sources],
            "latency_ms": result.total_latency_ms
        }

    def add_documents(self, texts: list[str], metadata: dict = None):
        return self.pipeline.ingest(texts, metadata=metadata)
```

#### 2. As a REST API (FastAPI example)

```python
from fastapi import FastAPI
from src.orchestration.rag_pipeline import RAGPipeline

app = FastAPI()
pipeline = RAGPipeline(config_path="config/rag_config.yaml")

@app.post("/query")
async def query(question: str):
    result = pipeline.query(question)
    return {"answer": result.answer, "sources": len(result.sources)}

@app.post("/ingest")
async def ingest(documents: list[str]):
    count = pipeline.ingest(documents)
    return {"ingested": count}
```

#### 3. Key Integration Points

| Component | Interface | Purpose |
|-----------|-----------|---------|
| `RAGPipeline` | `query()`, `ingest()` | Main entry points |
| `RAGConfig` | Pydantic model | Configuration management |
| `QueryResult` | Dataclass | Structured response |
| `Document` | Dataclass | Document representation |

---

## API Reference

### RAGPipeline

```python
class RAGPipeline:
    def __init__(
        self,
        config: Optional[RAGConfig] = None,
        config_path: Optional[str] = None,
        vector_store: Optional[BaseVectorStore] = None,
        embedding_service: Optional[EmbeddingService] = None,
        llm_service: Optional[LLMService] = None,
    )

    def query(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        return_sources: bool = True,
        verbose: bool = False,
    ) -> QueryResult

    def ingest(
        self,
        documents: Union[List[Document], List[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int

    def ingest_file(
        self,
        file_path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]

    def get_pipeline_info(self) -> Dict[str, Any]
    def clear_memory(self) -> None
```

### QueryResult

```python
@dataclass
class QueryResult:
    answer: str                           # Generated answer
    sources: List[Document]               # Source documents
    query: str                            # Original query
    processed_query: Optional[str]        # Transformed query
    query_type: Optional[str]             # Classification
    retrieval_latency_ms: float
    generation_latency_ms: float
    total_latency_ms: float
    metadata: Dict[str, Any]              # Additional info
```

### Document

```python
@dataclass
class Document:
    content: str                          # Text content
    metadata: Dict[str, Any]              # Source, timestamps, etc.
    id: Optional[str]                     # Unique identifier
    embedding: Optional[List[float]]      # Vector representation
    score: Optional[float]                # Relevance score
```

---

## Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...              # For embeddings and LLM

# Optional
ANTHROPIC_API_KEY=sk-ant-...       # For Claude
COHERE_API_KEY=...                 # For Cohere embeddings/reranker
MILVUS_HOST=localhost              # Override Milvus host
MILVUS_PORT=19530                  # Override Milvus port
```

---

## Dependencies

```
# Core
pydantic>=2.0
pydantic-settings>=2.0
pyyaml>=6.0

# Embeddings & LLMs
openai>=1.0
anthropic>=0.18
sentence-transformers>=2.2

# Vector Store
pymilvus>=2.3.0

# Utilities
numpy>=1.24
structlog>=23.0
python-dotenv>=1.0
```

Install all:
```bash
pip install -r requirements.txt
```

---

## Testing

```bash
# Run the CLI demo
python rag_cli.py --verbose

# Load test documents and query
python rag_cli.py --load data/docs/ --verbose
```

---

## License

MIT License - See LICENSE file for details.
