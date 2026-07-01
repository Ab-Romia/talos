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

__all__ = ["RAGChain"]


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
    ):
        from rag import (
            get_query_rewriter,
            get_hyde_embeddings,
            get_vectorstore,
            get_workspace_vectorstore,
            get_retriever,
            get_llm,
            get_memory,
            compression_retriever,
        )

        self.collection_name = collection_name
        self.workspace_id = workspace_id
        self.file_ids = file_ids
        self.chatroom_id = chatroom_id
        self.retrieved_docs: list[Document] = []
        self.chat_retriever = None
        # Captured for debug/observability (the /ask debug flag reads these).
        self.last_context = ""
        self.last_chat_docs: list[Document] = []
        # Prior conversation turns supplied by the caller (the /ask endpoint loads
        # the channel's un-indexed tail). Injected into the answer prompt's
        # chat_history slot; the indexed body is recalled via chat_retriever.
        self._injected_history = list(chat_history) if chat_history else []

        self.last_query_info = {}

        # Each of these is an extra LLM call per query; gate them by config.
        self.query_rewriter = get_query_rewriter() if config.use_query_rewrite else None
        self.hyde = get_hyde_embeddings() if config.use_hyde else None

        if workspace_id:
            self.vectorstore = get_workspace_vectorstore(embeddings=self.hyde)
            # source == "file" keeps chat-memory vectors out of file retrieval in
            # the shared talos_documents collection.
            parts = [f'workspace_id == "{workspace_id}"', 'source == "file"']
            if file_ids:
                ids_csv = ", ".join(f'"{fid}"' for fid in file_ids)
                parts.append(f"file_id in [{ids_csv}]")
            extra_search_kwargs = {"expr": " && ".join(parts)}

            # Per-channel long-term memory: a small dense retriever over this
            # channel's indexed messages, merged into context (not citations).
            if chatroom_id:
                chat_expr = f'chatroom_id == "{chatroom_id}" && source == "chat"'
                self.chat_retriever = self.vectorstore.as_retriever(
                    search_kwargs={"k": config.chat_recall_k, "expr": chat_expr}
                )
        else:
            self.vectorstore = get_vectorstore(collection_name, embeddings=self.hyde)
            extra_search_kwargs = None

        self.retriever = get_retriever(
            vectorstore=self.vectorstore,
            documents=[],
            config=config,
            search_kwargs=extra_search_kwargs,
        )

        self.retriever = compression_retriever(
            self.retriever, compression_type=config.compression_type
        )

        self.llm = get_llm()
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
        missing chat corpus degrades to file-only context."""
        if not self.chat_retriever:
            return []
        try:
            return self.chat_retriever.invoke(query)
        except Exception:
            return []

    # TODO: use prompt template
    def _format_docs(self, docs):
        self.last_context = "\n\n".join(doc.page_content for doc in docs)
        return self.last_context

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

        self.memory.add_user_message(question)

        full_response = ""

        for chunk in self.chain.stream(question):
            full_response += chunk
            yield chunk

        # if self.multiquery_retriever and hasattr(
        #     self.multiquery_retriever, "last_generated_queries"
        # ):
        #     self.last_query_info["generated_queries"] = (
        #         self.multiquery_retriever.last_generated_queries
        #     )

        self.last_query_info["retrieved_docs"] = self.retrieved_docs
        self.last_query_info["num_docs_retrieved"] = len(self.retrieved_docs)

        if include_citations:
            full_response += "\n\nSources:"
            yield "\n\nSources:"
            for citation in format_citations(self.retrieved_docs):
                yield f"\n{citation}"
                full_response += f"\n{citation}"

        self.memory.add_ai_message(full_response)

    async def ingest_documents(self, file_paths: list[str]):
        from rag import load_documents

        documents = [doc async for doc in load_documents(file_paths)]
        return self.vectorstore.add_documents(documents)
