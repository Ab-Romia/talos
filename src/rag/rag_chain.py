from typing import final

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import (
    RunnablePassthrough,
    RunnableParallel,
    RunnableLambda,
)

from config import RAG_PROMPT
from config import global_rag_config as global_rag_config, RagConfig
from utils.logger import get_logger

from .trace import RagTrace

__all__ = ["RAGChain"]

logger = get_logger(__name__)


@final
class RAGChain:
    def __init__(
        self,
        collection_name: str,
        config: RagConfig = global_rag_config,
        workspace_id: str | None = None,
        file_ids: list[str] | None = None,
        chatroom_id: str | None = None,
        chat_history: list | None = None,
        exclude_message_ids: set[str] | None = None,
        *,
        retriever=None,
        chat_retriever=None,
        llm=None,
    ):
        from rag import (
            get_query_rewriter,
            get_hyde_embeddings,
            get_embeddings,
            get_vectorstore,
            get_workspace_vectorstore,
            build_rag_pipeline,
            get_llm,
            get_memory,
        )

        self.collection_name = collection_name
        self.config = config
        self.workspace_id = workspace_id
        self.file_ids = file_ids
        self.chatroom_id = chatroom_id
        self.retrieved_docs: list[Document] = []
        self.chat_retriever = chat_retriever
        # Captured for debug/observability (the /ask debug flag reads these).
        self.last_context = ""
        self.last_chat_docs: list[Document] = []
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
                extra_search_kwargs = {"expr": " && ".join(parts)}

                # Per-channel long-term memory over this channel's indexed
                # messages. Uses BASE embeddings (not HyDE): hypothetical-document
                # expansion is tuned for corpus QA, not conversational recall.
                if chatroom_id:
                    chat_vs = get_workspace_vectorstore(embeddings=get_embeddings(config=config))
                    chat_expr = f'chatroom_id == "{chatroom_id}" && source == "chat"'
                    self.chat_retriever = chat_vs.as_retriever(
                        search_kwargs={"k": config.chat_recall_k, "expr": chat_expr}
                    )
            else:
                self.vectorstore = get_vectorstore(collection_name, embeddings=self.hyde)
                extra_search_kwargs = None

            self.retriever = build_rag_pipeline(
                config, self.vectorstore, search_kwargs=extra_search_kwargs
            )

        self.llm = llm if llm is not None else get_llm(config=config)
        self.memory = get_memory(use_memory=config.conversation_memory_k > 0)
        self.chain = (
                RunnableParallel(
                    {
                        "context": RunnableLambda(self._rewrite_and_retrieve)
                                   | RunnableLambda(self._format_docs),
                        "question": RunnablePassthrough(),
                        "chat_history": RunnableLambda(
                            lambda _: self._injected_history + self.memory.messages
                        ),
                    }
                )
                | RAG_PROMPT
                | self.llm
                | StrOutputParser()
        )

    def _rewrite_and_retrieve(self, question: str):
        if self.query_rewriter is not None:
            result = self.query_rewriter.invoke({"query": question})
            rewritten = str(result) if isinstance(result.content, list) else result.content
            rewritten = rewritten.strip()
        else:
            rewritten = question  # skip the extra LLM call; retrieve on the raw query

        self.last_query_info["rewritten_query"] = rewritten

        docs = self.retriever.invoke(rewritten)
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
        except Exception:
            logger.warning("chat recall failed; degrading to file-only",
                           chatroom_id=self.chatroom_id, exc_info=True)
            return []
        if self._exclude_message_ids:
            docs = [d for d in docs
                    if d.metadata.get("message_id") not in self._exclude_message_ids]
        return docs

    # TODO: use prompt template
    def _format_docs(self, docs):
        self.last_context = "\n\n".join(doc.page_content for doc in docs)
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
        self.trace = RagTrace(
            model=self.config.openai_model,
            embedding_provider=self.config.embedding_provider,
            effective_config={
                "use_hyde": self.config.use_hyde,
                "use_query_rewrite": self.config.use_query_rewrite,
                "use_reranking": self.config.use_reranking,
                "use_hybrid_retrieval": self.config.use_hybrid_retrieval,
                "compression_type": self.config.compression_type.value,
                "retrieval_top_k": self.config.retrieval_top_k,
                "rerank_fetch_k": self.config.rerank_fetch_k,
            },
            original_query=question,
            rewritten_query=self.last_query_info.get("rewritten_query"),
            hyde_used=self.hyde is not None,
            file_candidates=[RagTrace.doc_summary(d) for d in self.retrieved_docs],
            chat_candidates=[RagTrace.doc_summary(d) for d in self.last_chat_docs],
            injected_tail_size=len(self._injected_history),
            final_context=self.last_context,
            prompt=prompt,
        )

    def query(self, question: str, include_citations: bool = True) -> str:
        full_response = ""
        for chunk in self.stream_query(question, include_citations):
            full_response += chunk
        return full_response

    def stream_query(self, question: str, include_citations: bool = True):
        from rag import format_citations

        self.last_query_info = {
            "original_query": question,
            "rewritten_query": None,
            "generated_queries": [],
            "retrieved_docs": [],
            "num_docs_retrieved": 0,
        }

        # B4: snapshot the history the prompt will actually see BEFORE this turn's
        # question is recorded, so the live question isn't double-injected (once
        # in chat_history, once in the question slot).
        history_at_prompt = self._injected_history + list(self.memory.messages)

        full_response = ""

        for chunk in self.chain.stream(question):
            full_response += chunk
            yield chunk

        self.last_query_info["retrieved_docs"] = self.retrieved_docs
        self.last_query_info["num_docs_retrieved"] = len(self.retrieved_docs)

        self._fill_trace(question, history_at_prompt)

        if include_citations:
            full_response += "\n\nSources:"
            yield "\n\nSources:"
            for citation in format_citations(self.retrieved_docs):
                yield f"\n{citation}"
                full_response += f"\n{citation}"

        # Record the turn AFTER generation (B4): user first, then assistant.
        self.memory.add_user_message(question)
        self.memory.add_ai_message(full_response)

    async def ingest_documents(self, file_paths: list[str]):
        from rag import load_documents

        documents = [doc async for doc in load_documents(file_paths)]
        return self.vectorstore.add_documents(documents)
