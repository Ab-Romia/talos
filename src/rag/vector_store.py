import io
import sys
from dataclasses import dataclass

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_milvus import Milvus
from langchain_openai import OpenAIEmbeddings
from pymilvus import connections, Collection, utility

from src.config import global_rag_config

__all__ = [
    "get_embeddings",
    "get_vectorstore",
    "create_vectorstore_from_documents",
    "clear_collection",
    "get_collection_info",
]


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
    collection_name: str | None = None,
    embedding_provider: str | None = None,
    embeddings: Embeddings | None = None,
) -> VectorStore:
    if embeddings is None:
        embeddings = get_embeddings(provider=embedding_provider)

    connections.connect(
        alias="default",
        host=global_rag_config.milvus_host,
        port=global_rag_config.milvus_port,
    )

    # TODO: handle existing collection differently?
    vectorstore = Milvus(
        embedding_function=embeddings,
        collection_name=collection_name or global_rag_config.milvus_collection_name,
        connection_args={
            "host": global_rag_config.milvus_host,
            "port": global_rag_config.milvus_port,
        },
        auto_id=True,
        drop_old=False,
    )

    return vectorstore


def create_vectorstore_from_documents(
    documents: list[Document], collection_name: str | None = None
):
    embeddings = get_embeddings()

    connections.connect(
        alias="default",
        host=global_rag_config.milvus_host,
        port=global_rag_config.milvus_port,
    )

    stderr_backup = sys.stderr
    sys.stderr = io.StringIO()

    try:
        vectorstore = Milvus.from_documents(
            documents=documents,
            embedding=embeddings,
            collection_name=collection_name or global_rag_config.milvus_collection_name,
            connection_args={
                "host": global_rag_config.milvus_host,
                "port": global_rag_config.milvus_port,
            },
            drop_old=False,
        )

        collection = Collection(
            collection_name or global_rag_config.milvus_collection_name
        )
        collection.flush()

    finally:
        sys.stderr = stderr_backup

    return vectorstore


def clear_collection(collection_name: str | None = None):
    connections.connect(
        alias="default",
        host=global_rag_config.milvus_host,
        port=global_rag_config.milvus_port,
    )

    col_name = collection_name or global_rag_config.milvus_collection_name

    if utility.has_collection(col_name):
        utility.drop_collection(col_name)
        return True
    return False


@dataclass
class CollectionInfo:
    name: str
    num_entities: int


def get_collection_info(collection_name: str | None = None) -> CollectionInfo | None:
    connections.connect(
        alias="default",
        host=global_rag_config.milvus_host,
        port=global_rag_config.milvus_port,
    )

    col_name = collection_name or global_rag_config.milvus_collection_name

    if utility.has_collection(col_name):
        collection = Collection(col_name)
        collection.load()

        return CollectionInfo(
            name=col_name,
            num_entities=collection.num_entities,
        )
    return None
