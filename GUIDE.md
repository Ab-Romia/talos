# Modular RAG System - Complete Guide

> **Note:** This system implements a production-ready Modular RAG architecture with CLaRa-inspired optimizations based on the [Modular RAG paper](https://arxiv.org/html/2407.21059v1) and Apple's [CLaRa research](https://arxiv.org/abs/2511.18659).

## Table of Contents
1. [What is RAG?](#what-is-rag)
2. [System Architecture](#system-architecture)
3. [CLaRa-Inspired Optimizations](#clara-inspired-optimizations)
4. [How It Works](#how-it-works)
5. [Setup Instructions](#setup-instructions)
6. [Configuration Guide](#configuration-guide)
7. [Extending the System](#extending-the-system)

---

## What is RAG?

RAG (Retrieval-Augmented Generation) is a technique that enhances LLM responses by providing relevant context from a knowledge base.

### The Problem RAG Solves

LLMs have inherent limitations:
- They don't know anything after their training cutoff
- They can't access your private data
- They sometimes hallucinate when uncertain
- They're expensive to fine-tune with new information

### The RAG Solution

RAG addresses these by:
1. Storing your information in a searchable vector database
2. Finding relevant documents when a question is asked
3. Providing those documents as context to the LLM
4. Generating grounded answers based on actual retrieved information

---

## System Architecture

This repository contains a **production-ready Modular RAG system** with the following components:

### Core Modules (`src/core/`)

#### Configuration Loader
- **Pydantic Models**: Type-safe, validated configuration for all components
- **YAML Support**: Load configuration from YAML files
- **Environment Variables**: Override settings via environment variables
- **Zero Hardcoding**: All parameters are configurable

#### Base Interfaces
- **Abstract Classes**: Define contracts for all swappable components
- **Type Hints**: Full type annotation throughout
- **Document Model**: Unified document representation with metadata

#### Exceptions
- **Custom Hierarchy**: Specific exceptions for different failure modes
- **Context Preservation**: Detailed error information for debugging

### Indexing Module (`src/indexing/`)

#### Milvus Vector Store
- **Production Ready**: Full Milvus integration with connection pooling
- **In-Memory Fallback**: For development and testing
- **Batch Operations**: Efficient bulk insert and search
- **Metadata Filtering**: Filter searches by document metadata

#### Embedding Service
- **Multi-Provider**: OpenAI, HuggingFace, Cohere support
- **Caching**: Embedding cache to reduce API calls
- **Batch Processing**: Efficient batch embedding generation
- **Normalization**: Optional L2 normalization

### Ingestion Module (`src/ingestion/`)

#### Document Loaders
- **Text Files**: Plain text with encoding support
- **PDF Files**: Page-aware extraction with pypdf
- **Markdown**: Structure-aware loading with title extraction
- **JSON/JSONL**: Configurable content and metadata fields
- **Directories**: Recursive loading with glob patterns

#### Chunking Strategies
- **Fixed Chunking**: Simple character-based splits with overlap
- **Recursive Chunking**: Hierarchical splitting by separators
- **Sentence Chunking**: Sentence boundary-aware splitting
- **Markdown Chunking**: Header-aware document splitting
- **Semantic Chunking**: Embedding-based natural breakpoints (CLaRa-inspired)

#### Metadata Extraction
- **Automatic Metadata**: Content hash, word count, timestamps
- **Keyword Extraction**: TF-based keyword extraction
- **File Metadata**: Size, creation time, modification time

### Retrieval Module (`src/retrieval/`)

#### Dense Retriever
- **Vector Similarity**: Cosine/L2/Inner product search
- **Top-K Retrieval**: Configurable result count
- **Metadata Filtering**: Filter by document attributes
- **Multi-Query**: Search with multiple query variations

#### Hybrid Retriever
- **Dense + Sparse**: Combines embedding and BM25 search
- **Reciprocal Rank Fusion (RRF)**: Score combination algorithm
- **Configurable Weights**: Adjust dense/sparse balance
- **Best of Both**: Semantic understanding + keyword matching

#### Cross-Encoder Reranker
- **Two-Stage Retrieval**: Retrieve broadly, rerank precisely
- **Sentence Transformers**: Uses cross-encoder models
- **Score-Based Filtering**: Minimum relevance threshold
- **GPU Support**: Optional GPU acceleration

#### Query Processing
- **Query Rewriting**: LLM-enhanced query reformulation
- **Query Expansion**: Generate multiple search variations
- **HyDE**: Hypothetical Document Embedding
- **Step-Back Prompting**: Generate broader context queries
- **Query Decomposition**: Break complex queries into sub-queries

#### Context Compression
- **LLM Extraction**: Extract relevant sentences using LLM
- **Embeddings Filter**: Similarity-based sentence filtering
- **Configurable Ratio**: Target compression level

### Generation Module (`src/generation/`)

#### LLM Service
- **OpenAI**: GPT-4, GPT-4o-mini, GPT-3.5-turbo
- **Anthropic**: Claude 3 models
- **Streaming**: Optional streaming responses
- **Retry Logic**: Automatic retry with exponential backoff

#### Prompt Builder
- **Template System**: YAML-based prompt templates
- **Context Formatting**: Document-aware context construction
- **Variable Substitution**: Dynamic prompt generation

#### Citation Handler
- **Source Tracking**: Track which documents were used
- **Citation Formatting**: Numbered, footnote, or inline styles
- **Excerpts**: Include relevant excerpts from sources

### Orchestration Module (`src/orchestration/`)

#### RAG Pipeline
- **End-to-End**: Complete query → answer flow
- **Ingestion**: Document loading and indexing
- **Configurable**: Enable/disable components via config
- **Metrics**: Latency tracking and logging

#### Query Router
- **7 Query Types**: FACTUAL, ANALYTICAL, COMPARATIVE, PROCEDURAL, CONVERSATIONAL, EXPLORATORY, UNCLEAR
- **Adaptive Pipelines**: Different settings per query type
- **Rule-Based**: Fast pattern matching classification

#### Conversation Memory
- **Turn Tracking**: Store questions, answers, and metadata
- **Context Summary**: Generate conversation summaries
- **Session Stats**: Track conversation statistics
- **Configurable History**: Limit stored turns

---

## CLaRa-Inspired Optimizations

This implementation adopts key principles from Apple's CLaRa research:

### 1. Semantic Chunking
Instead of fixed-size chunks, documents are split based on semantic similarity:
- Sentences are embedded
- Similarity between consecutive sentences is calculated
- Breakpoints are placed where similarity drops below threshold
- Results in more coherent, meaningful chunks

### 2. Two-Stage Retrieval
Improves relevance through a two-stage process:
1. **Stage 1 (Recall)**: Retrieve many candidates with fast bi-encoder
2. **Stage 2 (Precision)**: Rerank with accurate cross-encoder

### 3. Context Compression
Reduces context size while preserving relevant information:
- Extract only sentences relevant to the query
- Filter based on embedding similarity
- Achieve similar accuracy with less context

### 4. Query Enhancement
Improve retrieval through query transformation:
- Rewrite queries for better keyword coverage
- Expand queries with related terms
- Generate hypothetical documents (HyDE)

---

## How It Works

### Query Flow Example

When you ask: "How does semantic chunking work?"

1. **Query Router** classifies as ANALYTICAL
2. **Query Processor** rewrites: "semantic chunking document splitting embedding-based breakpoints"
3. **Hybrid Retriever** searches with both dense (embeddings) and sparse (BM25)
4. **RRF** combines results from both methods
5. **Reranker** scores each candidate with cross-encoder
6. **Context Compressor** (optional) extracts relevant sentences
7. **LLM Generator** produces answer with context
8. **Citation Handler** tracks sources
9. **Memory** stores the conversation turn

---

## Setup Instructions

### Prerequisites
- Python 3.10+
- OpenAI API key
- Optional: Milvus server for production

### Installation

```bash
# Clone repository
git clone https://github.com/Ab-romia/gp-artifact.git
cd gp-artifact

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Running

```bash
# Interactive CLI
python rag_cli.py

# Web application
python app.py

# Run examples
python examples/basic_qa.py
python examples/advanced_retrieval.py
```

---

## Configuration Guide

### Main Configuration (`config/rag_config_new.yaml`)

```yaml
# Pipeline type
pipeline_type: modular

# Knowledge base description (helps LLM understand context)
knowledge_base:
  description: "Your knowledge base description"
  domain: "Your domain"

# Embedding settings
embedding:
  provider: openai  # openai, huggingface, cohere
  model_name: text-embedding-3-small
  dimension: 1536

# Retrieval settings
retriever:
  top_k: 10
  retrieval_method: hybrid  # dense, sparse, hybrid
  dense_weight: 0.7
  sparse_weight: 0.3

# Reranker settings
reranker:
  enabled: true
  model_name: cross-encoder/ms-marco-MiniLM-L-6-v2
  top_n: 5

# Chunking settings
chunking:
  strategy: semantic  # fixed, recursive, semantic, sentence, markdown
  chunk_size: 1000
  chunk_overlap: 200

# Query processing
query_processor:
  enabled: true
  rewriting: true
  expansion: true
  hyde: false

# LLM settings
generator:
  provider: openai
  model_name: gpt-4o-mini
  temperature: 0.1
  max_tokens: 1000
```

### Prompt Templates (`config/prompts/`)

Create custom prompt templates in YAML:

```yaml
name: custom_prompt
description: My custom prompt

input_variables:
  - context
  - question

template: |
  Your custom prompt here with {context} and {question}.
```

---

## Extending the System

### Adding a New Embedding Provider

1. Create class extending `BaseEmbedding` in `src/indexing/embedding_service.py`
2. Implement `embed_query()`, `embed_documents()`, `get_dimension()`
3. Add to provider map in `create_embedding_service()`

### Adding a New Chunking Strategy

1. Create class extending `TextChunker` in `src/ingestion/chunking_strategies.py`
2. Implement `chunk()` method
3. Add to strategy map in `create_chunker()`

### Adding a New Document Loader

1. Create class extending `DocumentLoader` in `src/ingestion/document_loaders.py`
2. Implement `load()` and `supported_extensions`
3. Register in `DirectoryLoader` or `create_loader()`

### Adding a New LLM Provider

1. Create class extending `LLMService` in `src/generation/llm_service.py`
2. Implement `_call()`, `generate()`, `generate_stream()`
3. Add to provider map in `create_llm_service()`
