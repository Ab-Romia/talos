# Document Database (Vector Store)

The document database provides vector storage and similarity search capabilities for the RAG system using Milvus vector database with the pymilvus SDK.

## Functional Requirements

### Vector Storage

- The system shall store document embeddings as vectors with associated metadata.
- Each vector shall have a unique string identifier (VARCHAR, max 128 chars).
- Documents shall store content (VARCHAR, max 65535 chars) and JSON metadata.
- The system shall support sparse vectors for hybrid BM25-style search.

### Index Types

The system shall support multiple index types for different scale requirements:

**CPU Indexes:**
- **FLAT**: Brute-force search for small datasets (<100K vectors), 100% recall.
- **HNSW**: Graph-based ANN for <10M vectors, low latency, high recall.
  - M parameter: max connections per node (8-64).
  - efConstruction: build-time search width (64-512).
  - ef: search-time width (16-512).
- **IVF_FLAT**: Cluster-based search for 10M-100M vectors.
  - nlist: number of clusters.
  - nprobe: clusters to search at query time.
- **IVF_SQ8**: Memory-efficient with 8-bit scalar quantization.
- **IVF_PQ**: Maximum compression with product quantization.
- **DISKANN**: Billion-scale disk-based search.
- **AUTOINDEX**: Let Milvus auto-select based on data.

**GPU Indexes:**
- **GPU_IVF_FLAT**: GPU-accelerated IVF for high throughput.
- **GPU_IVF_PQ**: GPU-accelerated with product quantization.

### Similarity Metrics

- **L2**: Euclidean distance.
- **IP**: Inner product (for normalized vectors).
- **COSINE**: Cosine similarity (auto-normalizes).

### Collection Operations

- **Create Collection**: Define schema with fields (id, content, embedding, metadata).
- **Insert**: Add documents with embeddings in batches (optimal: 500-2000 per batch).
- **Search**: Find top-k nearest neighbors with optional metadata filters.
- **Hybrid Search**: Combine dense and sparse vectors with RRF or weighted ranking.
- **Delete**: Remove documents by ID expression.
- **Drop Collection**: Remove entire collection.

### Metadata Filtering

- Filter by string equality: `metadata["key"] == "value"`
- Filter by numeric comparison: `>=`, `<=`, `>`, `<`, `!=`
- Filter by list membership: `metadata["key"] in [values]`
- Range queries with gte, lte, gt, lt operators.

### Hybrid Search

- Combine dense (semantic) and sparse (BM25) vectors.
- Use RRF (Reciprocal Rank Fusion) or weighted ranking.
- Configurable alpha parameter for dense vs sparse weight.
- Requires Milvus 2.4+ for native sparse vector support.

## Non-Functional Requirements

### Performance

- Connection pooling with automatic reconnection.
- Retry logic with exponential backoff (3 retries).
- Collection caching for repeated access.
- Batch insertions with progress tracking.
- Search latency logging and statistics.

### Scalability

- Automatic index selection based on dataset size.
- Support for billion-scale datasets with DISKANN.
- GPU acceleration for high-throughput scenarios.

### Reliability

- Graceful error handling with custom exceptions.
- Connection health checks.
- Flush after batch insertions.

### Configurability

- Host/port via config or environment variables (MILVUS_HOST, MILVUS_PORT).
- Authentication via MILVUS_USER, MILVUS_PASSWORD.
- Configurable consistency level.
- Configurable index parameters per use case.

## Embedding Service

Multi-provider embedding support:

- **OpenAI**: text-embedding-3-small (1536 dim), with caching.
- **HuggingFace**: sentence-transformers models (e.g., all-MiniLM-L6-v2).
- **Cohere**: embed-english-v3.0 (1024 dim).

Features:
- Embedding cache to avoid redundant API calls.
- Batch processing with configurable batch size.
- Retry logic for rate limit handling.
- Vector normalization option.

## Chunking Strategies

Multiple chunking strategies for document ingestion:

- **Fixed**: Fixed-size chunks with overlap.
- **Recursive**: Split by multiple separators (paragraphs, sentences).
- **Sentence**: Group sentences until target size.
- **Markdown**: Respect markdown structure (headers, code blocks).
- **Semantic**: CLaRa-inspired chunking using embedding similarity to find natural breakpoints.

Configurable parameters:
- chunk_size, chunk_overlap, min_chunk_size, max_chunk_size.
- Breakpoint threshold for semantic chunking (percentile, standard_deviation, interquartile).

## Components Overview

| Component | Purpose |
|-----------|---------|
| OptimizedMilvusVectorStore | Production Milvus client with all features |
| MilvusVectorStore | Standard Milvus client |
| InMemoryVectorStore | Testing/development store |
| OpenAIEmbedding | OpenAI embedding service |
| HuggingFaceEmbedding | Local sentence-transformers |
| CohereEmbedding | Cohere embedding service |
| SemanticChunker | Embedding-based chunking |
| MarkdownChunker | Markdown-aware chunking |

## Collection Schema

| Field | Type | Description |
|-------|------|-------------|
| id | VARCHAR(128) | Primary key, unique document ID |
| content | VARCHAR(65535) | Document text content |
| embedding | FLOAT_VECTOR | Dense embedding vector |
| sparse_embedding | SPARSE_FLOAT_VECTOR | Sparse vector for hybrid search [TODO] |
| metadata | JSON | Flexible metadata storage |

## Index Configuration Presets

| Preset | Use Case | Key Parameters |
|--------|----------|----------------|
| hnsw_balanced | General (<10M) | M=16, efConstruction=256, ef=64 |
| hnsw_high_recall | Accuracy-critical | M=32, efConstruction=512, ef=256 |
| hnsw_low_latency | Real-time apps | M=8, efConstruction=128, ef=32 |
| ivf_flat_medium | 10M-100M vectors | nlist=1024, nprobe=16 |
| ivf_sq8_memory | Memory-constrained | nlist=2048, nprobe=32 |
| diskann_billion | Billion-scale | Auto-configured |
