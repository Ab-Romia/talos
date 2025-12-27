from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownTextSplitter
)
from src_v2.config.settings import settings


def get_text_splitter(strategy: str | None = None):
    if strategy is None:
        strategy = settings.chunking_strategy

    if strategy == "recursive":
        return RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    elif strategy == "markdown":
        return MarkdownTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap
        )

    else:
        raise ValueError(f"Unknown chunking strategy: {strategy}")