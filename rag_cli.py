#!/usr/bin/env python3
"""
Talos RAG CLI - Interactive Command-Line Interface for Testing the RAG System

This CLI provides a comprehensive way to test and demonstrate all components
of the modular RAG pipeline including:
- Document ingestion with various chunking strategies
- Query processing (rewriting, expansion, HyDE)
- Hybrid retrieval (dense + sparse)
- Cross-encoder reranking
- LLM generation with citations
- Conversation memory

Usage:
    python rag_cli.py                    # Interactive mode
    python rag_cli.py --simple           # Simple mode (no advanced features)
    python rag_cli.py --verbose          # Verbose output showing all steps
    python rag_cli.py --config path.yaml # Custom config file
"""

import os
import sys
import argparse
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def print_header(text: str):
    """Print a styled header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(60)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}\n")


def print_step(step_name: str, description: str = ""):
    """Print a pipeline step indicator."""
    print(f"{Colors.YELLOW}[{step_name}]{Colors.RESET} {description}")


def print_substep(text: str):
    """Print a substep or detail."""
    print(f"  {Colors.DIM}→ {text}{Colors.RESET}")


def print_success(text: str):
    """Print a success message."""
    print(f"{Colors.GREEN}✓ {text}{Colors.RESET}")


def print_error(text: str):
    """Print an error message."""
    print(f"{Colors.RED}✗ {text}{Colors.RESET}")


def print_info(text: str):
    """Print an info message."""
    print(f"{Colors.BLUE}ℹ {text}{Colors.RESET}")


def format_time(seconds: float) -> str:
    """Format time duration."""
    if seconds < 1:
        return f"{seconds*1000:.1f}ms"
    return f"{seconds:.2f}s"


class RAGCLIDemo:
    """Interactive RAG CLI demonstration."""

    def __init__(self, config_path: Optional[str] = None, simple_mode: bool = False, verbose: bool = True):
        self.config_path = config_path or "config/rag_config.yaml"
        self.simple_mode = simple_mode
        self.verbose = verbose
        self.pipeline = None
        self.documents_loaded = False
        self.document_count = 0

        # Check API key
        if not os.getenv("OPENAI_API_KEY"):
            print_error("OPENAI_API_KEY not set. Please configure it in .env file")
            print_info("Create a .env file with: OPENAI_API_KEY=your-key-here")
            sys.exit(1)

    def initialize(self):
        """Initialize the RAG pipeline."""
        print_header("Initializing Talos RAG System")

        try:
            start_time = time.time()

            print_step("Loading Configuration", self.config_path)

            # Try to import the new modular RAG system
            try:
                from src.orchestration.rag_pipeline import RAGPipeline
                from src.core.config_loader import RAGConfig

                if Path(self.config_path).exists():
                    config = RAGConfig.from_yaml(self.config_path)
                else:
                    print_substep("Using default configuration")
                    config = RAGConfig()

                config = config.update_from_env()
                self.pipeline = RAGPipeline(config=config)

                print_success("Using modular RAG pipeline from src/")

            except ImportError as e:
                print_substep(f"Modular RAG not available: {e}")
                print_substep("Falling back to simple mode")
                self.simple_mode = True
                self.pipeline = SimplePipeline()

            elapsed = time.time() - start_time
            print_success(f"Pipeline initialized in {format_time(elapsed)}")

            # Show pipeline configuration
            if hasattr(self.pipeline, 'get_pipeline_info'):
                info = self.pipeline.get_pipeline_info()
                print_info("Pipeline Configuration:")
                for key, value in info.items():
                    print_substep(f"{key}: {value}")

        except Exception as e:
            print_error(f"Failed to initialize pipeline: {e}")
            raise

    def load_documents(self, paths: List[str]):
        """Load and ingest documents."""
        print_header("Document Ingestion")

        total_chunks = 0
        total_docs = 0

        for path in paths:
            path = Path(path)

            if not path.exists():
                print_error(f"File not found: {path}")
                continue

            print_step("Loading", str(path))
            start_time = time.time()

            try:
                if path.is_dir():
                    # Load all files from directory
                    files = list(path.glob("**/*.*"))
                    print_substep(f"Found {len(files)} files in directory")

                    for file in files:
                        if file.suffix.lower() in ['.txt', '.md', '.pdf', '.json']:
                            result = self._ingest_file(file)
                            if result:
                                total_chunks += result.get('chunks_created', 0)
                                total_docs += 1
                else:
                    result = self._ingest_file(path)
                    if result:
                        total_chunks += result.get('chunks_created', 0)
                        total_docs += 1

                elapsed = time.time() - start_time
                print_success(f"Loaded in {format_time(elapsed)}")

            except Exception as e:
                print_error(f"Failed to load {path}: {e}")

        self.documents_loaded = total_docs > 0
        self.document_count = total_docs

        print_info(f"Total: {total_docs} documents, {total_chunks} chunks")

    def _ingest_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Ingest a single file."""
        print_substep(f"Processing: {file_path.name}")

        if hasattr(self.pipeline, 'ingest_file'):
            result = self.pipeline.ingest_file(str(file_path))
            if self.verbose:
                print_substep(f"Created {result.get('chunks_created', 0)} chunks")
            return result
        else:
            # Simple mode - just read content
            with open(file_path, 'r', errors='ignore') as f:
                content = f.read()
            self.pipeline.add_document(content, {"source": str(file_path)})
            return {"chunks_created": 1}

    def query(self, question: str) -> Dict[str, Any]:
        """Execute a query with full pipeline visualization."""
        print_header("RAG Query Pipeline")

        result = {
            "question": question,
            "steps": [],
            "answer": "",
            "sources": [],
            "timing": {}
        }

        total_start = time.time()

        # Step 1: Query Classification
        print_step("Step 1: Query Classification")
        step_start = time.time()

        query_type = "general"
        if hasattr(self.pipeline, 'query_router') and self.pipeline.query_router:
            try:
                query_type = self.pipeline.query_router.classify(question)
                print_substep(f"Query Type: {query_type}")

                if hasattr(self.pipeline.query_router, 'get_pipeline_config'):
                    config = self.pipeline.query_router.get_pipeline_config(query_type)
                    print_substep(f"Strategy: {config.get('strategy', 'default')}")
            except Exception as e:
                print_substep(f"Classification skipped: {e}")

        result["timing"]["classification"] = time.time() - step_start
        result["steps"].append({"name": "Classification", "query_type": query_type})

        # Step 2: Query Processing
        print_step("Step 2: Query Processing")
        step_start = time.time()

        processed_query = question
        processing_info = {}

        if hasattr(self.pipeline, 'query_processor') and self.pipeline.query_processor:
            try:
                proc_result = self.pipeline.query_processor.process(question)
                processed_query = proc_result.get('processed_query', question)

                if processed_query != question:
                    print_substep(f"Original: {question}")
                    print_substep(f"Processed: {processed_query}")
                else:
                    print_substep("No query transformation applied")

                if proc_result.get('hypothetical_doc'):
                    print_substep("Generated hypothetical document (HyDE)")

                processing_info = proc_result
            except Exception as e:
                print_substep(f"Processing skipped: {e}")
        else:
            print_substep("Query processor disabled")

        result["timing"]["processing"] = time.time() - step_start
        result["steps"].append({"name": "Processing", "processed_query": processed_query})

        # Step 3: Retrieval
        print_step("Step 3: Document Retrieval")
        step_start = time.time()

        retrieved_docs = []
        if hasattr(self.pipeline, 'hybrid_retriever'):
            try:
                retrieval_result = self.pipeline.hybrid_retriever.retrieve(
                    processed_query,
                    top_k=10
                )
                retrieved_docs = retrieval_result.documents if hasattr(retrieval_result, 'documents') else []

                print_substep(f"Retrieved {len(retrieved_docs)} documents")

                if self.verbose and retrieved_docs:
                    print_substep("Top 3 retrieved documents:")
                    for i, doc in enumerate(retrieved_docs[:3]):
                        content_preview = doc.content[:100] + "..." if len(doc.content) > 100 else doc.content
                        score = getattr(doc, 'score', 'N/A')
                        print(f"      {i+1}. [Score: {score:.3f}] {content_preview}")

            except Exception as e:
                print_substep(f"Hybrid retrieval failed: {e}")
        elif hasattr(self.pipeline, 'dense_retriever'):
            try:
                retrieval_result = self.pipeline.dense_retriever.retrieve(
                    processed_query,
                    top_k=10
                )
                retrieved_docs = retrieval_result.documents if hasattr(retrieval_result, 'documents') else []
                print_substep(f"Retrieved {len(retrieved_docs)} documents (dense only)")
            except Exception as e:
                print_substep(f"Dense retrieval failed: {e}")

        result["timing"]["retrieval"] = time.time() - step_start
        result["steps"].append({"name": "Retrieval", "doc_count": len(retrieved_docs)})

        # Step 4: Reranking
        print_step("Step 4: Reranking")
        step_start = time.time()

        reranked_docs = retrieved_docs
        if hasattr(self.pipeline, 'reranker') and self.pipeline.reranker and retrieved_docs:
            try:
                reranked_docs = self.pipeline.reranker.rerank(
                    question,
                    retrieved_docs,
                    top_n=5
                )
                print_substep(f"Reranked to top {len(reranked_docs)} documents")

                if self.verbose and reranked_docs:
                    print_substep("Reranked documents:")
                    for i, doc in enumerate(reranked_docs[:3]):
                        content_preview = doc.content[:80] + "..." if len(doc.content) > 80 else doc.content
                        score = getattr(doc, 'score', 'N/A')
                        print(f"      {i+1}. [Relevance: {score:.3f}] {content_preview}")

            except Exception as e:
                print_substep(f"Reranking skipped: {e}")
        else:
            print_substep("Reranker disabled or no documents to rerank")

        result["timing"]["reranking"] = time.time() - step_start
        result["steps"].append({"name": "Reranking", "doc_count": len(reranked_docs)})

        # Step 5: Context Compression (if enabled)
        print_step("Step 5: Context Compression")
        step_start = time.time()

        compressed_docs = reranked_docs
        if hasattr(self.pipeline, 'context_compressor') and self.pipeline.context_compressor:
            try:
                compressed_docs = self.pipeline.context_compressor.compress(
                    question,
                    reranked_docs
                )
                print_substep(f"Compressed context from {len(reranked_docs)} to {len(compressed_docs)} docs")
            except Exception as e:
                print_substep(f"Compression skipped: {e}")
        else:
            print_substep("Context compression disabled")

        result["timing"]["compression"] = time.time() - step_start
        result["steps"].append({"name": "Compression", "doc_count": len(compressed_docs)})

        # Step 6: Answer Generation
        print_step("Step 6: Answer Generation")
        step_start = time.time()

        try:
            if hasattr(self.pipeline, 'llm_service') and compressed_docs:
                generation_result = self.pipeline.llm_service.generate(
                    query=question,
                    context=compressed_docs,
                )
                answer = generation_result.answer
                print_substep(f"Generated answer ({len(answer)} chars)")
                print_substep(f"Tokens: {generation_result.prompt_tokens} prompt, {generation_result.completion_tokens} completion")
            elif hasattr(self.pipeline, 'query'):
                # Fallback to full pipeline query
                full_result = self.pipeline.query(question)
                answer = full_result.answer if hasattr(full_result, 'answer') else str(full_result)
                compressed_docs = full_result.sources if hasattr(full_result, 'sources') else []
            else:
                answer = "Pipeline not properly initialized for generation."

        except Exception as e:
            answer = f"Generation failed: {e}"
            print_error(str(e))

        result["timing"]["generation"] = time.time() - step_start
        result["steps"].append({"name": "Generation", "answer_length": len(answer)})

        # Final results
        total_time = time.time() - total_start
        result["timing"]["total"] = total_time
        result["answer"] = answer
        result["sources"] = [
            {
                "content": doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
                "score": getattr(doc, 'score', None),
                "metadata": getattr(doc, 'metadata', {})
            }
            for doc in compressed_docs
        ]

        # Print answer
        print_header("Answer")
        print(answer)

        # Print sources
        if result["sources"] and self.verbose:
            print(f"\n{Colors.CYAN}Sources ({len(result['sources'])}){Colors.RESET}")
            for i, source in enumerate(result["sources"][:3]):
                print(f"  {i+1}. {source['content'][:100]}...")

        # Print timing summary
        print(f"\n{Colors.CYAN}Timing Summary{Colors.RESET}")
        for step_name, duration in result["timing"].items():
            if step_name != "total":
                print(f"  {step_name}: {format_time(duration)}")
        print(f"  {Colors.BOLD}Total: {format_time(total_time)}{Colors.RESET}")

        return result

    def interactive_loop(self):
        """Run interactive query loop."""
        print_header("Interactive Mode")
        print_info("Commands:")
        print("  /load <path>  - Load document(s)")
        print("  /clear        - Clear conversation history")
        print("  /info         - Show pipeline info")
        print("  /verbose      - Toggle verbose output")
        print("  /help         - Show this help")
        print("  /quit         - Exit")
        print("")

        while True:
            try:
                user_input = input(f"{Colors.GREEN}You>{Colors.RESET} ").strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    self._handle_command(user_input)
                else:
                    self.query(user_input)

            except KeyboardInterrupt:
                print("\n")
                print_info("Goodbye!")
                break
            except EOFError:
                print_info("Goodbye!")
                break

    def _handle_command(self, command: str):
        """Handle CLI commands."""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/quit" or cmd == "/exit":
            print_info("Goodbye!")
            sys.exit(0)

        elif cmd == "/load":
            if not arg:
                print_error("Usage: /load <path>")
            else:
                self.load_documents([arg])

        elif cmd == "/clear":
            if hasattr(self.pipeline, 'clear_memory'):
                self.pipeline.clear_memory()
            print_success("Conversation history cleared")

        elif cmd == "/info":
            if hasattr(self.pipeline, 'get_pipeline_info'):
                info = self.pipeline.get_pipeline_info()
                print_info("Pipeline Information:")
                for key, value in info.items():
                    print(f"  {key}: {value}")
            else:
                print_info("Simple pipeline mode")

        elif cmd == "/verbose":
            self.verbose = not self.verbose
            print_success(f"Verbose mode: {'ON' if self.verbose else 'OFF'}")

        elif cmd == "/help":
            print_info("Available commands:")
            print("  /load <path>  - Load document(s) from path")
            print("  /clear        - Clear conversation history")
            print("  /info         - Show pipeline configuration")
            print("  /verbose      - Toggle verbose output")
            print("  /quit         - Exit the CLI")

        else:
            print_error(f"Unknown command: {cmd}")


class SimplePipeline:
    """Simple fallback pipeline when modular RAG is not available."""

    def __init__(self):
        self.documents = []

    def add_document(self, content: str, metadata: dict = None):
        self.documents.append({"content": content, "metadata": metadata or {}})

    def query(self, question: str):
        # Simple keyword matching
        results = []
        for doc in self.documents:
            if any(word.lower() in doc["content"].lower() for word in question.split()):
                results.append(doc)

        if results:
            context = "\n".join([r["content"][:500] for r in results[:3]])
            return f"Based on the documents:\n\n{context}\n\n(Simple mode - no LLM generation)"
        return "No relevant documents found."


def main():
    parser = argparse.ArgumentParser(
        description="Talos RAG CLI - Interactive RAG System Testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rag_cli.py                           # Start interactive mode
  python rag_cli.py --simple                  # Simple mode without advanced features
  python rag_cli.py --config my_config.yaml   # Use custom configuration
  python rag_cli.py --load data/docs/         # Pre-load documents
        """
    )

    parser.add_argument(
        "--simple", "-s",
        action="store_true",
        help="Run in simple mode without advanced RAG features"
    )

    parser.add_argument(
        "--config", "-c",
        type=str,
        default="config/rag_config.yaml",
        help="Path to configuration file"
    )

    parser.add_argument(
        "--load", "-l",
        type=str,
        nargs="+",
        help="Pre-load document(s) from path(s)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=True,
        help="Enable verbose output (default: True)"
    )

    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Disable verbose output"
    )

    args = parser.parse_args()

    # Print banner
    print(f"""
{Colors.CYAN}╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   ████████╗ █████╗ ██╗      ██████╗ ███████╗             ║
║   ╚══██╔══╝██╔══██╗██║     ██╔═══██╗██╔════╝             ║
║      ██║   ███████║██║     ██║   ██║███████╗             ║
║      ██║   ██╔══██║██║     ██║   ██║╚════██║             ║
║      ██║   ██║  ██║███████╗╚██████╔╝███████║             ║
║      ╚═╝   ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝             ║
║                                                          ║
║          RAG System - Interactive CLI                    ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝{Colors.RESET}
    """)

    verbose = args.verbose and not args.quiet

    # Initialize CLI
    cli = RAGCLIDemo(
        config_path=args.config,
        simple_mode=args.simple,
        verbose=verbose
    )

    # Initialize pipeline
    cli.initialize()

    # Load documents if specified
    if args.load:
        cli.load_documents(args.load)

    # Start interactive loop
    cli.interactive_loop()


if __name__ == "__main__":
    main()
