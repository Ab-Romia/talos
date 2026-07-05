import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import final

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from config import RAG_PROMPT
from config import global_rag_config as global_rag_config, RagConfig
from utils.logger import get_logger

from .ai_settings import OVERRIDABLE
from .retrieval.chat_selection import select_chat_context
from .trace import RagTrace

__all__ = ["RAGChain", "PreparedAsk"]

logger = get_logger(__name__)


@dataclass
class PreparedAsk:
    """Everything retrieval produced, ready for generation."""
    question: str
    context: str
    history: list = field(default_factory=list)


@final
class RAGChain:
    def __init__(
        self,
        collection_name: str,
        config: RagConfig = global_rag_config,
        workspace_id: str | None = None,
        file_ids: list[str] | None = None,
        chatroom_id: str | None = None,
        channel_ids: list[str] | None = None,
        chat_history: list | None = None,
        exclude_message_ids: set[str] | None = None,
        *,
        retriever=None,
        chat_retriever=None,
        llm=None,
        request_id: str | None = None,
        config_provenance: dict | None = None,
    ):
        from rag import (
            get_query_rewriter,
            get_hyde_embeddings,
            get_embeddings,
            get_vectorstore,
            get_workspace_vectorstore,
            build_rag_pipeline,
            get_llm,
        )

        self.collection_name = collection_name
        self.config = config
        self.config_provenance = dict(config_provenance or {})
        self.workspace_id = workspace_id
        self.request_id = request_id or ""
        self._retrieval_ms = 0.0
        self._generation_ms = 0.0
        self.file_ids = file_ids
        self.chatroom_id = chatroom_id
        self.channel_ids = channel_ids
        self.retrieved_docs: list[Document] = []
        self.chat_retriever = chat_retriever
        # Captured for debug/observability (the /ask debug flag reads these).
        self.last_context = ""
        self.last_chat_docs: list[Document] = []
        self.last_chat_selection: dict = {}
        # One structured record of what the last run used; filled by stream_query.
        self.trace = RagTrace()
        # Prior conversation turns supplied by the caller (the /ask endpoint loads
        # the channel's un-indexed tail). Injected into the answer prompt's
        # chat_history slot; the indexed body is recalled via chat_retriever.
        self._injected_history = list(chat_history) if chat_history else []
        # B5: message_ids already present in the injected tail (tier 1). A message
        # can briefly be in both tiers (its vector is in Milvus before its
        # indexed_at commit lands), so we drop those from chat recall to keep each
        # message in exactly one tier of the context.
        self._exclude_message_ids = set(exclude_message_ids or [])

        self.last_query_info = {}

        if retriever is not None:
            # Injected (test / embedding-free) path: skip all Milvus + LLM
            # building so the chain can be exercised without external services.
            self.query_rewriter = None
            self.hyde = None
            self.vectorstore = None
            self.retriever = retriever
        else:
            # Each of these is an extra LLM call per query; gate them by config.
            self.query_rewriter = get_query_rewriter(config=config) if config.use_query_rewrite else None
            self.hyde = get_hyde_embeddings(config=config) if config.use_hyde else None

            if workspace_id:
                self.vectorstore = get_workspace_vectorstore(embeddings=self.hyde)
                # source == "file" keeps chat-memory vectors out of file retrieval
                # in the shared talos_documents collection.
                parts = [f'workspace_id == "{workspace_id}"', 'source == "file"']
                if file_ids:
                    ids_csv = ", ".join(f'"{fid}"' for fid in file_ids)
                    parts.append(f"file_id in [{ids_csv}]")
                elif file_ids is not None:
                    # Caller passed an explicit EMPTY allow-list (permission
                    # scoping resolved to no accessible files) — match nothing
                    # rather than falling open to the whole workspace.
                    parts.append('file_id in ["__no_access__"]')
                # Kept for filename-directed refinement in _rewrite_and_retrieve
                # (same workspace + permission scope, narrowed to named files).
                self._file_expr = " && ".join(parts)
                extra_search_kwargs = {"expr": self._file_expr}

                # Per-channel long-term memory over this channel's indexed
                # messages. Uses BASE embeddings (not HyDE): hypothetical-document
                # expansion is tuned for corpus QA, not conversational recall.
                if chatroom_id:
                    chat_vs = get_workspace_vectorstore(embeddings=get_embeddings(config=config))
                    chat_expr = f'chatroom_id == "{chatroom_id}" && source == "chat"'
                    self.chat_retriever = chat_vs.as_retriever(
                        search_kwargs={"k": config.chat_recall_fetch_k, "expr": chat_expr}
                    )
                elif channel_ids:
                    # Workspace-wide surfaces (the AI Assistant page) recall chat
                    # memory across every channel the CALLER may view — the same
                    # tiered mechanism, permission-scoped instead of single-channel.
                    chat_vs = get_workspace_vectorstore(embeddings=get_embeddings(config=config))
                    ch_csv = ", ".join(f'"{cid}"' for cid in channel_ids)
                    chat_expr = f'chatroom_id in [{ch_csv}] && source == "chat"'
                    self.chat_retriever = chat_vs.as_retriever(
                        search_kwargs={"k": config.chat_recall_fetch_k, "expr": chat_expr}
                    )
            else:
                self.vectorstore = get_vectorstore(collection_name, embeddings=self.hyde)
                extra_search_kwargs = None

            self.retriever = build_rag_pipeline(
                config, self.vectorstore, search_kwargs=extra_search_kwargs
            )

        self.llm = llm if llm is not None else get_llm(config=config)

    @staticmethod
    def _files_named_in(question: str, docs) -> list[str]:
        """Filenames the question explicitly refers to, drawn from the retrieved
        docs' metadata. Full-name matches always count; extension-less stems only
        when long enough to be unambiguous (so a doc named test.pdf doesn't
        hijack every question containing the word 'test')."""
        q = question.lower()
        named: list[str] = []
        for d in docs:
            fn = (d.metadata.get("filename") or "").strip()
            if not fn or fn in named:
                continue
            stem = fn.rsplit(".", 1)[0]
            if fn.lower() in q or (len(stem) >= 5 and stem.lower() in q):
                named.append(fn)
        return named

    def _rewrite_and_retrieve(self, question: str):
        if self.query_rewriter is not None:
            result = self.query_rewriter.invoke({"query": question})
            rewritten = str(result) if isinstance(result.content, list) else result.content
            rewritten = rewritten.strip()
        else:
            rewritten = question  # skip the extra LLM call; retrieve on the raw query

        self.last_query_info["rewritten_query"] = rewritten

        docs = self.retriever.invoke(rewritten)

        # Filename-directed questions ("tell me about lab03.pdf") get retrieval
        # narrowed to the named file(s): the semantic top-k otherwise pads the
        # context — and the citations — with chunks from unrelated documents.
        named = self._files_named_in(question, docs)
        if named and getattr(self, "_file_expr", None) and self.vectorstore is not None:
            try:
                names_csv = ", ".join(f'"{n}"' for n in named)
                scoped_expr = f"{self._file_expr} && filename in [{names_csv}]"
                scoped = self.vectorstore.similarity_search(
                    rewritten, k=self.config.retrieval_top_k, expr=scoped_expr
                )
                if scoped:
                    docs = scoped
            except Exception:
                logger.warning("filename-scoped retrieval failed; keeping broad results",
                               named=named, exc_info=True)

        self.retrieved_docs = docs  # files only -> drives citations
        chat_docs = self._retrieve_chat(rewritten)
        self.last_chat_docs = chat_docs  # captured for debug
        return docs + chat_docs  # context sees files + channel memory

    def _retrieve_chat(self, query: str):
        """Channel-scoped chat memory. Never errors the answer -- an empty or
        missing chat corpus degrades to file-only context, but the failure is
        logged so a misconfig (missing collection, dim mismatch) doesn't hide
        silently as 'no memory'."""
        if not self.chat_retriever:
            return []
        try:
            docs = self.chat_retriever.invoke(query)
            fetched = len(docs)
            if self._exclude_message_ids:
                def _overlaps_tail(d):
                    ids = d.metadata.get("message_ids")
                    if ids is None:  # legacy per-message docs
                        mid = d.metadata.get("message_id")
                        ids = [mid] if mid else []
                    return any(i in self._exclude_message_ids for i in ids)
                docs = [d for d in docs if not _overlaps_tail(d)]
            dropped_tail = fetched - len(docs)
            sel_stats: dict = {}
            docs = select_chat_context(
                docs,
                k=self.config.chat_recall_k,
                now=datetime.now(timezone.utc),
                half_life_hours=self.config.chat_decay_half_life_hours,
                overlap_threshold=self.config.chat_recall_overlap_threshold,
                stats=sel_stats,
            )
            self.last_chat_selection = {
                "fetched": fetched,
                "dropped_tail": dropped_tail,
                "dropped_redundant": sel_stats.get("dropped_redundant", 0),
                "truncated": sel_stats.get("truncated", 0),
                "kept": len(docs),
            }
        except Exception:
            logger.warning("chat recall failed; degrading to file-only",
                           chatroom_id=self.chatroom_id, exc_info=True)
            self.last_chat_selection = {}
            return []
        return docs

    # TODO: use prompt template
    def _format_docs(self, docs):
        # Label each chunk with its origin. Without this the model cannot
        # connect a question that names a document ("the week 11 report") to
        # its unlabeled text and refuses despite perfect retrieval.
        parts = []
        for doc in docs:
            if doc.metadata.get("source") == "chat":
                header = "[from: channel conversation]"
            else:
                label = doc.metadata.get("filename") or "document"
                page = doc.metadata.get("page_number")
                header = f"[from: {label}" + (f", page {page}" if page else "") + "]"
            parts.append(f"{header}\n{doc.page_content}")
        self.last_context = "\n\n".join(parts)
        return self.last_context

    def _fill_trace(self, question: str, history_at_prompt: list) -> None:
        """Record exactly what this run used. history_at_prompt is the chat
        history the chain actually saw (captured before the turn is recorded)."""
        prompt = "\n\n".join(
            f"[{m.type}] {m.content}"
            for m in RAG_PROMPT.format_messages(
                context=self.last_context, question=question,
                chat_history=history_at_prompt)
        )
        effective = {k: getattr(self.config, k) for k in OVERRIDABLE}
        effective["use_hybrid_retrieval"] = self.config.use_hybrid_retrieval
        effective["compression_type"] = self.config.compression_type.value
        self.trace = RagTrace(
            model=self.config.openai_model,
            embedding_provider=self.config.embedding_provider,
            request_id=self.request_id,
            retrieval_ms=round(self._retrieval_ms, 1),
            generation_ms=round(self._generation_ms, 1),
            effective_config=effective,
            config_provenance=dict(self.config_provenance),
            original_query=question,
            rewritten_query=self.last_query_info.get("rewritten_query"),
            hyde_used=self.hyde is not None,
            file_candidates=[RagTrace.doc_summary(d) for d in self.retrieved_docs],
            chat_candidates=[RagTrace.doc_summary(d) for d in self.last_chat_docs],
            chat_selection=dict(self.last_chat_selection),
            injected_tail_size=len(self._injected_history),
            final_context=self.last_context,
            prompt=prompt,
        )

    def query(self, question: str, include_citations: bool = True) -> str:
        full_response = ""
        for chunk in self.stream_query(question, include_citations):
            full_response += chunk
        return full_response

    def prepare(self, question: str) -> PreparedAsk:
        """Run the retrieval half eagerly: rewrite -> retrieve (files + chat)
        -> format context. Raises on failure, which lets the HTTP layer turn
        Milvus/LLM-rewrite errors into a real error response BEFORE any
        response headers are sent."""
        self.last_query_info = {
            "original_query": question,
            "rewritten_query": None,
            "generated_queries": [],
            "retrieved_docs": [],
            "num_docs_retrieved": 0,
        }
        t0 = time.perf_counter()
        docs = self._rewrite_and_retrieve(question)
        context = self._format_docs(docs)
        self._retrieval_ms = (time.perf_counter() - t0) * 1000.0
        self.last_query_info["retrieved_docs"] = self.retrieved_docs
        self.last_query_info["num_docs_retrieved"] = len(self.retrieved_docs)
        return PreparedAsk(
            question=question,
            context=context,
            history=list(self._injected_history),
        )

    def stream_answer(self, prepared: PreparedAsk, include_citations: bool = True):
        """Generation half: stream LLM tokens for an already-prepared ask.
        Fills self.trace after the answer completes."""
        from rag import format_citations

        prompt_value = RAG_PROMPT.invoke({
            "context": prepared.context,
            "question": prepared.question,
            "chat_history": prepared.history,
        })
        t0 = time.perf_counter()
        for chunk in (self.llm | StrOutputParser()).stream(prompt_value):
            yield chunk
        self._generation_ms = (time.perf_counter() - t0) * 1000.0

        self._fill_trace(prepared.question, prepared.history)

        if include_citations:
            yield "\n\nSources:"
            for citation in format_citations(self.retrieved_docs):
                yield f"\n{citation}"

    def stream_query(self, question: str, include_citations: bool = True):
        """Back-compat wrapper: prepare + stream in one sync generator (used by
        query(), the eval harness, and scripts/debug_ask.py)."""
        prepared = self.prepare(question)
        yield from self.stream_answer(prepared, include_citations)

    async def ingest_documents(self, file_paths: list[str]):
        from rag import load_documents

        documents = [doc async for doc in load_documents(file_paths)]
        return self.vectorstore.add_documents(documents)
