# Phase 4: RAG Integration — Implementation Plan

## Goal
Uploaded documents become searchable via the existing RAG pipeline, scoped to workspaces.
Existing CLI RAG usage remains unchanged.

---

## Current State of RAG Code

### Key Files
- `src/rag/vector_store.py` — `get_vectorstore()` returns `langchain_milvus.Milvus` with `enable_dynamic_field=True`, `auto_id=True`. Module-level `connections.connect()` to Milvus. Also has `clear_collection()`, `get_collection_info()`.
- `src/rag/rag_chain.py` — `RAGChain` class. `__init__` takes `collection_name` and `config`. Uses `get_vectorstore()`, `get_retriever()`, `compression_retriever()`. Methods: `query()`, `stream_query()`, `ingest_documents()`. Imports from `src.rag` (absolute).
- `src/rag/ingestion.py` — `load_documents()` (async gen via UnstructuredLoader), `document_splitter_()`, `format_citations()`. Citations use `doc.metadata.get("source", "unknown")`.
- `src/rag/retrieval/retrievers.py` — `get_retriever()` builds dense retriever via `vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": ...})`. Optionally adds BM25 hybrid + reranking.
- `src/config/config.py` — `RagConfig` with `milvus_host`, `milvus_port`, `milvus_collection_name="documents_v2"`, `chunk_size=1000`, `chunk_overlap=200`, `embedding_provider="openai"`, `embedding_model="text-embedding-3-small"`.
- `src/rag/__init__.py` — re-exports from generation, ingestion, retrieval, vector_store.

### Key Observations
1. Existing `get_vectorstore()` uses `enable_dynamic_field=True` — metadata fields are auto-created from first doc's metadata.
2. Dense retriever uses `search_kwargs={"k": N}` — Milvus `search_kwargs` also supports `"expr"` for filter expressions.
3. `RAGChain.__init__` builds the full chain once. `workspace_id` filtering needs to be applied per-query, not at init time.
4. `format_citations()` only uses `doc.metadata.get("source")` — needs to include `file_id` for uploaded files.
5. `connections.connect()` at module level in vector_store.py is fine — will be reused.

---

## Design Decisions

### 1. Separate Collection for Workspace Files
- Existing CLI uses collection `documents_v2` (from `global_rag_config.milvus_collection_name`).
- Workspace files use a NEW collection `talos_documents`.
- This avoids schema conflicts and keeps CLI backward-compatible.

### 2. Workspace Isolation via Milvus Filter Expressions
- All chunks get `workspace_id` in metadata.
- At query time, filter with `expr='workspace_id == "..."'` in `search_kwargs`.
- `enable_dynamic_field=True` means metadata fields are stored as dynamic fields in Milvus, and `expr` filters work on them.

### 3. RAGChain Workspace Filtering
- Add optional `workspace_id` parameter to `RAGChain.__init__()`.
- When set, the retriever's `search_kwargs` includes `expr` filter.
- The retriever is built with the filter baked in at init time (since RAGChain builds the chain once).
- For workspace-scoped usage, create a new RAGChain instance per workspace.

### 4. Document Processing Integration
- `processing/documents.py` currently chunks but doesn't insert into Milvus.
- Phase 4 adds `ingest_file_chunks()` in `src/rag/ingestion.py` that takes chunks and inserts via vectorstore.
- `process_document()` calls this after chunking.

### 5. File Deletion
- `delete_file_chunks()` in `vector_store.py` uses pymilvus `MilvusClient.delete()` with filter expression.
- Called from `FileService.soft_delete()`.

---

## Files to Modify

### 1. `src/rag/vector_store.py`
**Add:**
- `WORKSPACE_COLLECTION = "talos_documents"` constant
- `get_workspace_vectorstore()` — returns Milvus vectorstore for workspace files, same embeddings as existing, uses `talos_documents` collection
- `delete_file_chunks(file_id: str, collection_name: str = WORKSPACE_COLLECTION)` — deletes all chunks for a file_id using pymilvus `MilvusClient`

**Keep unchanged:** `get_vectorstore()`, `get_embeddings()`, `clear_collection()`, `get_collection_info()`

### 2. `src/rag/ingestion.py`
**Add:**
- `ingest_file_chunks(chunks: list[Document], workspace_id: str, file_id: str)` — enriches each chunk's metadata with workspace_id/file_id, inserts via workspace vectorstore

**Modify:**
- `format_citations()` — when `file_id` is in metadata, include it in citation output

**Keep unchanged:** `load_documents()`, `document_splitter()`, `document_splitter_()`

### 3. `src/rag/rag_chain.py`
**Modify `__init__`:**
- Add optional `workspace_id: str | None = None` parameter
- When set, use `get_workspace_vectorstore()` instead of `get_vectorstore()`
- Pass `search_kwargs={"expr": f'workspace_id == "{workspace_id}"'}` to retriever

**Keep unchanged:** `query()`, `stream_query()`, `ingest_documents()` signatures. The existing CLI usage (no workspace_id) still works.

### 4. `src/rag/retrieval/retrievers.py`
**Modify `get_retriever()`:**
- Accept optional `search_kwargs: dict | None = None` parameter
- Merge with default `{"k": config.retrieval_top_k}` when building dense retriever
- This allows caller to pass `expr` filter

### 5. `src/processing/documents.py`
**Modify `process_document()`:**
- After chunking, call `ingest_file_chunks()` to insert into Milvus
- Return chunks list for potential future use

### 6. `src/files/service.py`
**Modify `soft_delete()`:**
- After setting `deleted_at`, call `delete_file_chunks(file_id)` to remove from Milvus

### 7. `src/rag/__init__.py`
**Add to exports:** `ingest_file_chunks`, `delete_file_chunks`, `get_workspace_vectorstore`

---

## Files to Create

None. All changes are modifications to existing files.

---

## Exact Change Specifications

### `src/rag/vector_store.py` — additions at bottom of file

```python
WORKSPACE_COLLECTION = "talos_documents"


def get_workspace_vectorstore(
    collection_name: str = WORKSPACE_COLLECTION,
    embedding_provider: str | None = None,
    embeddings: Embeddings | None = None,
) -> VectorStore:
    """Get vectorstore for workspace-scoped file chunks."""
    if embeddings is None:
        embeddings = get_embeddings(embedding_provider)

    return Milvus(
        embedding_function=embeddings,
        collection_name=collection_name,
        auto_id=True,
        enable_dynamic_field=True,
        connection_args={
            "host": global_rag_config.milvus_host,
            "port": global_rag_config.milvus_port,
        },
    )


def delete_file_chunks(file_id: str, collection_name: str = WORKSPACE_COLLECTION):
    """Delete all vector chunks for a given file_id from Milvus."""
    from pymilvus import MilvusClient

    client = MilvusClient(
        uri=f"http://{global_rag_config.milvus_host}:{global_rag_config.milvus_port}"
    )

    if not utility.has_collection(collection_name):
        return

    client.delete(
        collection_name=collection_name,
        filter=f'file_id == "{file_id}"',
    )
```

### `src/rag/ingestion.py` — add function, modify format_citations

```python
def ingest_file_chunks(
    chunks: list[Document],
    workspace_id: str,
    file_id: str,
):
    """Insert document chunks into the workspace-scoped Milvus collection."""
    from src.rag.vector_store import get_workspace_vectorstore

    # Ensure all chunks have required metadata
    for chunk in chunks:
        chunk.metadata.setdefault("workspace_id", workspace_id)
        chunk.metadata.setdefault("file_id", file_id)

    vectorstore = get_workspace_vectorstore()
    vectorstore.add_documents(chunks)
```

In `format_citations()`, add file_id to citation when present:
```python
# After getting citation source:
file_id = doc.metadata.get("file_id")
filename = doc.metadata.get("filename")
if filename:
    page = doc.metadata.get("page_number", "")
    page_str = f", p.{page}" if page else ""
    citation = f"{filename}{page_str}"
    if file_id:
        citation += f" (file:{file_id})"
```

### `src/rag/rag_chain.py` — modify __init__

Add `workspace_id: str | None = None` to __init__ signature.
When workspace_id is set:
- Use `get_workspace_vectorstore()` instead of `get_vectorstore(collection_name)`
- Pass `search_kwargs={"expr": f'workspace_id == "{workspace_id}"'}` to `get_retriever()`

### `src/rag/retrieval/retrievers.py` — modify get_retriever

Add `search_kwargs: dict | None = None` parameter.
Merge into dense retriever's search_kwargs:
```python
base_search_kwargs = {"k": config.retrieval_top_k}
if search_kwargs:
    base_search_kwargs.update(search_kwargs)
dense_retriever = vectorstore.as_retriever(
    search_type="similarity", search_kwargs=base_search_kwargs
)
```

### `src/processing/documents.py` — add Milvus ingestion

After chunking, add:
```python
from rag.ingestion import ingest_file_chunks
ingest_file_chunks(chunks, str(file_record.workspace_id), str(file_record.id))
```

### `src/files/service.py` — add chunk deletion on soft_delete

In `soft_delete()`, after setting `deleted_at`:
```python
from rag.vector_store import delete_file_chunks
try:
    delete_file_chunks(str(file_id))
except Exception:
    logger.warning("Failed to delete file chunks from vector store", file_id=str(file_id))
```

---

## Dependencies

No new pip dependencies needed. Uses existing:
- `langchain_milvus` (already via `langchain`)
- `pymilvus` (already installed)
- `langchain_core` (already installed)

---

## Backward Compatibility Checklist

- [ ] `RAGChain(collection_name="documents_v2")` still works (no workspace_id → uses get_vectorstore)
- [ ] `get_vectorstore()` unchanged
- [ ] `load_documents()` unchanged
- [ ] `format_citations()` still works for docs without file_id (falls back to source)
- [ ] `get_retriever()` with no search_kwargs behaves identically
- [ ] CLI RAG usage untouched

---

## Risk Notes

1. **Module-level Milvus connection** in `vector_store.py` (`connections.connect(...)` at line 19-23) runs at import time. If Milvus is down, importing this module fails. This is pre-existing — not introduced by Phase 4.

2. **`ingest_file_chunks` is synchronous** — it calls `vectorstore.add_documents()` which embeds + inserts. This is called from the ARQ worker which is async but can tolerate sync blocking calls since it runs in a separate process.

3. **`delete_file_chunks` uses pymilvus MilvusClient** directly (not langchain) because langchain's Milvus wrapper doesn't expose delete-by-filter. The MilvusClient connection is short-lived (created per call).

4. **Dynamic fields in Milvus** — `enable_dynamic_field=True` means metadata fields (workspace_id, file_id, etc.) are stored but not indexed. Filter expressions (`expr`) on dynamic fields do a scan, not an index lookup. For large collections, consider adding scalar indexes later. Fine for graduation project scale.
