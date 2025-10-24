

# Modular RAG Framework

A graduation project implementing Retrieval-Augmented Generation (RAG) systems with a modular architecture.

## Quick Start

```bash
# Clone and setup
git clone <repo-url>
cd gp-artifact
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Run the Modular RAG system (default)
python main.py

# Or run the simple RAG baseline
python main.py --simple
```

## Documentation

- **[GUIDE.md](GUIDE.md)** - Complete guide with explanations, architecture, and walkthrough
- **[QUICKSTART.md](QUICKSTART.md)** - Quick reference for getting started
- **[NEXT_STEPS.md](NEXT_STEPS.md)** - Roadmap for implementing Modular RAG

## Current Implementation

This repository now contains a **fully functional Modular RAG system** based on the [Modular RAG paper](https://arxiv.org/html/2407.21059v1):

### Knowledge Base

The system comes with a **team workspace knowledge base** containing:
- Project overview, goals, and timeline
- Team member information and roles
- Sprint plans and milestone tracking
- Meeting notes and decisions
- Task assignments and deadlines
- Technical architecture and development guidelines
- Issues, blockers, and resolutions

This makes the system immediately useful for team collaboration and project management queries.

### Simple RAG (Baseline)
- Dense retrieval using OpenAI embeddings
- In-memory vector storage with cosine similarity
- LLM-based answer generation
- Interactive CLI interface

### Modular RAG (New!)
- **Query Router**: Automatically classifies queries and routes to optimal pipeline (workspace-aware)
- **Query Processor**: Rewrites and expands queries for better retrieval
- **Conversation Memory**: Tracks chat history for context-aware responses
- **Dense Retriever**: Semantic search with OpenAI embeddings
- **Cross-Encoder Reranker**: Improves relevance of retrieved documents
- **LLM Generator**: Context-aware generation that understands it's querying a team workspace
- **YAML Configuration**: Easy customization of all components including knowledge base context

## Module Architecture

### `modules/retriever/`
Handles document retrieval from various sources.

**Implemented:**
- Dense retrieval with OpenAI embeddings (`text-embedding-3-small`)
- Cosine similarity search

**Future:**
- Sparse retrieval (BM25, TF-IDF)
- Hybrid retrieval strategies
- FAISS integration for efficient vector search

### `modules/generator/`
Generates answers from retrieved context.

**Implemented:**
- OpenAI GPT-4o-mini integration
- Context-aware prompt templating

**Future:**
- Multiple LLM providers (Anthropic, local models)
- Advanced prompt engineering
- Streaming responses

### `modules/reranker/`
Reranks retrieved documents to improve relevance.

**Implemented:**
- Cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
- Score-based filtering

**Future:**
- LLM-based reranking
- Multiple reranking strategies

### `modules/pre_retrieval/`
Processes queries before retrieval. *(New!)*

**Implemented:**
- Query rewriting for clarity
- Query expansion with related terms
- Multi-query generation

### `modules/orchestration/`
Routes queries to optimal pipelines. *(New!)*

**Implemented:**
- Query type classification (factual, complex, conversational, unclear)
- Adaptive pipeline configuration
- Per-query-type optimization

### `modules/config/`
Configuration management. *(New!)*

**Implemented:**
- YAML-based configuration
- Module enable/disable controls
- Per-module parameter settings

### `modules/memory/`
Conversation memory and context tracking. *(New!)*

**Implemented:**
- Conversation history storage
- Context-aware query resolution
- Session statistics tracking
- Automatic conversation context integration

### `modules/evaluator/`
Evaluates pipeline performance. *(Future)*

**Planned:**
- Retrieval metrics (MRR, NDCG, Recall@K)
- Generation metrics (BLEU, ROUGE, faithfulness)
- End-to-end pipeline benchmarking

## Tech Stack

- **Language:** Python 3.8+
- **Embeddings:** OpenAI API (`text-embedding-3-small`)
- **Generation:** OpenAI API (`gpt-4o-mini`)
- **Reranking:** Sentence-Transformers (Cross-Encoder)
- **Vector Operations:** NumPy
- **Configuration:** python-dotenv, PyYAML

## Project Structure

```
gp-artifact/
├── main.py                          # Application entry point (Simple RAG)
├── modular_rag.py                   # Modular RAG implementation
├── modules/                         # Core modules
│   ├── retriever/                   # Retrieval implementations
│   │   └── dense_retriever.py      # ✓ OpenAI embeddings
│   ├── generator/                   # Generation implementations
│   │   └── llm_generator.py        # ✓ GPT-4o-mini (context-aware)
│   ├── reranker/                    # Reranking module
│   │   └── cross_encoder_reranker.py # ✓ Cross-encoder reranking
│   ├── pre_retrieval/               # Query processing (NEW!)
│   │   └── query_processor.py      # ✓ Query rewriting/expansion/resolution
│   ├── orchestration/               # Query routing (NEW!)
│   │   └── query_router.py         # ✓ Query classification
│   ├── memory/                      # Conversation memory (NEW!)
│   │   └── conversation_memory.py  # ✓ Chat history tracking
│   ├── config/                      # Configuration (NEW!)
│   │   └── config_loader.py        # ✓ YAML config loader
│   └── evaluator/                   # Evaluation (future)
├── config/
│   └── rag_config.yaml              # ✓ System configuration
├── data/
│   └── raw/knowledge_base.txt       # Knowledge base
├── GUIDE.md                         # Complete documentation
├── NEXT_STEPS.md                    # Future roadmap
└── requirements.txt                 # Dependencies
```

## For Team Members

**First time setup?** Read [GUIDE.md](GUIDE.md) for:
- Understanding how RAG works
- Architecture explanation
- Complete setup instructions
- Code walkthrough
- Extension ideas

## Using Modular RAG

### Running the System

```bash
# Default: Run with Modular RAG
python main.py

# Run with Simple RAG (baseline)
python main.py --simple
```

### Configuration

Edit `config/rag_config.yaml` to customize the system:

```yaml
# Enable/disable components
reranker:
  enabled: true  # Set to false to disable reranking

query_processor:
  enabled: true  # Set to false to disable query processing
  expansion: true
  rewriting: true

orchestration:
  routing_enabled: true  # Set to false to disable query routing

memory:
  max_history: 10  # Number of conversation turns to remember

knowledge_base:
  description: "the team's graduation project workspace..."
  domain: "team collaboration and project management"
```

### Example Queries

The system understands it's working with a team workspace. Try queries like:
- "Who is the team lead?"
- "What are our current blockers?"
- "When is the next sprint review?"
- "What tasks is Mohamed working on?"
- "Summarize the last meeting"
- "What's our deadline for the midterm presentation?"

### Special Commands

When using Modular RAG, you can use these commands:

- `/clear` - Clear conversation history
- `/stats` - Show conversation statistics
- `/history` - Display full conversation history

### How It Works

1. **Query Classification**: The router analyzes your question type
   - Factual: "What is Python?" → Simple pipeline
   - Complex: "Compare Python and Java" → Enhanced pipeline with query expansion
   - Conversational: "Tell me more" → Uses conversation context
   - Unclear: "tell me about that" → Pipeline with query rewriting

2. **Conversation Context**:
   - Tracks previous questions and answers
   - Resolves follow-up questions using conversation history
   - Example: After asking "What is Python?", you can ask "What is it used for?"

3. **Query Processing** (if enabled):
   - Resolves conversational references using chat history
   - Rewrites unclear queries for clarity
   - Expands queries with related terms

4. **Retrieval**:
   - Searches knowledge base using semantic similarity
   - Returns top-K most relevant documents

5. **Reranking** (if enabled):
   - Uses cross-encoder to rerank results
   - Improves relevance of final context

6. **Generation**:
   - Generates answer using retrieved context
   - Includes conversation history for continuity
   - Uses GPT-4o-mini by default

### What's Next

**See [NEXT_STEPS.md](NEXT_STEPS.md) for future enhancements:**
- Hybrid retrieval (BM25 + dense)
- Multi-hop retrieval for complex questions
- Evaluation metrics and benchmarking
- Advanced indexing strategies

