# Quick Start Guide

Get up and running with the Modular RAG system in minutes.

## Setup

### 1. Install Dependencies

```bash
# Using uv (recommended)
uv venv && uv sync

# Or using pip
pip install -r requirements.txt
```

### 2. Configure API Key

```bash
cp .env.example .env
```

Edit `.env` and add your OpenAI API key:
```
OPENAI_API_KEY=your_api_key_here
```

## Running the System

### Interactive CLI

```bash
# Run with Modular RAG (default, recommended)
python rag_cli.py

# Run with Simple RAG (baseline)
python rag_cli.py --simple
```

### Web Application

```bash
python app.py
```

### Using the New RAG Pipeline

```python
from src.orchestration.rag_pipeline import RAGPipeline

# Initialize
pipeline = RAGPipeline(config_path="config/rag_config_new.yaml")

# Ingest documents
pipeline.ingest(["Document 1 content", "Document 2 content"])

# Query
result = pipeline.query("Your question here")
print(result.answer)
```

## Project Structure

```
gp-artifact/
├── rag_cli.py                    # Interactive CLI
├── app.py                        # Web application
├── config/
│   ├── rag_config.yaml           # Legacy config
│   ├── rag_config_new.yaml       # New production config
│   └── prompts/                  # Prompt templates
├── src/                          # New modular implementation
│   ├── core/                     # Config, interfaces, exceptions
│   ├── indexing/                 # Vector store, embeddings
│   ├── ingestion/                # Document loaders, chunking
│   ├── retrieval/                # Retrievers, reranker, query processing
│   ├── generation/               # LLM, prompts, citations
│   └── orchestration/            # Pipeline, router, memory
├── modules/                      # Legacy modules
├── examples/                     # Usage examples
└── docs/                         # Documentation
```

## Key Components

### Retrieval Methods
- **Dense**: Vector similarity search
- **Hybrid**: Dense + BM25 with RRF fusion
- **Reranking**: Two-stage with cross-encoder

### Chunking Strategies
- **Semantic**: Embedding-based breakpoints (recommended)
- **Recursive**: Hierarchical by separators
- **Fixed**: Simple character-based

### Query Processing
- **Rewriting**: LLM-enhanced reformulation
- **Expansion**: Multi-query generation
- **HyDE**: Hypothetical document embedding

## Configuration

Edit `config/rag_config_new.yaml`:

```yaml
# Retrieval settings
retriever:
  retrieval_method: hybrid  # dense, sparse, hybrid
  top_k: 10

# Reranker
reranker:
  enabled: true
  top_n: 5

# Chunking
chunking:
  strategy: semantic  # fixed, recursive, semantic

# Query processing
query_processor:
  enabled: true
  rewriting: true
  expansion: true
```

## CLI Commands

In the interactive CLI:
- `/clear` - Clear conversation history
- `/stats` - Show session statistics
- `/history` - Display conversation history
- `exit` or `quit` - Exit the CLI

## Examples

### Run Example Scripts

```bash
# Basic Q&A
python examples/basic_qa.py

# Document ingestion
python examples/document_ingestion.py

# Advanced retrieval comparison
python examples/advanced_retrieval.py
```

### Code Examples

```python
# Ingest a file
pipeline.ingest_file("path/to/document.pdf")

# Query with verbose output
result = pipeline.query("question", verbose=True)

# Get pipeline info
info = pipeline.get_pipeline_info()
print(info)

# Clear conversation memory
pipeline.clear_memory()
```

## Next Steps

1. Read the full [GUIDE.md](GUIDE.md) for architecture details
2. Explore [src/README.md](src/README.md) for module documentation
3. Check [examples/](examples/) for more usage patterns
4. Review [config/rag_config_new.yaml](config/rag_config_new.yaml) for all options
