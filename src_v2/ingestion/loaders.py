from pathlib import Path
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    CSVLoader,
    UnstructuredMarkdownLoader
)


def load_document(file_path: str):
    path = Path(file_path)
    suffix = path.suffix.lower()

    loaders = {
        '.pdf': PyPDFLoader,
        '.txt': TextLoader,
        '.csv': CSVLoader,
        '.md': UnstructuredMarkdownLoader,
    }

    loader_class = loaders.get(suffix)
    if not loader_class:
        raise ValueError(f"Unsupported file type: {suffix}")

    return loader_class(file_path).load()


def load_documents(file_paths: list[str]):
    docs = []
    for path in file_paths:
        docs.extend(load_document(path))
    return docs