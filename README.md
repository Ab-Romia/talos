# Talos: AI-Powered Collaborative Workspace

A graduation project implementing a production-ready Retrieval-Augmented Generation (RAG) system with CLaRa-inspired optimizations and modular architecture for enhanced team collaboration and project management.

## Features

- **Zero Hardcoding**: All parameters configurable via YAML
- **CLaRa-Inspired Optimizations**: Semantic chunking, two-stage retrieval, context compression
- **Modular Architecture**: Swap providers, strategies, and components easily
- **Production Ready**: Error handling, logging, caching, retry logic
- **Adaptive Query Routing**: Automatic classification and optimized pipeline selection

## Quick Start

### Clone Repository

```bash
git clone https://github.com/Ab-romia/gp-artifact.git
cd gp-artifact
```

### Install Dependencies

> It is recommended to use [uv](https://docs.astral.sh/uv/).
> Install via `pip install uv`.

```bash
uv venv
uv sync
```

Or with pip:

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Set Environment Variables

Copy the example env file, then edit `.env`.

```bash
cp .env.example .env
```

Add your API keys:
```
OPENAI_API_KEY=your_openai_api_key_here
```

### Start Dev Database (Optional)

```bash
docker compose up -d
```

### Run the Application

```bash
# Run the RAG CLI (recommended for testing)
uv run rag_cli.py

# Or run with simple mode
uv run rag_cli.py --simple

# Run the web app
uv run app.py
```

## Documentation

- **[GUIDE.md](GUIDE.md)** - Complete architecture guide and walkthrough
- **[QUICKSTART.md](QUICKSTART.md)** - Quick reference for getting started
- **[src/README.md](src/README.md)** - Detailed module documentation
- **[docs/](docs/)** - Additional project documentation

## Architecture Overview

```
src/
├── core/                      # Configuration & base classes
│   ├── config_loader.py       # Pydantic models for all configs
│   ├── base_interfaces.py     # Abstract base classes
│   └── exceptions.py          # Custom exception hierarchy
│
├── indexing/                  # Vector storage & embeddings
│   ├── milvus_manager.py      # Milvus/InMemory vector stores
│   ├── embedding_service.py   # Multi-provider embeddings (OpenAI, HuggingFace, Cohere)
│   └── index_builder.py       # Index management
│
├── ingestion/                 # Document processing
│   ├── document_loaders.py    # Text, PDF, Markdown, JSON loaders
│   ├── chunking_strategies.py # Semantic, fixed, recursive chunking
│   └── pipeline.py            # Ingestion orchestration
│
├── retrieval/                 # Document retrieval
│   ├── retrievers/            # Dense, Hybrid (BM25+Dense), Reranker
│   ├── query_processing/      # Query rewriting, expansion, HyDE
│   └── compression/           # CLaRa-inspired context compression
│
├── generation/                # Response generation
│   ├── llm_service.py         # OpenAI, Anthropic support
│   ├── prompt_builder.py      # Template-based prompts
│   └── citation_handler.py    # Source citations
│
└── orchestration/             # Pipeline coordination
    ├── rag_pipeline.py        # Main RAG orchestrator
    ├── query_router.py        # Adaptive query routing (7 types)
    └── conversation_memory.py # Conversation state
```

## Key Components

### Retrieval Methods
- **Dense Retrieval**: Vector similarity search using embeddings
- **Hybrid Retrieval**: Dense + BM25 with Reciprocal Rank Fusion (RRF)
- **Cross-Encoder Reranking**: Two-stage retrieval for better relevance

### Chunking Strategies
- **Semantic Chunking**: Embedding-based natural breakpoints (CLaRa-inspired)
- **Recursive Chunking**: Hierarchical splitting by separators
- **Fixed/Sentence/Markdown Chunking**: Traditional approaches

### Query Processing
- **Query Rewriting**: LLM-enhanced query reformulation
- **Query Expansion**: Multi-query generation
- **HyDE**: Hypothetical Document Embedding
- **Step-back Prompting**: Broader context queries

### Query Routing
Automatic classification into 7 types with optimized pipeline settings:
- FACTUAL, ANALYTICAL, COMPARATIVE
- PROCEDURAL, CONVERSATIONAL
- EXPLORATORY, UNCLEAR

## Configuration

All settings in `config/rag_config_new.yaml`:

```yaml
# Embedding provider
embedding:
  provider: openai  # or huggingface, cohere
  model_name: text-embedding-3-small

# Retrieval settings
retriever:
  retrieval_method: hybrid  # or dense, sparse
  top_k: 10

# Reranking
reranker:
  enabled: true
  model_name: cross-encoder/ms-marco-MiniLM-L-6-v2

# Chunking strategy
chunking:
  strategy: semantic  # or fixed, recursive, sentence, markdown
  chunk_size: 1000
```

## Usage Example

```python
from src.orchestration.rag_pipeline import RAGPipeline

# Initialize pipeline
pipeline = RAGPipeline(config_path="config/rag_config_new.yaml")

# Ingest documents
pipeline.ingest(["Your document content here..."])

# Query
result = pipeline.query("What is in the documents?")
print(result.answer)
print(f"Sources: {len(result.sources)}")
```

## Examples

See the `examples/` directory:
- `basic_qa.py` - Simple Q&A demonstration
- `document_ingestion.py` - Document loading and chunking
- `advanced_retrieval.py` - Multi-stage retrieval comparison

## CLaRa-Inspired Optimizations

This implementation adopts key principles from Apple's CLaRa research:

1. **Semantic Chunking**: Documents split based on semantic similarity rather than fixed sizes
2. **Two-Stage Retrieval**: Dense retrieval → Cross-encoder reranking
3. **Context Compression**: Reduce context while preserving relevant information
4. **Query Enhancement**: LLM-based query rewriting and expansion

## Project Structure

```
gp-artifact/
├── app.py                    # FastAPI web application
├── rag_cli.py                # Interactive CLI
├── config/
│   ├── rag_config.yaml       # Legacy configuration
│   ├── rag_config_new.yaml   # New production configuration
│   └── prompts/              # Prompt templates
├── src/                      # New modular RAG implementation
├── modules/                  # Legacy modules (for reference)
├── examples/                 # Usage examples
├── docs/                     # Project documentation
└── requirements.txt          # Python dependencies
```

## Requirements

- Python 3.10+
- OpenAI API key (for embeddings and LLM)
- Optional: Milvus for production vector storage
- Optional: Docker for development database

## License

This project is part of a graduation project for Talos AI-Powered Collaborative Workspace.
