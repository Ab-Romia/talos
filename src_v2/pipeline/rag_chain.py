from langchain_core.runnables import RunnablePassthrough, RunnableParallel, RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from src_v2.vectorstore.milvus_store import get_vectorstore, create_vectorstore_from_documents
from src_v2.retrieval.retrievers import get_retriever
from src_v2.retrieval.query_processing import get_hyde_embeddings, get_query_rewriter, get_multiquery_retriever
from src_v2.retrieval.compression import get_compression_retriever
from src_v2.generation.chains import get_llm
from src_v2.generation.memory import get_memory
from src_v2.config.prompts import RAG_PROMPT
from src_v2.config.settings import settings
from src_v2.ingestion.loaders import load_documents
from src_v2.ingestion.splitters import get_text_splitter
from src_v2.utils.citations import add_citations_to_response, format_citations


class RAGChain:
    def __init__(
        self,
        collection_name: str | None = None,
        use_memory: bool = True,
        use_multiquery: bool = False,
        use_compression: bool = False,
        verbose: bool = False
    ):
        self.collection_name = collection_name
        self.use_memory = use_memory
        self.use_multiquery = use_multiquery
        self.use_compression = use_compression
        self.verbose = verbose
        self.retrieved_docs = []
        self.last_query_info = {}

        hyde_embeddings = get_hyde_embeddings()
        self.query_rewriter = get_query_rewriter()

        self.vectorstore = get_vectorstore(collection_name=collection_name, embeddings=hyde_embeddings)

        self.retriever = get_retriever(
            vectorstore=self.vectorstore,
            use_rerank=settings.use_reranking
        )

        if use_multiquery:
            self.retriever = get_multiquery_retriever(self.retriever)
            self.multiquery_retriever = self.retriever
        else:
            self.multiquery_retriever = None

        if use_compression:
            self.retriever = get_compression_retriever(self.retriever, compression_type="llm")

        self.llm = get_llm()
        self.memory = get_memory() if use_memory else None
        self.chain = self._build_chain()

    def _build_chain(self):
        def rewrite_and_retrieve(question):
            result = self.query_rewriter.invoke({"query": question})
            rewritten = result.content if hasattr(result, 'content') else str(result)
            self.last_query_info['rewritten_query'] = rewritten.strip()

            docs = self.retriever.invoke(rewritten)
            self.retrieved_docs = docs
            return docs

        retrieval_chain = RunnableParallel(
            {
                "context": RunnableLambda(rewrite_and_retrieve) | RunnableLambda(self._format_docs),
                "question": RunnablePassthrough(),
                "chat_history": RunnableLambda(lambda x: self.memory.get_messages() if self.memory else [])
            }
        )

        rag_chain = (
            retrieval_chain
            | RAG_PROMPT
            | self.llm
            | StrOutputParser()
        )

        return rag_chain

    @staticmethod
    def _format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    def query(self, question: str, include_citations: bool = True) -> str:
        self.last_query_info = {
            'original_query': question,
            'rewritten_query': None,
            'generated_queries': [],
            'retrieved_docs': [],
            'num_docs_retrieved': 0
        }

        if self.memory:
            self.memory.add_user_message(question)

        response = self.chain.invoke(question)

        if self.multiquery_retriever and hasattr(self.multiquery_retriever, 'last_generated_queries'):
            self.last_query_info['generated_queries'] = self.multiquery_retriever.last_generated_queries

        self.last_query_info['retrieved_docs'] = self.retrieved_docs
        self.last_query_info['num_docs_retrieved'] = len(self.retrieved_docs)

        if include_citations:
            response = add_citations_to_response(response, self.retrieved_docs)

        if self.memory:
            self.memory.add_ai_message(response)

        return response

    def get_last_query_info(self):
        return self.last_query_info

    def stream_query(self, question: str, include_citations: bool = True):
        self.last_query_info = {
            'original_query': question,
            'rewritten_query': None,
            'generated_queries': [],
            'retrieved_docs': [],
            'num_docs_retrieved': 0
        }

        if self.memory:
            self.memory.add_user_message(question)

        full_response = ""

        for chunk in self.chain.stream(question):
            full_response += chunk
            yield chunk

        if self.multiquery_retriever and hasattr(self.multiquery_retriever, 'last_generated_queries'):
            self.last_query_info['generated_queries'] = self.multiquery_retriever.last_generated_queries

        self.last_query_info['retrieved_docs'] = self.retrieved_docs
        self.last_query_info['num_docs_retrieved'] = len(self.retrieved_docs)

        if include_citations:
            citations = format_citations(self.retrieved_docs)
            if citations:
                yield citations
                full_response += citations

        if self.memory:
            self.memory.add_ai_message(full_response)


def ingest_documents(file_paths: list[str], collection_name: str | None = None):
    docs = load_documents(file_paths)

    unique_sources = set()
    for doc in docs:
        if hasattr(doc, 'metadata') and 'source' in doc.metadata:
            unique_sources.add(doc.metadata['source'])

    ingestion_info = {
        'num_files': len(unique_sources) if unique_sources else len(file_paths),
        'num_documents': len(docs),
        'num_chunks': 0,
        'files': file_paths
    }

    splitter = get_text_splitter()
    chunks = splitter.split_documents(docs)
    ingestion_info['num_chunks'] = len(chunks)

    vectorstore = create_vectorstore_from_documents(chunks, collection_name)

    return vectorstore, ingestion_info
