from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_milvus import Milvus
from langchain_openai import OpenAIEmbeddings
from pymilvus import connections, Collection, utility

from model.config import global_rag_config

__all__ = [
    "get_embeddings",
    "get_vectorstore",
    "clear_collection",
    "get_collection_info",
]

connections.connect(
    alias="default",
    host=global_rag_config.milvus_host,
    port=global_rag_config.milvus_port,
)


def get_embeddings(provider: str | None = None) -> Embeddings:
    if provider is None:
        provider = global_rag_config.embedding_provider

    if provider == "openai":
        return OpenAIEmbeddings(
            model=global_rag_config.embedding_model,
            api_key=global_rag_config.openai_api_key,
        )
    elif provider == "huggingface":
        return HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")


def get_vectorstore(
        collection_name: str,
        embedding_provider: str | None = None,
        embeddings: Embeddings | None = None,
) -> VectorStore:
    if embeddings is None:
        embeddings = get_embeddings(embedding_provider)

    # TODO: handle existing collection differently?
    return Milvus(
        embedding_function=embeddings,
        collection_name=collection_name,
        auto_id=True,
        enable_dynamic_field=True,
    )


def clear_collection(collection_name: str):
    col_name = collection_name

    if utility.has_collection(col_name):
        utility.drop_collection(col_name)
        return True
    return False


@dataclass
class CollectionInfo:
    name: str
    num_entities: int


def get_collection_info(collection_name: str | None = None) -> CollectionInfo | None:
    col_name = collection_name or global_rag_config.milvus_collection_name

    if utility.has_collection(col_name):
        collection = Collection(col_name)
        collection.load()

        return CollectionInfo(
            name=col_name,
            num_entities=collection.num_entities,
        )
    return None
