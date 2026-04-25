from typing import final

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import (
    RunnablePassthrough,
    RunnableParallel,
    RunnableLambda,
)

from config import RAG_PROMPT
from config import RagConfig, get_effective_rag_config

__all__ = ["RAGChain"]


@final
class RAGChain:
    def __init__(
        self,
        collection_name: str,
        config: RagConfig | None = None,
        workspace_id: str | None = None,
        file_ids: list[str] | None = None,
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

        c = config or get_effective_rag_config()
        self.rag_config = c

        self.collection_name = collection_name
        self.workspace_id = workspace_id
        self.file_ids = file_ids
        self.retrieved_docs: list[Document] = []

        self.last_query_info = {}

        self.query_rewriter = get_query_rewriter(c)
        self.hyde = get_hyde_embeddings(c)

        if workspace_id:
            self.vectorstore = get_workspace_vectorstore(
                embeddings=self.hyde, config=c
            )
            parts = [f'workspace_id == "{workspace_id}"']
            if file_ids:
                ids_csv = ", ".join(f'"{fid}"' for fid in file_ids)
                parts.append(f"file_id in [{ids_csv}]")
            extra_search_kwargs = {"expr": " && ".join(parts)}
        else:
            self.vectorstore = get_vectorstore(
                collection_name, embeddings=self.hyde, config=c
            )
            extra_search_kwargs = None

        self.retriever = get_retriever(
            vectorstore=self.vectorstore,
            documents=[],
            config=c,
            search_kwargs=extra_search_kwargs,
        )

        self.retriever = compression_retriever(
            self.retriever, compression_type=c.compression_type
        )

        self.llm = get_llm(c)
        self.memory = get_memory(use_memory=c.conversation_memory_k > 0)
        self.chain = (
                RunnableParallel(
                    {
                        "context": RunnableLambda(self._rewrite_and_retrieve)
                                   | RunnableLambda(self._format_docs),
                        "question": RunnablePassthrough(),
                        "chat_history": RunnableLambda(lambda _: self.memory.messages),
                    }
                )
                | RAG_PROMPT
                | self.llm
                | StrOutputParser()
        )

    def _rewrite_and_retrieve(self, question: str):
        result = self.query_rewriter.invoke({"query": question})
        if isinstance(result.content, list):
            rewritten = str(result)
        else:
            rewritten = result.content

        self.last_query_info["rewritten_query"] = rewritten.strip()

        docs = self.retriever.invoke(rewritten)
        self.retrieved_docs = docs
        return docs

    # TODO: use prompt template
    @staticmethod
    def _format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

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
