from typing import List, Dict, Optional
from datetime import datetime


class ConversationMemory:
    """
    Manages conversation history and context for RAG system.
    Tracks questions, answers, and retrieved context.
    """

    def __init__(self, max_history: int = 10):
        """
        Initialize conversation memory.

        Args:
            max_history: Maximum number of conversation turns to keep
        """
        self.max_history = max_history
        self.history: List[Dict] = []
        self.session_start = datetime.now()

    def add_turn(
        self,
        question: str,
        answer: str,
        retrieved_context: Optional[List[str]] = None,
        metadata: Optional[Dict] = None
    ):
        """
        Add a conversation turn to memory.

        Args:
            question: User's question
            answer: System's answer
            retrieved_context: Documents retrieved for this turn
            metadata: Additional metadata (query type, processing info, etc.)
        """
        turn = {
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "answer": answer,
            "context": retrieved_context or [],
            "metadata": metadata or {}
        }

        self.history.append(turn)

        # Maintain max history size
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def get_last_n_turns(self, n: int = 3) -> List[Dict]:
        """
        Get the last N conversation turns.

        Args:
            n: Number of turns to retrieve

        Returns:
            List of conversation turns
        """
        return self.history[-n:] if self.history else []

    def get_full_history(self) -> List[Dict]:
        """Get complete conversation history."""
        return self.history.copy()

    def get_conversation_context(self, include_retrieved: bool = False) -> str:
        """
        Format conversation history as context string.

        Args:
            include_retrieved: Whether to include retrieved documents

        Returns:
            Formatted conversation history
        """
        if not self.history:
            return ""

        context_parts = []
        for i, turn in enumerate(self.history, 1):
            context_parts.append(f"Turn {i}:")
            context_parts.append(f"Q: {turn['question']}")
            context_parts.append(f"A: {turn['answer']}")

            if include_retrieved and turn.get('context'):
                context_parts.append(f"Context used: {len(turn['context'])} documents")

            context_parts.append("")  # Empty line between turns

        return "\n".join(context_parts)

    def get_last_question(self) -> Optional[str]:
        """Get the most recent question."""
        return self.history[-1]["question"] if self.history else None

    def get_last_answer(self) -> Optional[str]:
        """Get the most recent answer."""
        return self.history[-1]["answer"] if self.history else None

    def has_history(self) -> bool:
        """Check if there is any conversation history."""
        return len(self.history) > 0

    def clear(self):
        """Clear all conversation history."""
        self.history = []
        self.session_start = datetime.now()

    def get_contextual_summary(self, max_turns: int = 3) -> str:
        """
        Get a concise summary of recent conversation for query processing.

        Args:
            max_turns: Maximum number of recent turns to include

        Returns:
            Summary of recent conversation
        """
        recent_turns = self.get_last_n_turns(max_turns)

        if not recent_turns:
            return ""

        summary_parts = ["Recent conversation:"]
        for turn in recent_turns:
            summary_parts.append(f"- Q: {turn['question']}")
            summary_parts.append(f"  A: {turn['answer'][:100]}...")  # Truncate long answers

        return "\n".join(summary_parts)

    def get_session_stats(self) -> Dict:
        """Get statistics about the current conversation session."""
        return {
            "total_turns": len(self.history),
            "session_duration": (datetime.now() - self.session_start).total_seconds(),
            "session_start": self.session_start.isoformat()
        }
