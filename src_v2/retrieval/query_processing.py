#Query preprocessing and expansion.

from langchain_classic.retrievers import MultiQueryRetriever
from langchain_classic.chains import HypotheticalDocumentEmbedder
from src_v2.generation.chains import get_llm
from src_v2.vectorstore.embeddings import get_embeddings


class VerboseMultiQueryRetriever(MultiQueryRetriever):
    def _get_relevant_documents(self, query, *, run_manager):
        queries = self.generate_queries(query, run_manager)
        # Store queries bypassing pydantic restrictions
        object.__setattr__(self, 'last_generated_queries', queries)

        documents = []
        for q in queries:
            documents.extend(self.retriever.invoke(q))

        # Deduplicate by content hash
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


def get_hyde_embeddings():
    base_embeddings = get_embeddings()
    llm = get_llm()

    return HypotheticalDocumentEmbedder.from_llm(
        llm=llm,
        base_embeddings=base_embeddings,
        prompt_key="web_search"
    )
