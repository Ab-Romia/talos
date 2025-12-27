#!/usr/bin/env python3
"""
RAG CLI v2 - Advanced Retrieval-Augmented Generation System
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src_v2.pipeline.rag_chain import RAGChain, ingest_documents
from src_v2.config.settings import settings


class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


def print_header():
    """Print CLI header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'RAG System v2'.center(60)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}\n")
    print(f"Model: {settings.openai_model}")
    print(f"Collection: {settings.milvus_collection_name}")
    print(f"Retrieval: {'Hybrid + Reranking' if settings.use_reranking else 'Dense Vector Search'}")
    print(f"Milvus: {settings.milvus_host}:{settings.milvus_port}\n")


def print_help():
    """Print available commands."""
    print(f"{Colors.YELLOW}Available Commands:{Colors.RESET}")
    print("  /ingest <file_paths>  - Ingest documents (comma-separated paths)")
    print("  /help                 - Show this help message")
    print("  /quit or /exit        - Exit the CLI")
    print("  <your question>       - Ask a question\n")


def ingest_command(file_paths_str: str):
    """Handle document ingestion."""
    file_paths = [p.strip() for p in file_paths_str.split(',')]

    print(f"\n{Colors.YELLOW}[1/4] Loading documents...{Colors.RESET}")
    print(f"      Files: {', '.join([Path(p).name for p in file_paths])}")

    try:
        vectorstore, info = ingest_documents(
            file_paths=file_paths,
            collection_name=settings.milvus_collection_name
        )

        print(f"      Loaded {info['num_documents']} document(s)")

        print(f"\n{Colors.YELLOW}[2/4] Chunking text...{Colors.RESET}")
        print(f"      Strategy: {settings.chunking_strategy}")
        print(f"      Chunk size: {settings.chunk_size}, Overlap: {settings.chunk_overlap}")
        print(f"      Created {info['num_chunks']} chunks")

        print(f"\n{Colors.YELLOW}[3/4] Generating embeddings...{Colors.RESET}")
        print(f"      Model: {settings.embedding_model}")

        print(f"\n{Colors.YELLOW}[4/4] Storing in vector database...{Colors.RESET}")
        print(f"      Collection: {settings.milvus_collection_name}")

        print(f"\n{Colors.GREEN}✓ Successfully ingested {info['num_files']} file(s), {info['num_chunks']} chunks{Colors.RESET}\n")
    except Exception as e:
        print(f"\n{Colors.RED}✗ Ingestion failed: {e}{Colors.RESET}\n")


def query_command(chain: RAGChain, question: str, streaming: bool = True):
    """Handle query."""
    if streaming:
        print(f"{Colors.GREEN}Response:{Colors.RESET} ", end="", flush=True)
        try:
            for chunk in chain.stream_query(question):
                print(chunk, end="", flush=True)
            print("\n")
        except Exception as e:
            print(f"\n{Colors.RED}✗ Query failed: {e}{Colors.RESET}\n")
    else:
        try:
            response = chain.query(question)
            print(f"{Colors.GREEN}Response:{Colors.RESET} {response}\n")
        except Exception as e:
            print(f"{Colors.RED}✗ Query failed: {e}{Colors.RESET}\n")


def main():
    """Main CLI loop."""
    print_header()
    print_help()

    # Initialize RAG chain
    print(f"{Colors.YELLOW}Initializing RAG chain...{Colors.RESET}")
    try:
        chain = RAGChain(
            collection_name=settings.milvus_collection_name,
            use_memory=True
        )
        print(f"{Colors.GREEN}✓ RAG chain initialized{Colors.RESET}\n")
    except Exception as e:
        print(f"{Colors.RED}✗ Initialization failed: {e}{Colors.RESET}")
        print(f"{Colors.YELLOW}Make sure Milvus is running and .env is configured{Colors.RESET}")
        sys.exit(1)

    # Main loop
    while True:
        try:
            user_input = input(f"{Colors.BOLD}Query:{Colors.RESET} ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.lower() in ["/quit", "/exit"]:
                print(f"{Colors.CYAN}Goodbye!{Colors.RESET}")
                break

            elif user_input.lower() == "/help":
                print_help()

            elif user_input.lower().startswith("/ingest "):
                file_paths = user_input[8:].strip()
                ingest_command(file_paths)

            else:
                # Regular query
                query_command(chain, user_input, streaming=settings.llm_streaming)

        except KeyboardInterrupt:
            print(f"\n{Colors.CYAN}Goodbye!{Colors.RESET}")
            break
        except Exception as e:
            print(f"{Colors.RED}✗ Error: {e}{Colors.RESET}\n")


if __name__ == "__main__":
    main()
