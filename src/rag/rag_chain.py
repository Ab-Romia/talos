from typing import final

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import (
    RunnablePassthrough,
    RunnableParallel,
    RunnableLambda,
)

from src.config import global_rag_config as global_rag_config, RagConfig
from src.config.prompts import RAG_PROMPT

__all__ = ["RAGChain", "ingest_documents"]


@final
class RAGChain:
    def __init__(self, collection_name: str, config: RagConfig = global_rag_config):
        from src.rag import (
            get_query_rewriter,
            get_hyde_embeddings,
            get_vectorstore,
            get_retriever,
            get_llm,
            get_memory,
            compression_retriever,
        )

        self.collection_name = collection_name
        self.retrieved_docs: list[Document] = []

        self.last_query_info = {}

        self.query_rewriter = get_query_rewriter()
        self.hyde = get_hyde_embeddings()
        self.vectorstore = get_vectorstore(
            collection_name=collection_name, embeddings=self.hyde
        )

        self.retriever = get_retriever(
            vectorstore=self.vectorstore,
            documents=[],
            config=config,
        )

        self.retriever = compression_retriever(
            self.retriever, compression_type=config.compression_type
        )

        self.llm = get_llm()
        # Keep the history-like object returned by get_memory to allow swapping later
        self.memory = get_memory(use_memory=config.conversation_memory_k > 0)
        self.chain = self._build_chain()

    def _build_chain(self):
        def rewrite_and_retrieve(question: str):
            result = self.query_rewriter.invoke({"query": question})
            if isinstance(result.content, list):
                rewritten = str(result)
            else:
                rewritten = result.content

            self.last_query_info["rewritten_query"] = rewritten.strip()

            docs = self.retriever.invoke(rewritten)
            self.retrieved_docs = docs
            return docs

        retrieval_chain = RunnableParallel(
            {
                "context": RunnableLambda(rewrite_and_retrieve)
                | RunnableLambda(self._format_docs),
                "question": RunnablePassthrough(),
                "chat_history": RunnableLambda(lambda _: self.memory.messages),
            }
        )

        # fmt: off
        rag_chain = (
            retrieval_chain
            | RAG_PROMPT
            | self.llm
            | StrOutputParser()
        )
        # fmt: on

        return rag_chain

    @staticmethod
    def _format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    def query(self, question: str, include_citations: bool = True) -> str:
        full_response = ""
        for chunk in self.stream_query(question, include_citations):
            full_response += chunk
        return full_response

    def stream_query(self, question: str, include_citations: bool = True):
        from src.rag import format_citations

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
            citations = format_citations(self.retrieved_docs)
            if citations:
                yield citations
                full_response += citations

        self.memory.add_ai_message(full_response)


def ingest_documents(file_paths: list[str], collection_name: str | None = None):
    from src.rag import (
        load_documents,
        get_text_splitter,
        create_vectorstore_from_documents,
    )

    docs = load_documents(file_paths)

    unique_sources = set()
    for doc in docs:
        if hasattr(doc, "metadata") and "source" in doc.metadata:
            unique_sources.add(doc.metadata["source"])

    ingestion_info = {
        "num_files": len(unique_sources) if unique_sources else len(file_paths),
        "num_documents": len(docs),
        "num_chunks": 0,
        "files": file_paths,
    }

    splitter = get_text_splitter()
    chunks = splitter.split_documents(docs)
    ingestion_info["num_chunks"] = len(chunks)

    vectorstore = create_vectorstore_from_documents(chunks, collection_name)

    return vectorstore, ingestion_info
