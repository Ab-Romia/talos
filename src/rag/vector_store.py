import copy
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_milvus import Milvus
from langchain_openai import OpenAIEmbeddings
from pymilvus import connections, Collection, utility

from config import global_rag_config

def _link_milvus_client_orm(client) -> None:
    """Register a MilvusClient's connection handler under the pymilvus ORM
    `connections` registry so ORM Collection(using=alias) can reuse it.

    langchain_milvus talks to Milvus via a MilvusClient but reads schema via the
    ORM Collection API; the two use separate connection registries. Without this
    bridge, ORM access raises "should create connection first". (This path had no
    live caller on main until the /ask endpoint + chat indexer.)
    """
    alias = client._using
    if alias in connections._alias_handlers:
        return
    connections._alias_handlers[alias] = client._handler
    if "default" in connections._alias_config:
        connections._alias_config[alias] = copy.deepcopy(connections._alias_config["default"])
    else:
        connections._alias_config[alias] = {
            "address": f"{global_rag_config.milvus_host}:{global_rag_config.milvus_port}",
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

__all__ = [
    "get_embeddings",
    "get_vectorstore",
    "get_workspace_vectorstore",
    "delete_file_chunks",
    "delete_message_chunks",
    "delete_chat_segments_for_messages",
    "clear_collection",
    "get_collection_info",
]

# Single source of truth for the product/ingest/indexer/CLI collection. Both
# WORKSPACE_COLLECTION and global_rag_config.milvus_collection_name resolve here,
# so the CLI and the app can no longer read different collections.
WORKSPACE_COLLECTION = global_rag_config.milvus_collection_name

_milvus_connected = False


def _ensure_milvus_connection():
    global _milvus_connected
    if not _milvus_connected:
        connections.connect(
            alias="default",
            uri=f"http://{global_rag_config.milvus_host}:{global_rag_config.milvus_port}",
        )
        _milvus_connected = True


# bge-en-v1.5 retrieval instruction (query side only) — per the BAAI model card.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def _bge_embeddings_cls():
    from langchain_community.embeddings import HuggingFaceBgeEmbeddings
    return HuggingFaceBgeEmbeddings


def _hf_embeddings_for(model: str) -> Embeddings:
    """HF embedder for the configured model. bge-en models need the query-side
    instruction prefix or retrieval quality silently degrades."""
    if "bge-" in model:
        return _bge_embeddings_cls()(
            model_name=model,
            query_instruction=BGE_QUERY_INSTRUCTION,
            encode_kwargs={"normalize_embeddings": True},
        )
    return HuggingFaceEmbeddings(model_name=model)


@lru_cache(maxsize=None)
def _build_embeddings(provider: str, model: str, api_key: str | None) -> Embeddings:
    # Cached: constructing the embedder (esp. the HuggingFace sentence-transformer)
    # loads the model from disk and costs ~3.5s — otherwise paid on every query.
    # Keyed on (provider, model) so two different models don't collide.
    if provider == "openai":
        return OpenAIEmbeddings(model=model, api_key=api_key)
    elif provider == "huggingface":
        return _hf_embeddings_for(model)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")


@lru_cache(maxsize=None)
def _assert_collection_dim(collection_name: str, provider: str, model: str) -> None:
    """Fail fast if the configured embedder's dimension doesn't match the live
    collection (e.g. env lost EMBEDDING_PROVIDER and fell back to OpenAI/1536
    against a 384-dim corpus). Cached: one probe embedding per process."""
    _ensure_milvus_connection()
    if not utility.has_collection(collection_name):
        return
    field = next((f for f in Collection(collection_name).schema.fields if f.name == "vector"), None)
    if field is None:
        return
    coll_dim = field.params.get("dim")
    emb_dim = len(get_embeddings(provider).embed_query("dimension probe"))
    if coll_dim is not None and emb_dim != int(coll_dim):
        raise RuntimeError(
            f"Embedding dim mismatch: {provider}/{model} produces {emb_dim}-dim vectors "
            f"but collection '{collection_name}' is {coll_dim}-dim. Fix EMBEDDING_* env "
            f"or re-ingest the collection."
        )


def get_embeddings(provider: str | None = None, config=global_rag_config) -> Embeddings:
    provider = provider or config.embedding_provider
    api_key = config.openai_api_key.get_secret_value() if config.openai_api_key else None
    return _build_embeddings(provider, config.embedding_model, api_key)


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
    """Get vectorstore for workspace-scoped file chunks.

    Relies on the module-level MilvusClient ORM bridge (see
    _install_milvus_client_orm_bridge) for the pymilvus ORM connection.
    """
    if embeddings is None:
        embeddings = get_embeddings(embedding_provider)
        _assert_collection_dim(
            collection_name,
            embedding_provider or global_rag_config.embedding_provider,
            global_rag_config.embedding_model,
        )

    return Milvus(
        embedding_function=embeddings,
        collection_name=collection_name,
        auto_id=True,
        enable_dynamic_field=True,
        # MUST stay the uri form: MilvusClient(host=, port=) deadlocks in
        # _wait_for_channel_ready (the 2026-07-02 bug, still present on
        # pymilvus 2.6.x via connection_manager._create_shared).
        connection_args={
            "uri": f"http://{global_rag_config.milvus_host}:{global_rag_config.milvus_port}",
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


def delete_message_chunks(
    message_id: str,
    collection_name: str = WORKSPACE_COLLECTION,
):
    """Delete all chat-memory vector chunks for a given message_id from Milvus.

    Mirrors delete_file_chunks; used to keep the chat indexer idempotent on
    retry and to purge a message's vectors if it is ever deleted.
    """
    _ensure_milvus_connection()
    if not utility.has_collection(collection_name):
        return

    from pymilvus import MilvusClient

    client = MilvusClient(
        uri=f"http://{global_rag_config.milvus_host}:{global_rag_config.milvus_port}"
    )

    client.delete(
        collection_name=collection_name,
        filter=f'message_id == "{message_id}"',
    )


def delete_chat_segments_for_messages(
    message_ids: list[str],
    collection_name: str = WORKSPACE_COLLECTION,
):
    """Delete every chat-memory segment vector that covers ANY of the given
    message_ids. The indexer calls this before re-ingesting a batch so a
    crashed previous tick can't leave duplicate segment vectors."""
    if not message_ids:
        return
    _ensure_milvus_connection()
    if not utility.has_collection(collection_name):
        return

    from pymilvus import MilvusClient
    import json

    client = MilvusClient(
        uri=f"http://{global_rag_config.milvus_host}:{global_rag_config.milvus_port}"
    )
    ids_json = json.dumps([str(i) for i in message_ids])
    client.delete(
        collection_name=collection_name,
        filter=f'source == "chat" && json_contains_any(message_ids, {ids_json})',
    )
