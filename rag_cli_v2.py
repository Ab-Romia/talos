#!/usr/bin/env python3

import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from src_v2.pipeline.rag_chain import RAGChain, ingest_documents
from src_v2.vectorstore.milvus_store import clear_collection, get_collection_info
from src_v2.config.settings import settings


class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


def print_header():
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'RAG System v2'.center(60)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}\n")
    print(f"Model: {settings.openai_model}")
    print(f"Collection: {settings.milvus_collection_name}")
    print(f"Retrieval: {'Hybrid + Reranking' if settings.use_reranking else 'Dense Vector Search'}")
    print(f"Milvus: {settings.milvus_host}:{settings.milvus_port}\n")


def print_help():
    print(f"{Colors.YELLOW}Available Commands:{Colors.RESET}")
    print("  /ingest <file_paths>  - Ingest documents (comma-separated paths)")
    print("  /clear                - Clear all ingested documents")
    print("  /info                 - Show collection information")
    print("  /help                 - Show this help message")
    print("  /quit or /exit        - Exit the CLI")
    print("  <your question>       - Ask a question\n")


def ingest_command(file_paths_str: str):
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
        return True
    except Exception as e:
        print(f"\n{Colors.RED}✗ Ingestion failed: {e}{Colors.RESET}\n")
        return False


def query_command(chain: RAGChain, question: str, streaming: bool = True):
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
    print_header()
    print_help()

    chain = None
    try:
        info = get_collection_info(settings.milvus_collection_name)
        if info['exists'] and info['num_entities'] > 0:
            print(f"{Colors.GREEN}Found {info['num_entities']} documents in collection{Colors.RESET}")
            print(f"{Colors.YELLOW}Initializing RAG chain...{Colors.RESET}")
            try:
                chain = RAGChain(
                    collection_name=settings.milvus_collection_name,
                    use_memory=True
                )
                print(f"{Colors.GREEN}✓ RAG chain ready{Colors.RESET}\n")
            except Exception as e:
                print(f"{Colors.RED}✗ Failed to initialize RAG chain: {e}{Colors.RESET}\n")
        else:
            print(f"{Colors.YELLOW}⚠ No documents found in collection '{settings.milvus_collection_name}'")
            print(f"  Use /ingest <file_paths> to add documents first{Colors.RESET}\n")
    except:
        print(f"{Colors.YELLOW}⚠ Collection not found. Use /ingest to add documents{Colors.RESET}\n")

    while True:
        try:
            user_input = input(f"{Colors.BOLD}Query:{Colors.RESET} ").strip()

            if not user_input:
                continue

            if user_input.lower() in ["/quit", "/exit"]:
                print(f"{Colors.CYAN}Goodbye!{Colors.RESET}")
                break

            elif user_input.lower() == "/help":
                print_help()

            elif user_input.lower().startswith("/ingest "):
                file_paths = user_input[8:].strip()
                if ingest_command(file_paths):
                    print(f"{Colors.YELLOW}Initializing RAG chain...{Colors.RESET}")
                    try:
                        chain = RAGChain(
                            collection_name=settings.milvus_collection_name,
                            use_memory=True
                        )
                        print(f"{Colors.GREEN}✓ RAG chain ready{Colors.RESET}\n")
                    except Exception as e:
                        print(f"{Colors.RED}✗ Failed to initialize RAG chain: {e}{Colors.RESET}\n")
                        chain = None

            elif user_input.lower() == "/clear":
                confirm = input(f"{Colors.YELLOW}Are you sure you want to clear all documents? (yes/no): {Colors.RESET}").strip().lower()
                if confirm == "yes":
                    try:
                        if clear_collection(settings.milvus_collection_name):
                            print(f"{Colors.GREEN}✓ Collection cleared successfully{Colors.RESET}\n")
                            chain = None
                        else:
                            print(f"{Colors.YELLOW}Collection doesn't exist or is already empty{Colors.RESET}\n")
                    except Exception as e:
                        print(f"{Colors.RED}✗ Failed to clear collection: {e}{Colors.RESET}\n")
                else:
                    print(f"{Colors.YELLOW}Clear cancelled{Colors.RESET}\n")

            elif user_input.lower() == "/info":
                try:
                    info = get_collection_info(settings.milvus_collection_name)
                    print(f"\n{Colors.CYAN}Collection Information:{Colors.RESET}")
                    print(f"  Name: {info['name']}")
                    print(f"  Exists: {info['exists']}")
                    print(f"  Documents: {info['num_entities']}\n")
                except Exception as e:
                    print(f"{Colors.RED}✗ Failed to get collection info: {e}{Colors.RESET}\n")

            else:
                if chain is None:
                    print(f"{Colors.RED}✗ No documents ingested yet. Use /ingest <file_paths> to add documents first{Colors.RESET}\n")
                else:
                    query_command(chain, user_input, streaming=settings.llm_streaming)

        except KeyboardInterrupt:
            print(f"\n{Colors.CYAN}Goodbye!{Colors.RESET}")
            break
        except Exception as e:
            print(f"{Colors.RED}✗ Error: {e}{Colors.RESET}\n")


if __name__ == "__main__":
    main()
