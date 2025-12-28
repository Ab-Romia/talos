#!/usr/bin/env python3
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

from src.config import global_rag_config
from src.rag import RAGChain, ingest_documents, clear_collection, get_collection_info

_ = load_dotenv()


class Colors(str, Enum):
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


# New helpers: color_text returns a colored string; print_color prints via color_text
def color_text(string: str, color: Colors) -> str:
    return f"{color.value}{string}{Colors.RESET.value}"


def print_color(string: str, color: Colors, **kwargs):
    print(color_text(string, color), **kwargs)


def main():
    print_header()
    print_help()

    chain = None
    info = get_collection_info(global_rag_config.milvus_collection_name)
    if info and info.num_entities > 0:
        print_color(f"Found {info.num_entities} documents in collection", Colors.GREEN)
        print_color("Initializing RAG chain...", Colors.YELLOW)
        try:
            chain = RAGChain(
                collection_name=global_rag_config.milvus_collection_name,
            )
            print_color("✓ RAG chain ready\n", Colors.GREEN)
        except Exception as e:
            print_color(f"✗ Failed to initialize RAG chain: {e}\n", Colors.RED)
    else:
        print_color(
            f"⚠ No documents found in collection '{global_rag_config.milvus_collection_name}'",
            Colors.YELLOW,
        )
        print(
            f"  Use {color_text('/ingest <file_paths>', Colors.BOLD)} to add documents first\n"
        )

    while chain:
        try:
            if main_loop(chain):
                break
        except KeyboardInterrupt:
            print_color("\nGoodbye!", Colors.CYAN)
            break
        except Exception as e:
            print_color(f"✗ Error: {e}\n", Colors.RED)


def main_loop(chain: RAGChain):
    user_input = input(color_text("Query:", Colors.BOLD) + " ").strip()

    if not user_input:
        return True

    if user_input.lower() in ["/quit", "/exit"]:
        print_color("Goodbye!", Colors.CYAN)
        return False

    elif user_input.lower() == "/help":
        print_help()

    elif user_input.lower().startswith("/ingest "):
        ingest_command(user_input[8:].strip())

    elif user_input.lower() == "/clear":
        confirm = input(
            color_text(
                "Are you sure you want to clear all documents? (y/N): ",
                Colors.YELLOW,
            )
        )
        if confirm.strip().lower() == "y":
            if clear_collection(global_rag_config.milvus_collection_name):
                print_color("✓ Collection cleared successfully\n", Colors.GREEN)
            else:
                print_color(
                    "Collection doesn't exist or is already empty\n",
                    Colors.YELLOW,
                )
        else:
            print_color("Clear cancelled\n", Colors.YELLOW)

    elif user_input.lower() == "/info":
        info_command()
    else:
        query_command(chain, user_input)

    return True


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
    print("  /info                 - Show collection information")
    print("  /help                 - Show this help message")
    print("  /quit or /exit        - Exit the CLI")
    print("  <your question>       - Ask a question\n")


def ingest_command(file_paths_str: str):
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
        _, info = ingest_documents(
            file_paths=file_paths,
            collection_name=global_rag_config.milvus_collection_name,
        )

        print(f"      Loaded {info['num_documents']} document(s)")

        print()
        print_color("[2/4] Chunking text...", Colors.YELLOW)
        print(f"      Strategy: {global_rag_config.chunking_strategy}")
        print(
            f"      Chunk size: {global_rag_config.chunk_size}, Overlap: {global_rag_config.chunk_overlap}"
        )
        print(f"      Created {info['num_chunks']} chunks")

        print()
        print_color("[3/4] Generating embeddings...", Colors.YELLOW)
        print(f"      Model: {global_rag_config.embedding_model}")

        print()
        print_color("[4/4] Storing in vector database...", Colors.YELLOW)
        print(f"      Collection: {global_rag_config.milvus_collection_name}")

        print()
        print_color(
            f"✓ Successfully ingested {info['num_files']} file(s), {info['num_chunks']} chunks\n",
            Colors.GREEN,
        )
    except Exception as e:
        print()
        print_color(f"✗ Ingestion failed: {e}\n", Colors.RED)


def query_command(chain: RAGChain | None, question: str):
    if chain is None:
        print_color(
            "✗ No documents ingested yet. Use /ingest <file_paths> to add documents first\n",
            Colors.RED,
        )
        return

    streaming = global_rag_config.llm_streaming
    try:
        if streaming:
            print_color("Response:", Colors.GREEN, end=" ")
            for chunk in chain.stream_query(question):
                print(chunk, end="", flush=True)
            print("\n")
        else:
            response = chain.query(question)
            print_color("Response:", Colors.GREEN, end=" ")
            print(f"{response}\n")
    except Exception as e:
        print_color(f"✗ Query failed: {e}\n", Colors.RED)


def info_command():
    info = get_collection_info(global_rag_config.milvus_collection_name)
    if info:
        print()
        print_color("Collection Information:", Colors.CYAN)
        print(f"  Name: {info.name}")
        print(f"  Documents: {info.num_entities}\n")
    else:
        print_color("✗ Failed to get collection info\n", Colors.RED)


if __name__ == "__main__":
    main()
