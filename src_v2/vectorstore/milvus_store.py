#Milvus vector store management.

import sys
import io
from contextlib import redirect_stderr

from langchain_milvus import Milvus
from pymilvus import connections
from src_v2.config.settings import settings
from src_v2.vectorstore.embeddings import get_embeddings


def get_vectorstore(
    collection_name: str | None = None,
    embedding_provider: str | None = None
):
    embeddings = get_embeddings(provider=embedding_provider)

    connections.connect(
        alias="default",
        host=settings.milvus_host,
        port=settings.milvus_port
    )

    # Suppress async event loop warnings
    stderr_backup = sys.stderr
    sys.stderr = io.StringIO()

    try:
        vectorstore = Milvus(
            embedding_function=embeddings,
            collection_name=collection_name or settings.milvus_collection_name,
            connection_args={
                "host": settings.milvus_host,
                "port": settings.milvus_port
            },
            auto_id=True,
            drop_old=False
        )
    finally:
        sys.stderr = stderr_backup

    return vectorstore


def create_vectorstore_from_documents(documents, collection_name: str | None = None):
    embeddings = get_embeddings()

    connections.connect(
        alias="default",
        host=settings.milvus_host,
        port=settings.milvus_port
    )

    # Suppress async event loop warnings
    stderr_backup = sys.stderr
    sys.stderr = io.StringIO()

    try:
        vectorstore = Milvus.from_documents(
            documents=documents,
            embedding=embeddings,
            collection_name=collection_name or settings.milvus_collection_name,
            connection_args={
                "host": settings.milvus_host,
                "port": settings.milvus_port
            }
        )
    finally:
        sys.stderr = stderr_backup

    return vectorstore
