# Talos RAG System

Modular Retrieval-Augmented Generation system built with LangChain, Milvus, and OpenAI. Graduation project.

## Architecture

```
Document → Ingestion → Chunking → Milvus Vector Store
                                        │
Query → Query Processing (Rewrite/HyDE) → Hybrid Retrieval (Dense + BM25)
                                        │
                                   Reranking (Cross-Encoder)
                                        │
                                   LLM Generation → Answer with Citations
```

**Key components:**
- **Hybrid retrieval** — dense (semantic) + sparse (BM25) search with reciprocal rank fusion
- **Cross-encoder reranking** — two-stage retrieval for precision
- **Query processing** — query rewriting, expansion, HyDE
- **Context compression** — LLM extraction or embedding-based filtering
- **Conversation memory** — multi-turn context awareness

## Setup

### Prerequisites

- Python 3.12+
- Docker
- OpenAI API key

### Install

```bash
git clone https://github.com/Ab-romia/gp-artifact.git
cd gp-artifact

cp .env.example .env
# Edit .env — set OPENAI_API_KEY at minimum

pip install uv
uv sync
```

### Start services

```bash
docker compose up -d
# Starts: PostgreSQL, Milvus (+ etcd, minio), Adminer
```

### Run

```bash
python rag_cli.py
```

## CLI Commands

```
/ingest <file_paths>  - Ingest documents (comma-separated paths)
/clear                - Clear all ingested documents
/help                 - Show help
/quit or /exit        - Exit
<your question>       - Ask a question about ingested documents
```

## Configuration

Runtime config is loaded from `.env` (via pydantic-settings). See `.env.example` for all available variables.

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `MILVUS_HOST` | `localhost` | Milvus host |
| `MILVUS_PORT` | `19530` | Milvus port |
| `USE_HYBRID_RETRIEVAL` | `true` | Enable hybrid search |
| `USE_RERANKING` | `true` | Enable cross-encoder reranking |
| `CHUNK_SIZE` | `1000` | Document chunk size |
| `CHUNK_OVERLAP` | `200` | Chunk overlap |

YAML prompt templates are in `config/prompts/`.

## Tests

```bash
pytest tests/ -v
```

## Tech Stack

- **LangChain** — RAG pipeline orchestration
- **Milvus** — vector database
- **OpenAI** — embeddings + generation
- **Pydantic** — configuration and validation
- **Docker Compose** — infrastructure (Milvus, PostgreSQL, MinIO, etcd)

## License

Graduation project — Talos, 2026.
