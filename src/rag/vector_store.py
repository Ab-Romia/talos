import copy
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_milvus import Milvus
from langchain_openai import OpenAIEmbeddings
from pymilvus import connections, Collection, utility
from pymilvus.exceptions import ErrorCode, MilvusException

from config import RagConfig, get_effective_rag_config
from utils.logger import get_logger

logger = get_logger(__name__)

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


def _link_milvus_client_orm(client) -> None:
    alias = client._using
    if alias in connections._alias_handlers:
        return
    connections._alias_handlers[alias] = client._handler
    if "default" in connections._alias_config:
        connections._alias_config[alias] = copy.deepcopy(connections._alias_config["default"])
    else:
        c = get_effective_rag_config()
        connections._alias_config[alias] = {
            "address": f"{c.milvus_host}:{c.milvus_port}",
            "user": "",
            "db_name": "default",
        }


def _install_milvus_client_orm_bridge() -> None:
    from pymilvus.milvus_client.milvus_client import MilvusClient

    if getattr(MilvusClient.__init__, "_talos_orm_bridge", False):
        return
    _orig = MilvusClient.__init__

    def _patched(self, *a, **kw):
        _orig(self, *a, **kw)
        _link_milvus_client_orm(self)

    _patched._talos_orm_bridge = True
    MilvusClient.__init__ = _patched


_install_milvus_client_orm_bridge()


def _ensure_milvus_connection(c: RagConfig | None = None) -> None:
    global _milvus_connected
    if not _milvus_connected:
        conf = c or get_effective_rag_config()
        connections.connect(
            alias="default",
            host=conf.milvus_host,
            port=conf.milvus_port,
        )
        _milvus_connected = True


def get_embeddings(
    provider: str | None = None, config: RagConfig | None = None
) -> Embeddings:
    c = config or get_effective_rag_config()
    if provider is None:
        provider = c.embedding_provider

    if provider == "openai":
        return OpenAIEmbeddings(
            model=c.embedding_model,
            api_key=c.openai_api_key,
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
    config: RagConfig | None = None,
) -> VectorStore:
    c = config or get_effective_rag_config()
    _ensure_milvus_connection(c)
    if embeddings is None:
        embeddings = get_embeddings(embedding_provider, c)

    return Milvus(
        embedding_function=embeddings,
        collection_name=collection_name,
        auto_id=True,
        enable_dynamic_field=True,
        connection_args={"uri": f"http://{c.milvus_host}:{c.milvus_port}"},
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
    c = get_effective_rag_config()
    _ensure_milvus_connection(c)
    col_name = collection_name or c.milvus_collection_name

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
    config: RagConfig | None = None,
) -> VectorStore:
    c = config or get_effective_rag_config()
    _ensure_milvus_connection(c)
    if embeddings is None:
        embeddings = get_embeddings(embedding_provider, c)

    return Milvus(
        embedding_function=embeddings,
        collection_name=collection_name,
        auto_id=True,
        enable_dynamic_field=True,
        connection_args={"uri": f"http://{c.milvus_host}:{c.milvus_port}"},
    )


def delete_file_chunks(
    file_id: str,
    workspace_id: str | None = None,
    collection_name: str = WORKSPACE_COLLECTION,
):
    c = get_effective_rag_config()
    _ensure_milvus_connection(c)
    if not utility.has_collection(collection_name):
        return

    parts = [f'file_id == "{file_id}"']
    if workspace_id:
        parts.append(f'workspace_id == "{workspace_id}"')
    expr = " && ".join(parts)

    try:
        col = Collection(collection_name, using="default")
        col.load()
        col.delete(expr)
    except MilvusException as e:
        if e.code == ErrorCode.INDEX_NOT_FOUND:
            logger.info(
                "Skipping Milvus delete (no index yet; nothing to remove)",
                collection=collection_name,
                file_id=file_id,
            )
            return
        raise
