import os
import sys
from dotenv import load_dotenv
from modules.rag.retriever import DenseRetriever
from modules.rag.generator import LLMGenerator
from modules.rag.modular_rag import ModularRAG


class SimpleRAG:
    def __init__(self, knowledge_file: str):
        self.retriever = DenseRetriever()
        self.generator = LLMGenerator()

        self.retriever.load_knowledge(knowledge_file)
        self.retriever.create_embeddings()

    def query(self, question: str, top_k: int = 3):
        print(f"\nQuestion: {question}")
        print("-" * 60)

        retrieved = self.retriever.retrieve(question, top_k=top_k)

        print(f"\nRetrieved {len(retrieved)} relevant chunks:")
        for i, (chunk, score) in enumerate(retrieved, 1):
            print(f"{i}. [Score: {score:.3f}] {chunk}")

        context_chunks = [chunk for chunk, _ in retrieved]

        print("\nGenerating answer...")
        answer = self.generator.generate(question, context_chunks)

        print(f"\nAnswer: {answer}")
        print("=" * 60)

        return answer


def main():
    load_dotenv()

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not found in environment")
        print("Please set it in your .env file")
        return

    # Determine which mode to use
    mode = "modular"  # Default to modular
    if len(sys.argv) > 1:
        if sys.argv[1] == "--simple":
            mode = "simple"
        elif sys.argv[1] == "--modular":
            mode = "modular"

    knowledge_file = "data/raw/knowledge_base.txt"

    if mode == "simple":
        print("Initializing Simple RAG System")
        print("=" * 60)
        rag = SimpleRAG(knowledge_file)
    else:
        config_path = "config/rag_config.yaml"
        if not os.path.exists(config_path):
            print(f"Warning: Config file not found at {config_path}")
            print("Using default configuration")
            config_path = None

        rag = ModularRAG(knowledge_file, config_path)

        # Print pipeline info
        print("\n" + "=" * 60)
        print("Pipeline Configuration:")
        for component, status in rag.get_pipeline_info().items():
            print(f"  {component.capitalize()}: {status}")

    print("\n" + "=" * 60)
    print(f"{'Modular' if mode == 'modular' else 'Simple'} RAG System Ready!")
    print("Type your questions below (or 'exit' to quit)")
    if mode == "modular":
        print("\nSpecial commands:")
        print("  /clear - Clear conversation history")
        print("  /stats - Show conversation statistics")
        print("  /history - Show conversation history")
    print("=" * 60)

    while True:
        try:
            question = input("\nYour question: ").strip()

            if not question:
                continue

            if question.lower() in ['exit', 'quit', 'q']:
                print("\nGoodbye!")
                break

            # Handle special commands (modular mode only)
            if mode == "modular" and question.startswith('/'):
                if question == '/clear':
                    rag.clear_conversation()
                    continue
                elif question == '/stats':
                    stats = rag.get_conversation_stats()
                    print(f"\nConversation Statistics:")
                    print(f"  Total turns: {stats['total_turns']}")
                    print(f"  Session duration: {stats['session_duration']:.0f} seconds")
                    print(f"  Session started: {stats['session_start']}")
                    continue
                elif question == '/history':
                    history = rag.memory.get_full_history()
                    if not history:
                        print("No conversation history yet")
                    else:
                        print(f"\nConversation History ({len(history)} turns):")
                        print("=" * 60)
                        for i, turn in enumerate(history, 1):
                            print(f"\nTurn {i}:")
                            print(f"Q: {turn['question']}")
                            print(f"A: {turn['answer']}")
                            if turn.get('metadata', {}).get('query_type'):
                                print(f"Type: {turn['metadata']['query_type']}")
                        print("=" * 60)
                    continue
                else:
                    print(f"Unknown command: {question}")
                    print("Available commands: /clear, /stats, /history")
                    continue

            rag.query(question)

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            print("Please try again.")


if __name__ == "__main__":
    main()
