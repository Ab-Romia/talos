#!/usr/bin/env python3
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

from model.config import global_rag_config
from src.rag import clear_collection, get_collection_info
from src.rag.rag_chain import RAGChain

_ = load_dotenv()


class Colors(str, Enum):
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def main():
    print_header()
    print_help()

    rag = RAGChain(global_rag_config.milvus_collection_name)
    info = get_collection_info(rag.collection_name)
    print_color("✓ RAG rag ready\n", Colors.GREEN)

    if info and info.num_entities > 0:
        print_color(f"Found {info.num_entities} documents in collection", Colors.GREEN)
        print_color("Initializing RAG rag...", Colors.YELLOW)
    else:
        print_color(
            f"⚠ No documents found in collection '{rag.collection_name}'",
            Colors.YELLOW,
        )
        print(
            f"  Use {color_text('/ingest <file_paths>', Colors.BOLD)} to add documents first\n"
        )

    while True:
        try:
            if not main_loop(rag):
                break
        except KeyboardInterrupt:
            print_color("\nGoodbye!", Colors.CYAN)
            break
        except Exception as e:
            print_color(f"✗ Error: {e}\n", Colors.RED)


def main_loop(rag: RAGChain):
    user_input = input(color_text("Query:", Colors.BOLD) + " ").strip()

    if not user_input:
        return True

    parts = user_input.split(" ", 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    match cmd:
        case "/quit" | "/exit":
            print_color("Goodbye!", Colors.CYAN)
            return False
        case "/help":
            print_help()
        case "/ingest":
            ingest_command(rag, arg)
        case "/clear":
            clear_command(rag)

        case _:
            query_command(rag, user_input)

    return True


def clear_command(rag: RAGChain):
    confirm = input(
        color_text(
            "Are you sure you want to clear all documents? (y/N): ",
            Colors.YELLOW,
        )
    )
    if confirm.strip().lower() == "y":
        if clear_collection(rag.collection_name):
            print_color("✓ Collection cleared successfully\n", Colors.GREEN)
        else:
            print_color(
                "Collection doesn't exist or is already empty\n",
                Colors.YELLOW,
            )
    else:
        print_color("Clear cancelled\n", Colors.YELLOW)


def color_text(string: str, color: Colors) -> str:
    return f"{color.value}{string}{Colors.RESET.value}"


def print_color(string: str, color: Colors, **kwargs):
    print(color_text(string, color), **kwargs)


def print_header():
    banner = r"""
    ████████╗ █████╗ ██╗      ██████╗ ███████╗
    ╚══██╔══╝██╔══██╗██║     ██╔═══██╗██╔════╝
       ██║   ███████║██║     ██║   ██║███████╗
       ██║   ██╔══██║██║     ██║   ██║╚════██║
       ██║   ██║  ██║███████╗╚██████╔╝███████║
       ╚═╝   ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝
       
    Retrieval-Augmented Generation CLI
    V.2.0
    """
    banner_len = max(len(line) for line in banner.splitlines()) + 12
    lines = [
        "╔" + "═" * banner_len + "╗",
        *(f"║{line.center(banner_len)}║" for line in banner.splitlines()),
        "╚" + "═" * banner_len + "╝",
    ]
    mapping = {c: color_text(c, Colors.BLUE) for c in ["╔", "═", "╗", "║", "╚", "╝"]}

    for line in lines:
        print("".join(mapping.get(ch, ch) for ch in line))

    print_color("Configuration:", Colors.BLUE)
    print(f"Model: {global_rag_config.openai_model}")
    print(f"Collection: {global_rag_config.milvus_collection_name}")
    print(
        f"Retrieval: {'Hybrid + Reranking' if global_rag_config.use_reranking else 'Dense Vector Search'}"
    )
    print(f"Milvus: {global_rag_config.milvus_host}:{global_rag_config.milvus_port}\n")


def print_help():
    print_color("Available Commands:", Colors.YELLOW)
    print("  /ingest <file_paths>  - Ingest documents (comma-separated paths)")
    print("  /clear                - Clear all ingested documents")
    print("  /help                 - Show this help message")
    print("  /quit or /exit        - Exit the CLI")
    print("  <your question>       - Ask a question\n")


def ingest_command(rag: RAGChain, file_paths_str: str):
    import asyncio

    if not file_paths_str:
        print_color(
            "✗ Please provide file paths to ingest. Usage: /ingest <file_paths>\n",
            Colors.RED,
        )
        return

    file_paths = [p.strip() for p in file_paths_str.split(",")]

    print()
    print_color("[1/4] Loading documents...", Colors.YELLOW)
    for p in file_paths:
        path = Path(p)
        if path.is_dir():
            print(f"      Scanning directory: {p}")
        else:
            print(f"      File: {path.name}")

    try:
        docs_ids = asyncio.run(rag.ingest_documents(file_paths=file_paths))
        print_color(f"✓ {len(docs_ids)} documents added\n", Colors.GREEN)
    except Exception as e:
        print()
        print_color(f"✗ Ingestion failed: {e}\n", Colors.RED)


def query_command(rag: RAGChain | None, question: str):
    if rag is None:
        print_color(
            "✗ No documents ingested yet. Use /ingest <file_paths> to add documents first\n",
            Colors.RED,
        )
        return

    streaming = global_rag_config.llm_streaming
    try:
        if streaming:
            print_color("Response:", Colors.GREEN, end=" ")
            for chunk in rag.stream_query(question):
                print(chunk, end="", flush=True)
            print("\n")
        else:
            response = rag.query(question)
            print_color("Response:", Colors.GREEN, end=" ")
            print(f"{response}\n")
    except Exception as e:
        print_color(f"✗ Query failed: {e}\n", Colors.RED)


if __name__ == "__main__":
    main()
