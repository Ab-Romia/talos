"""
Document loaders for various file formats.

Supports text, PDF, markdown, and other common formats.
"""

import os
from abc import ABC
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.base_interfaces import BaseChunker, BaseDocumentLoader, Document
from src.core.exceptions import DocumentLoadError, UnsupportedFileTypeError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DocumentLoader(BaseDocumentLoader, ABC):
    """Base class for document loaders."""

    def __init__(self, encoding: str = "utf-8"):
        self.encoding = encoding

    def _create_document(
        self,
        content: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Document:
        """Create a document with standard metadata."""
        doc_metadata = {
            "source": source,
            "file_name": Path(source).name if source else None,
            "file_type": Path(source).suffix if source else None,
        }
        if metadata:
            doc_metadata.update(metadata)

        return Document(content=content, metadata=doc_metadata)


class TextLoader(DocumentLoader):
    """Loader for plain text files."""

    @property
    def supported_extensions(self) -> List[str]:
        return [".txt", ".text"]

    def load(self, source: str) -> List[Document]:
        """Load a text file."""
        path = Path(source)

        if not path.exists():
            raise DocumentLoadError(
                f"File not found: {source}",
                source=source,
            )

        try:
            content = path.read_text(encoding=self.encoding)
            return [self._create_document(content, source)]
        except Exception as e:
            raise DocumentLoadError(
                f"Failed to load text file: {e}",
                source=source,
                cause=e,
            )

    def load_and_chunk(
        self,
        source: str,
        chunker: Optional[BaseChunker] = None,
    ) -> List[Document]:
        """Load and chunk text file."""
        documents = self.load(source)

        if chunker:
            chunked = []
            for doc in documents:
                chunked.extend(chunker.chunk(doc.content, doc.metadata))
            return chunked

        return documents


class PDFLoader(DocumentLoader):
    """Loader for PDF files."""

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    def load(self, source: str) -> List[Document]:
        """Load a PDF file."""
        path = Path(source)

        if not path.exists():
            raise DocumentLoadError(f"File not found: {source}", source=source)

        try:
            # Try pypdf first
            try:
                from pypdf import PdfReader

                reader = PdfReader(path)
                documents = []

                for page_num, page in enumerate(reader.pages):
                    text = page.extract_text()
                    if text.strip():
                        metadata = {
                            "page_number": page_num + 1,
                            "total_pages": len(reader.pages),
                        }
                        documents.append(
                            self._create_document(text, source, metadata)
                        )

                return documents

            except ImportError:
                # Fall back to pdfplumber
                try:
                    import pdfplumber

                    documents = []
                    with pdfplumber.open(path) as pdf:
                        for page_num, page in enumerate(pdf.pages):
                            text = page.extract_text()
                            if text and text.strip():
                                metadata = {
                                    "page_number": page_num + 1,
                                    "total_pages": len(pdf.pages),
                                }
                                documents.append(
                                    self._create_document(text, source, metadata)
                                )

                    return documents

                except ImportError:
                    raise ImportError(
                        "PDF support requires pypdf or pdfplumber. "
                        "Install with: pip install pypdf or pip install pdfplumber"
                    )

        except Exception as e:
            raise DocumentLoadError(
                f"Failed to load PDF: {e}",
                source=source,
                file_type=".pdf",
                cause=e,
            )

    def load_and_chunk(
        self,
        source: str,
        chunker: Optional[BaseChunker] = None,
    ) -> List[Document]:
        """Load and chunk PDF file."""
        documents = self.load(source)

        if chunker:
            chunked = []
            for doc in documents:
                # Preserve page metadata in chunks
                chunks = chunker.chunk(doc.content, doc.metadata)
                chunked.extend(chunks)
            return chunked

        return documents


class MarkdownLoader(DocumentLoader):
    """Loader for Markdown files."""

    @property
    def supported_extensions(self) -> List[str]:
        return [".md", ".markdown"]

    def load(self, source: str) -> List[Document]:
        """Load a markdown file."""
        path = Path(source)

        if not path.exists():
            raise DocumentLoadError(f"File not found: {source}", source=source)

        try:
            content = path.read_text(encoding=self.encoding)

            # Extract title from first heading if present
            title = None
            lines = content.split("\n")
            for line in lines:
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            metadata = {"title": title} if title else {}
            return [self._create_document(content, source, metadata)]

        except Exception as e:
            raise DocumentLoadError(
                f"Failed to load markdown file: {e}",
                source=source,
                cause=e,
            )

    def load_and_chunk(
        self,
        source: str,
        chunker: Optional[BaseChunker] = None,
    ) -> List[Document]:
        """Load and chunk markdown file."""
        documents = self.load(source)

        if chunker:
            chunked = []
            for doc in documents:
                chunked.extend(chunker.chunk(doc.content, doc.metadata))
            return chunked

        return documents


class JSONLoader(DocumentLoader):
    """Loader for JSON files."""

    def __init__(
        self,
        content_key: str = "content",
        metadata_keys: Optional[List[str]] = None,
        encoding: str = "utf-8",
    ):
        super().__init__(encoding)
        self.content_key = content_key
        self.metadata_keys = metadata_keys or []

    @property
    def supported_extensions(self) -> List[str]:
        return [".json", ".jsonl"]

    def load(self, source: str) -> List[Document]:
        """Load a JSON file."""
        import json

        path = Path(source)

        if not path.exists():
            raise DocumentLoadError(f"File not found: {source}", source=source)

        try:
            content = path.read_text(encoding=self.encoding)
            documents = []

            # Handle JSON Lines format
            if path.suffix == ".jsonl":
                for line in content.strip().split("\n"):
                    if line.strip():
                        item = json.loads(line)
                        doc = self._process_json_item(item, source)
                        if doc:
                            documents.append(doc)
            else:
                data = json.loads(content)
                if isinstance(data, list):
                    for item in data:
                        doc = self._process_json_item(item, source)
                        if doc:
                            documents.append(doc)
                else:
                    doc = self._process_json_item(data, source)
                    if doc:
                        documents.append(doc)

            return documents

        except Exception as e:
            raise DocumentLoadError(
                f"Failed to load JSON file: {e}",
                source=source,
                cause=e,
            )

    def _process_json_item(
        self, item: Dict[str, Any], source: str
    ) -> Optional[Document]:
        """Process a JSON item into a document."""
        if self.content_key not in item:
            return None

        content = str(item[self.content_key])
        metadata = {}

        for key in self.metadata_keys:
            if key in item:
                metadata[key] = item[key]

        return self._create_document(content, source, metadata)

    def load_and_chunk(
        self,
        source: str,
        chunker: Optional[BaseChunker] = None,
    ) -> List[Document]:
        """Load and chunk JSON file."""
        documents = self.load(source)

        if chunker:
            chunked = []
            for doc in documents:
                chunked.extend(chunker.chunk(doc.content, doc.metadata))
            return chunked

        return documents


class DirectoryLoader(DocumentLoader):
    """Loader for directories of documents."""

    def __init__(
        self,
        glob_pattern: str = "*",
        recursive: bool = True,
        encoding: str = "utf-8",
    ):
        super().__init__(encoding)
        self.glob_pattern = glob_pattern
        self.recursive = recursive
        self._loaders: Dict[str, DocumentLoader] = {}
        self._register_default_loaders()

    def _register_default_loaders(self) -> None:
        """Register default loaders for common file types."""
        self.register_loader(TextLoader(self.encoding))
        self.register_loader(MarkdownLoader(self.encoding))
        self.register_loader(PDFLoader(self.encoding))

    def register_loader(self, loader: DocumentLoader) -> None:
        """Register a loader for its supported extensions."""
        for ext in loader.supported_extensions:
            self._loaders[ext.lower()] = loader

    @property
    def supported_extensions(self) -> List[str]:
        return list(self._loaders.keys())

    def load(self, source: str) -> List[Document]:
        """Load all documents from a directory."""
        path = Path(source)

        if not path.exists():
            raise DocumentLoadError(f"Directory not found: {source}", source=source)

        if not path.is_dir():
            raise DocumentLoadError(f"Not a directory: {source}", source=source)

        documents = []
        glob_method = path.rglob if self.recursive else path.glob

        for file_path in glob_method(self.glob_pattern):
            if file_path.is_file():
                ext = file_path.suffix.lower()
                loader = self._loaders.get(ext)

                if loader:
                    try:
                        docs = loader.load(str(file_path))
                        documents.extend(docs)
                        logger.debug(f"Loaded {len(docs)} documents from {file_path}")
                    except DocumentLoadError as e:
                        logger.warning(f"Failed to load {file_path}: {e}")
                else:
                    logger.debug(f"No loader for {ext}, skipping {file_path}")

        logger.info(
            f"Loaded {len(documents)} documents from {source}",
            glob_pattern=self.glob_pattern,
            recursive=self.recursive,
        )

        return documents

    def load_and_chunk(
        self,
        source: str,
        chunker: Optional[BaseChunker] = None,
    ) -> List[Document]:
        """Load and chunk all documents from directory."""
        documents = self.load(source)

        if chunker:
            chunked = []
            for doc in documents:
                chunked.extend(chunker.chunk(doc.content, doc.metadata))
            return chunked

        return documents


def create_loader(
    source: str,
    encoding: str = "utf-8",
) -> DocumentLoader:
    """
    Create appropriate loader for a file or directory.

    Args:
        source: File path or directory path
        encoding: Text encoding

    Returns:
        Appropriate document loader
    """
    path = Path(source)

    if path.is_dir():
        return DirectoryLoader(encoding=encoding)

    ext = path.suffix.lower()

    loaders = {
        ".txt": TextLoader,
        ".text": TextLoader,
        ".md": MarkdownLoader,
        ".markdown": MarkdownLoader,
        ".pdf": PDFLoader,
        ".json": JSONLoader,
        ".jsonl": JSONLoader,
    }

    loader_class = loaders.get(ext)
    if loader_class is None:
        raise UnsupportedFileTypeError(
            ext,
            supported_types=list(loaders.keys()),
        )

    return loader_class(encoding=encoding)
