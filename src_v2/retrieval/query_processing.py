from langchain_classic.retrievers import MultiQueryRetriever
from langchain_classic.chains import HypotheticalDocumentEmbedder
from langchain_openai import ChatOpenAI
from src_v2.generation.chains import get_llm
from src_v2.vectorstore.embeddings import get_embeddings
from src_v2.config.settings import settings
from src_v2.config.prompts import QUERY_REWRITE_PROMPT


class VerboseMultiQueryRetriever(MultiQueryRetriever):
    def _get_relevant_documents(self, query, *, run_manager):
        queries = self.generate_queries(query, run_manager)
        object.__setattr__(self, 'last_generated_queries', queries)

        documents = []
        for q in queries:
            documents.extend(self.retriever.invoke(q))

        unique_docs = []
        seen_content = set()
        for doc in documents:
            content_hash = hash(doc.page_content)
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_docs.append(doc)

        return unique_docs


def get_multiquery_retriever(base_retriever):
    return VerboseMultiQueryRetriever.from_llm(
        retriever=base_retriever,
        llm=get_llm()
    )


def get_query_rewriter():
    llm = get_llm()
    return QUERY_REWRITE_PROMPT | llm


def get_hyde_embeddings():
    base_embeddings = get_embeddings()
    hyde_llm = ChatOpenAI(
        model="gpt-3.5-turbo",
        temperature=0.0,
        max_tokens=150,
        openai_api_key=settings.openai_api_key
    )
    return HypotheticalDocumentEmbedder.from_llm(
        llm=hyde_llm,
        base_embeddings=base_embeddings,
        prompt_key="web_search"
    )
