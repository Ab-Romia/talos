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
    supported_extensions = {'.pdf', '.txt', '.csv', '.md'}
    docs = []

    for path_str in file_paths:
        path = Path(path_str)

        if path.is_dir():
            files = []
            for ext in supported_extensions:
                files.extend(path.rglob(f'*{ext}'))
            for file_path in sorted(files):
                docs.extend(load_document(str(file_path)))
        elif path.is_file():
            docs.extend(load_document(str(path)))
        else:
            raise ValueError(f"Path not found: {path_str}")

    return docs