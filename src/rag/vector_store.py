from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_milvus import Milvus
from langchain_openai import OpenAIEmbeddings
from pymilvus import connections, Collection, utility

from config import global_rag_config

__all__ = [
    "get_embeddings",
    "get_vectorstore",
    "get_workspace_vectorstore",
    "delete_file_chunks",
    "clear_collection",
    "get_collection_info",
]

WORKSPACE_COLLECTION = "talos_documents"

_milvus_connected = False


def _ensure_milvus_connection():
    global _milvus_connected
    if not _milvus_connected:
        connections.connect(
            alias="default",
            host=global_rag_config.milvus_host,
            port=global_rag_config.milvus_port,
        )
        _milvus_connected = True


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
    _ensure_milvus_connection()
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
    _ensure_milvus_connection()
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
    _ensure_milvus_connection()
    col_name = collection_name or global_rag_config.milvus_collection_name

    if utility.has_collection(col_name):
        collection = Collection(col_name)
        collection.load()

        return CollectionInfo(
            name=col_name,
            num_entities=collection.num_entities,
        )
    return None


def get_workspace_vectorstore(
    collection_name: str = WORKSPACE_COLLECTION,
    embedding_provider: str | None = None,
    embeddings: Embeddings | None = None,
) -> VectorStore:
    """Get vectorstore for workspace-scoped file chunks."""
    if embeddings is None:
        embeddings = get_embeddings(embedding_provider)

    return Milvus(
        embedding_function=embeddings,
        collection_name=collection_name,
        auto_id=True,
        enable_dynamic_field=True,
        connection_args={
            "host": global_rag_config.milvus_host,
            "port": global_rag_config.milvus_port,
        },
    )


def delete_file_chunks(
    file_id: str,
    workspace_id: str | None = None,
    collection_name: str = WORKSPACE_COLLECTION,
):
    """Delete all vector chunks for a given file_id from Milvus.

    When workspace_id is supplied, the delete is additionally scoped to
    that workspace so a caller cannot accidentally wipe another tenant's
    rows if file_ids ever collide.
    """
    _ensure_milvus_connection()
    if not utility.has_collection(collection_name):
        return

    from pymilvus import MilvusClient

    client = MilvusClient(
        uri=f"http://{global_rag_config.milvus_host}:{global_rag_config.milvus_port}"
    )

    parts = [f'file_id == "{file_id}"']
    if workspace_id:
        parts.append(f'workspace_id == "{workspace_id}"')

    client.delete(
        collection_name=collection_name,
        filter=" && ".join(parts),
    )
