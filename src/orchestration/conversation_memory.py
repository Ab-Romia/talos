"""
Conversation memory for maintaining context across turns.

Stores and manages conversation history for contextual responses.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.base_interfaces import BaseMemory, Document
from src.core.config_loader import MemoryConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ConversationTurn:
    """Represents a single conversation turn."""

    question: str
    answer: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    retrieved_context: List[Document] = field(default_factory=list)


class ConversationMemory(BaseMemory):
    """
    Conversation memory for RAG systems.

    Maintains history and provides context for follow-up queries.
    """

    def __init__(self, config: Optional[MemoryConfig] = None):
        """
        Initialize conversation memory.

        Args:
            config: Memory configuration
        """
        self.config = config or MemoryConfig()
        self._history: List[ConversationTurn] = []
        self._session_start = datetime.now()

    def add_turn(
        self,
        question: str,
        answer: str,
        metadata: Optional[Dict[str, Any]] = None,
        retrieved_context: Optional[List[Document]] = None,
    ) -> None:
        """
        Add a conversation turn.

        Args:
            question: User question
            answer: Assistant answer
            metadata: Optional metadata
            retrieved_context: Optional retrieved documents
        """
        turn = ConversationTurn(
            question=question,
            answer=answer,
            metadata=metadata or {},
            retrieved_context=retrieved_context or [],
        )
        self._history.append(turn)

        # Trim to max history
        if len(self._history) > self.config.max_history:
            self._history = self._history[-self.config.max_history:]

        logger.debug(f"Added conversation turn, history size: {len(self._history)}")

    def get_history(self, max_turns: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get conversation history.

        Args:
            max_turns: Maximum turns to return

        Returns:
            List of turn dictionaries
        """
        turns = self._history
        if max_turns:
            turns = turns[-max_turns:]

        return [
            {
                "question": turn.question,
                "answer": turn.answer,
                "timestamp": turn.timestamp.isoformat(),
                "metadata": turn.metadata,
            }
            for turn in turns
        ]

    def get_context_string(self, max_turns: Optional[int] = None) -> str:
        """
        Get conversation history as formatted string.

        Args:
            max_turns: Maximum turns to include

        Returns:
            Formatted conversation string
        """
        turns = self._history
        if max_turns:
            turns = turns[-max_turns:]

        if not turns:
            return ""

        lines = ["Previous conversation:"]
        for turn in turns:
            lines.append(f"User: {turn.question}")
            lines.append(f"Assistant: {turn.answer}")
            lines.append("")

        return "\n".join(lines)

    def get_last_turn(self) -> Optional[ConversationTurn]:
        """Get the most recent turn."""
        return self._history[-1] if self._history else None

    def get_last_n_turns(self, n: int) -> List[ConversationTurn]:
        """Get last N turns."""
        return self._history[-n:] if self._history else []

    def has_history(self) -> bool:
        """Check if there is any history."""
        return len(self._history) > 0

    def clear(self) -> None:
        """Clear conversation history."""
        self._history = []
        self._session_start = datetime.now()
        logger.debug("Conversation history cleared")

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        total_questions = len(self._history)
        avg_answer_length = 0
        if total_questions > 0:
            avg_answer_length = sum(len(t.answer) for t in self._history) / total_questions

        return {
            "session_start": self._session_start.isoformat(),
            "total_turns": total_questions,
            "avg_answer_length": round(avg_answer_length),
            "duration_minutes": (datetime.now() - self._session_start).seconds / 60,
        }

    def get_contextual_summary(self, max_turns: int = 3) -> str:
        """
        Get a contextual summary of recent conversation.

        Args:
            max_turns: Maximum turns to summarize

        Returns:
            Summary string
        """
        if not self._history:
            return ""

        recent = self._history[-max_turns:]

        # Build context summary
        topics = []
        for turn in recent:
            # Extract key phrases from questions
            question = turn.question.lower()
            topics.append(question[:50])

        return f"Recent topics discussed: {'; '.join(topics)}"
