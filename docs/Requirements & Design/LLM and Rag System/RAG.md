# RAG System

The Retrieval-Augmented Generation (RAG) system provides intelligent document retrieval and response generation for the workspace. It enables users to query information from their workspace documents and receive contextually relevant answers.

## Functional Requirements

### Document Ingestion

- The system shall load and process documents from workspace data sources.
- Documents shall be chunked by logical sections (headers, paragraphs) to maintain context.
- The system shall create dense embeddings for each document chunk using the configured embedding model.
- A BM25 index shall be created for sparse keyword-based retrieval.

### Query Processing (Pre-Retrieval)

- The system shall support query rewriting to fix typos and grammar issues.
- The system shall support query expansion to add related terms.
- The system shall support HyDE (Hypothetical Document Embeddings) to generate hypothetical answers for improved retrieval.
- The system shall support step-back prompting to generate broader context queries.
- The system shall support query decomposition to break complex queries into sub-queries.
- The system shall resolve conversational references (pronouns, "it", "that") using conversation history.

### Query Routing

The system shall classify queries into the following types:
- Factual: Direct questions asking for specific facts.
- Analytical: Questions requiring analysis or explanation.
- Comparative: Questions comparing multiple items.
- Procedural: Questions about processes or steps.
- Conversational: Follow-up or context-dependent queries.
- Exploratory: Questions seeking broad information or lists.
- Unclear: Vague or ambiguous questions.

Each query type shall be routed to an appropriate pipeline configuration with optimized retrieval parameters.

### Retrieval

- The system shall support three retrieval methods:
  - Dense retrieval using semantic embeddings (cosine similarity).
  - Sparse retrieval using BM25 keyword matching.
  - Hybrid retrieval combining both methods.
- Hybrid retrieval shall use Reciprocal Rank Fusion (RRF) to combine results.
- The system shall support multi-query retrieval using query variations.
- The system shall support HyDE retrieval using hypothetical documents for dense search.
- Configurable weights shall control the balance between dense and sparse retrieval.

### Reranking

- The system shall optionally rerank retrieved documents using a cross-encoder model.
- The reranker shall score query-document pairs for relevance.
- The top-N most relevant documents shall be passed to generation.

### Response Generation

- The system shall generate responses using an LLM with retrieved context.
- The generator shall consider conversation history for context continuity.
- Responses shall be grounded in the retrieved documents.
- The system shall provide guidelines for the LLM to cite relevant information.

### Conversation Memory

- The system shall maintain conversation history within a session.
- History shall include questions, answers, retrieved context, and metadata.
- The system shall support a configurable maximum history length.
- Conversation context shall be available for query resolution and generation.

### Iterative Refinement

- For complex queries, the system shall support iterative refinement.
- Answer completeness shall be assessed after each iteration.
- Refined queries shall be generated to fill information gaps.
- Iterations shall continue until quality threshold is met or max iterations reached.

## Non-Functional Requirements

### Performance

- Document embedding creation shall process chunks in batches with progress indication.
- Retrieval shall return results efficiently for real-time query response.
- The reranker shall process documents quickly without significant latency.

### Configurability

- All major components shall be configurable via YAML configuration file.
- Configuration options shall include:
  - Embedding model selection
  - Dense/sparse weight balance
  - Reranker model and top-N setting
  - Query processor transformation toggles
  - Orchestration routing and iteration settings
  - Memory history length

### Modularity

- Each component (retriever, reranker, generator, query processor, router, memory) shall be independent.
- Components shall be optional and can be enabled/disabled via configuration.
- The system shall support swapping components without affecting others.

### Extensibility

- New query transformation strategies can be added to the query processor.
- New query types can be added to the router.
- Custom retrieval methods can be implemented by extending the retriever.

## Components Overview

### Core Pipeline (main branch)

| Component | Purpose |
|-----------|---------|
| HybridRetriever | Combines BM25 and dense retrieval with RRF fusion |
| CrossEncoderReranker | Reranks documents using cross-encoder scoring |
| QueryProcessor | Applies pre-retrieval transformations (rewrite, expand, HyDE, etc.) |
| QueryRouter | Classifies queries and determines pipeline configuration |
| LLMGenerator | Generates responses using LLM with context |
| ConversationMemory | Manages session history and context |
| ModularRAG | Orchestrates all components into a unified pipeline |

### Extended Architecture (rag_arc branch)

| Component | Purpose |
|-----------|---------|
| RAGPipeline | Full orchestration with ingestion, retrieval, generation |
| OptimizedMilvusVectorStore | Production Milvus client with hybrid search |
| EmbeddingService | Multi-provider embeddings (OpenAI, HuggingFace, Cohere) |
| SemanticChunker | CLaRa-inspired chunking using embedding similarity |
| ContextCompressor | Compress retrieved context for LLM [TODO] |
| CitationHandler | Handle source citations in responses [TODO] |
| PromptBuilder | Build prompts with context and history [TODO] |

## Integration with Platform [TODO]

- Workspace-scoped document retrieval
- Permission-based access to documents
- Real-time indexing of new messages
- AI assistant message delivery
