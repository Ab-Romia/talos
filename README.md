# Talos: AI-Powered Collaborative RAG System

A production-ready full-stack application combining Retrieval-Augmented Generation (RAG) with collaborative workspaces. Built as a graduation project featuring CLaRa-inspired optimizations, modular architecture, and seamless frontend-backend integration.

## Overview

Talos transforms your documents into intelligent conversations. Upload files, ask questions, and get accurate answers with source citations - all within organized workspaces.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Talos Architecture                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────────────┐  │
│   │   React     │────▶│   FastAPI   │────▶│   RAG Pipeline      │  │
│   │   Frontend  │     │   Backend   │     │   (CLaRa-inspired)  │  │
│   └─────────────┘     └──────┬──────┘     └──────────┬──────────┘  │
│                              │                       │              │
│                              ▼                       ▼              │
│                       ┌─────────────┐     ┌─────────────────────┐  │
│                       │  PostgreSQL │     │   Vector Store      │  │
│                       │  Database   │     │   (Milvus/Memory)   │  │
│                       └─────────────┘     └─────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Features

### Core Features
- **RAG-Powered Chat**: Intelligent Q&A with document retrieval and source citations
- **Document Management**: Upload and process PDFs, text, markdown, and more
- **Workspaces**: Organize knowledge into separate projects/teams
- **Real-time Chat**: Conversational interface with AI assistant

### Technical Features
- **Zero Hardcoding**: All parameters configurable via YAML/environment
- **CLaRa-Inspired Optimizations**: Semantic chunking, two-stage retrieval, context compression
- **Modular Architecture**: Swap providers, strategies, and components easily
- **Production Ready**: Error handling, logging, caching, retry logic
- **Type Safety**: Pydantic models and TypeScript-ready API

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL (or Docker)
- OpenAI API key

### 1. Clone and Setup

```bash
git clone https://github.com/Ab-romia/gp-artifact.git
cd gp-artifact

# Copy environment configuration
cp .env.example .env
# Edit .env with your API keys and settings
```

### 2. Install Backend Dependencies

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

### 3. Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

### 4. Start Database

```bash
docker compose up -d
```

### 5. Run the Application

**Terminal 1 - Backend:**
```bash
# From project root
python -m backend.app
# Or: uv run -m backend.app
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

### 6. Access the Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/api/docs
- **Database Admin**: http://localhost:8080

## Project Structure

```
gp-artifact/
├── backend/                    # FastAPI Backend
│   ├── api/                    # API Layer
│   │   ├── routes/             # API Endpoints
│   │   │   ├── auth.py         # Authentication routes
│   │   │   ├── workspaces.py   # Workspace management
│   │   │   ├── chatrooms.py    # Chatroom management
│   │   │   ├── messages.py     # Chat with RAG integration
│   │   │   ├── documents.py    # Document upload/management
│   │   │   └── rag.py          # Direct RAG queries
│   │   ├── schemas/            # Pydantic request/response models
│   │   └── deps/               # Dependencies (auth, db)
│   ├── model/                  # SQLAlchemy Models
│   │   ├── identity.py         # User, Role, Permission, Session
│   │   └── messaging.py        # Workspace, Chatroom, Message
│   ├── services/               # Business Logic
│   │   └── rag_service.py      # RAG pipeline integration
│   ├── app/                    # Application utilities
│   │   └── auth.py             # Password hashing
│   └── app.py                  # FastAPI application entry
│
├── frontend/                   # React Frontend
│   ├── src/
│   │   ├── components/         # React components
│   │   │   └── chat-components/
│   │   │       ├── ChatContent.jsx
│   │   │       └── ChatSidebar.jsx
│   │   ├── context/            # React Context providers
│   │   │   ├── AuthContext.jsx
│   │   │   ├── WorkspaceContext.jsx
│   │   │   └── ChatContext.jsx
│   │   ├── services/           # API client
│   │   │   └── api.js
│   │   └── page/               # Page components
│   │       ├── LandingPage/
│   │       ├── LoginPage/
│   │       └── ChatPage/
│   └── package.json
│
├── src/                        # Modular RAG Implementation
│   ├── core/                   # Configuration & base classes
│   │   ├── config_loader.py    # Pydantic configuration models
│   │   ├── base_interfaces.py  # Abstract base classes
│   │   └── exceptions.py       # Custom exceptions
│   ├── indexing/               # Vector storage & embeddings
│   │   ├── milvus_manager.py   # Vector store implementations
│   │   └── embedding_service.py # Multi-provider embeddings
│   ├── ingestion/              # Document processing
│   │   ├── document_loaders.py # File loaders
│   │   └── chunking_strategies.py # Chunking methods
│   ├── retrieval/              # Document retrieval
│   │   ├── retrievers/         # Dense, Hybrid, Reranker
│   │   └── query_processing/   # Query enhancement
│   ├── generation/             # Response generation
│   │   └── llm_service.py      # LLM providers
│   └── orchestration/          # Pipeline coordination
│       └── rag_pipeline.py     # Main orchestrator
│
├── config/                     # Configuration files
│   ├── rag_config.yaml         # RAG pipeline configuration
│   └── prompts/                # Prompt templates
│
├── docker-compose.yaml         # Docker services
├── .env.example                # Environment template
└── requirements.txt            # Python dependencies
```

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login and get token |
| GET | `/api/auth/me` | Get current user |
| POST | `/api/auth/logout` | Logout |

### Workspaces
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/workspaces` | List workspaces |
| POST | `/api/workspaces` | Create workspace |
| GET | `/api/workspaces/{id}` | Get workspace |
| PATCH | `/api/workspaces/{id}` | Update workspace |
| DELETE | `/api/workspaces/{id}` | Delete workspace |

### Chatrooms
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/chatrooms` | List chatrooms |
| POST | `/api/chatrooms` | Create chatroom |
| GET | `/api/chatrooms/{id}` | Get chatroom |
| DELETE | `/api/chatrooms/{id}` | Delete chatroom |

### Messages & Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/messages` | List messages |
| POST | `/api/messages/chat` | Send message (RAG-powered) |
| POST | `/api/messages/chat/stream` | Stream chat response |
| DELETE | `/api/messages/{id}` | Delete message |

### Documents
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/documents/upload` | Upload document |
| GET | `/api/documents` | List documents |
| GET | `/api/documents/{id}/status` | Get ingestion status |
| DELETE | `/api/documents/{id}` | Delete document |

### RAG
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/rag/query` | Execute RAG query |
| GET | `/api/rag/config` | Get RAG configuration |
| GET | `/api/rag/health` | Health check |

## Configuration

### Environment Variables

Key variables in `.env`:

```bash
# Database
DATABASE_URL=postgresql://talos_app:password@localhost:5432/talos

# Security
JWT_SECRET=your-secret-key

# RAG System
OPENAI_API_KEY=sk-your-key

# CORS
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### RAG Configuration

Edit `config/rag_config.yaml`:

```yaml
embedding:
  provider: openai
  model_name: text-embedding-3-small

retriever:
  retrieval_method: hybrid  # dense, sparse, or hybrid
  top_k: 10

reranker:
  enabled: true
  model_name: cross-encoder/ms-marco-MiniLM-L-6-v2

chunking:
  strategy: semantic  # or fixed, recursive, sentence
  chunk_size: 1000
```

## Technology Stack

### Frontend
- **React 18** - UI framework
- **Vite** - Build tool
- **React Router** - Routing
- **Styled Components** - Styling
- **React Bootstrap** - UI components

### Backend
- **FastAPI** - Web framework
- **SQLAlchemy 2.0** - ORM
- **PostgreSQL** - Database
- **Pydantic** - Data validation

### RAG System
- **OpenAI** - Embeddings & LLM
- **Milvus** - Vector database (optional)
- **Sentence Transformers** - Cross-encoder reranking
- **BM25** - Sparse retrieval

## CLaRa-Inspired Optimizations

1. **Semantic Chunking**: Documents split based on embedding similarity at natural breakpoints
2. **Two-Stage Retrieval**: Dense retrieval followed by cross-encoder reranking
3. **Context Compression**: Reduce context while preserving relevant information
4. **Query Enhancement**: LLM-based query rewriting and expansion

## Development

### Running Tests

```bash
# Backend tests
pytest backend/tests/

# Frontend tests
cd frontend && npm test
```

### Code Quality

```bash
# Backend linting
ruff check .
black --check .

# Frontend linting
cd frontend && npm run lint
```

## Deployment

### Production Checklist

- [ ] Set secure `JWT_SECRET`
- [ ] Configure `DATABASE_URL` for production
- [ ] Set `CORS_ORIGINS` to production domains
- [ ] Enable HTTPS
- [ ] Configure rate limiting
- [ ] Set up monitoring/logging

### Docker Deployment

```bash
# Build and run all services
docker compose -f docker-compose.prod.yaml up -d
```

## Documentation

- **[GUIDE.md](GUIDE.md)** - Complete architecture guide
- **[QUICKSTART.md](QUICKSTART.md)** - Quick reference
- **[API Docs](http://localhost:8000/api/docs)** - Interactive API documentation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

This project is part of a graduation project for Talos AI-Powered Collaborative Workspace.

---

**Talos RAG System** - Graduation Project 2025
