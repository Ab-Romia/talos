from collections.abc import Iterable
from pathlib import Path
from typing import cast

from langchain_core.documents import Document
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownTextSplitter,
)
from langchain_unstructured import UnstructuredLoader

from config import global_rag_config

__all__ = ["load_documents", "document_splitter", "format_citations", "ingest_file_chunks", "ingest_chat_messages"]


async def load_documents(file_paths: str | Path | list[str] | list[Path]):
    """
    Async generator that loads documents from given file paths.

    TODO:
        - Add support for more file types
        - Add support for bytes, str or file-like objects
        - More loading sources (web, database)
        - Fallback


    :param file_paths:
    """

    if not isinstance(file_paths, list):
        file_paths = [Path(file_paths)]
    else:
        file_paths = [Path(fp) for fp in file_paths]

    loader = UnstructuredLoader(
        file_paths,
        chunking_strategy="basic",
        max_characters=1_000_000,
        include_orig_elements=False,
    )

    async for doc in loader.alazy_load():
        yield doc


def document_splitter(document: str) -> str:
    return document


# add config
def document_splitter_(strategy: str | None = None):
    if strategy is None:
        strategy = global_rag_config.chunking_strategy

    if strategy == "recursive":
        return RecursiveCharacterTextSplitter(
            chunk_size=global_rag_config.chunk_size,
            chunk_overlap=global_rag_config.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    elif strategy == "markdown":
        return MarkdownTextSplitter(
            chunk_size=global_rag_config.chunk_size,
            chunk_overlap=global_rag_config.chunk_overlap,
        )

    else:
        raise ValueError(f"Unknown chunking strategy: {strategy}")


# TODO: add more metadata fields to Citation as needed
# Example metadata: https://docs.langchain.com/oss/python/integrations/document_loaders/unstructured_file
# Document(metadata={
#    'source': './example_data/layout-parser-paper.pdf',
#    'coordinates': {
#       'points': ((16.34, 213.36), (16.34, 253.36), (36.34, 253.36), (36.34, 213.36)),
#       'system': 'PixelSpace',
#       'layout_width': 612,
#       'layout_height': 792
#       },
#    'file_directory': './example_data',
#    'filename': 'layout-parser-paper.pdf',
#    'languages': ['eng'],
#    'last_modified': '2024-02-27T15:49:27',
#    'page_number': 1,
#    'filetype': 'application/pdf',
#    'category': 'UncategorizedText',
#    'element_id': 'd3ce55f220dfb75891b4394a18bcb973'},
#       ...
#    page_content='1 2 0 2')


def ingest_file_chunks(
    chunks: list[Document],
    workspace_id: str,
    file_id: str,
):
    """Insert document chunks into the workspace-scoped Milvus collection."""
    from rag.vector_store import get_workspace_vectorstore

    for chunk in chunks:
        chunk.metadata.setdefault("workspace_id", workspace_id)
        chunk.metadata.setdefault("file_id", file_id)
        # Discriminator so file retrieval and chat-memory retrieval stay separable
        # in the shared `talos_documents` collection.
        chunk.metadata.setdefault("source", "file")

    vectorstore = get_workspace_vectorstore()
    vectorstore.add_documents(chunks)


def ingest_chat_messages(docs: list[Document]):
    """Insert pre-built chat-memory Documents into the workspace collection.

    Documents already carry their metadata (workspace_id, chatroom_id,
    message_id, source="chat", sent_at). No-op on an empty list. Pinned to the
    same `talos_documents` collection file chunks use (WORKSPACE_COLLECTION).
    """
    if not docs:
        return
    from rag.vector_store import get_workspace_vectorstore

    vectorstore = get_workspace_vectorstore()
    vectorstore.add_documents(docs)


# TODO: use templates for formatting
def format_citations(documents: Iterable[Document]) -> Iterable[str]:
    """
    Citation formatter for retrieved documents.

    :param documents: Iterable of retrieved documents.
    :return: Formatted citation string.
    """

    citations: set[str] = set()

    # TODO: create polymorphic citation formatters
    for i, doc in enumerate(documents, 1):
        # For workspace files, use filename; for CLI docs, use source
        filename = doc.metadata.get("filename")
        file_id = doc.metadata.get("file_id")
        if filename:
            page = doc.metadata.get("page_number", "")
            page_str = f", p.{page}" if page else ""
            citation = f"{filename}{page_str}"
            if file_id:
                citation += f" (file:{file_id})"
        else:
            citation = cast(
                str, doc.metadata.get("source", "unknown"))  # pyright: ignore[reportUnknownMemberType]; fmt: skip

        if citation not in citations:
            citations.add(citation)
            yield f"[{i}] {citation}"
