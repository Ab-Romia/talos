from pathlib import Path

from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    CSVLoader,
    UnstructuredMarkdownLoader,
)
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownTextSplitter,
)

from src.config import global_rag_config

__all__ = ["load_document", "load_documents", "get_text_splitter"]


# TODO: Add support for more file types as needed
#   Better batch loading
#   Async loading
#   More loading sources (web, database)


def load_document(file_path: str | Path):
    path = Path(file_path)
    suffix = path.suffix.lower()

    loaders = {
        ".pdf": PyPDFLoader,
        ".txt": TextLoader,
        ".csv": CSVLoader,
        ".md": UnstructuredMarkdownLoader,
    }

    loader_class = loaders.get(suffix)
    if not loader_class:
        raise ValueError(f"Unsupported file type: {suffix}")

    return loader_class(file_path).load()


def load_documents(file_paths: list[str]):
    supported_extensions = {".pdf", ".txt", ".csv", ".md"}
    docs = []

    for path_str in file_paths:
        path = Path(path_str)

        if path.is_dir():
            files = []
            for ext in supported_extensions:
                files.extend(path.rglob(f"*{ext}"))
            for file_path in sorted(files):
                docs.extend(load_document(str(file_path)))
        elif path.is_file():
            docs.extend(load_document(str(path)))
        else:
            raise ValueError(f"Path not found: {path_str}")

    return docs


def get_text_splitter(strategy: str | None = None):
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
