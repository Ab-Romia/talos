"""
Query router for adaptive RAG pipelines.

Classifies queries and routes to appropriate processing strategies.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from src.core.base_interfaces import BaseQueryRouter
from src.core.config_loader import OrchestrationConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class QueryType(Enum):
    """Types of queries for routing."""

    FACTUAL = "factual"  # Direct fact questions
    ANALYTICAL = "analytical"  # Concept explanation/analysis
    COMPARATIVE = "comparative"  # Multiple item comparisons
    PROCEDURAL = "procedural"  # How-to, process questions
    CONVERSATIONAL = "conversational"  # Follow-up, context-dependent
    EXPLORATORY = "exploratory"  # Broad overview questions
    UNCLEAR = "unclear"  # Vague or ambiguous


class QueryRouter(BaseQueryRouter):
    """
    Query router for adaptive pipeline configuration.

    Classifies queries and returns optimal pipeline settings.
    """

    def __init__(
        self,
        config: OrchestrationConfig,
        knowledge_base_context: str = "general knowledge base",
        llm_service: Optional[Any] = None,
    ):
        """
        Initialize query router.

        Args:
            config: Orchestration configuration
            knowledge_base_context: Description of knowledge base
            llm_service: Optional LLM for complex classification
        """
        self.config = config
        self.knowledge_base_context = knowledge_base_context
        self.llm_service = llm_service

        # Query patterns for rule-based classification
        self._patterns = {
            QueryType.FACTUAL: [
                "what is", "who is", "when did", "where is",
                "how many", "how much", "define", "what does",
            ],
            QueryType.ANALYTICAL: [
                "why", "explain", "how does", "what causes",
                "analyze", "describe", "elaborate",
            ],
            QueryType.COMPARATIVE: [
                "compare", "difference", "versus", "vs",
                "better", "worse", "similar", "different",
            ],
            QueryType.PROCEDURAL: [
                "how to", "how do i", "steps to", "process",
                "guide", "tutorial", "instructions",
            ],
            QueryType.CONVERSATIONAL: [
                "what about", "and", "also", "more about",
                "tell me more", "continue", "furthermore",
            ],
            QueryType.EXPLORATORY: [
                "overview", "summary", "list", "all",
                "everything about", "general",
            ],
        }

    def set_llm_service(self, llm_service: Any) -> None:
        """Set LLM service for classification."""
        self.llm_service = llm_service

    def classify(self, query: str) -> str:
        """
        Classify query type.

        Args:
            query: User query

        Returns:
            Query type string
        """
        query_type = self._rule_based_classify(query)
        return query_type.value

    def _rule_based_classify(self, query: str) -> QueryType:
        """Classify using rule-based patterns."""
        query_lower = query.lower().strip()

        # Check each pattern
        scores: Dict[QueryType, int] = {qt: 0 for qt in QueryType}

        for query_type, patterns in self._patterns.items():
            for pattern in patterns:
                if pattern in query_lower:
                    scores[query_type] += 1

        # Get highest scoring type
        max_score = max(scores.values())
        if max_score > 0:
            for query_type, score in scores.items():
                if score == max_score:
                    return query_type

        # Default based on query characteristics
        if "?" not in query and len(query.split()) < 5:
            return QueryType.UNCLEAR

        return QueryType.FACTUAL

    def get_pipeline_config(self, query_type: str) -> Dict[str, Any]:
        """
        Get pipeline configuration for query type.

        Args:
            query_type: Query type string

        Returns:
            Pipeline configuration dictionary
        """
        try:
            qt = QueryType(query_type)
        except ValueError:
            qt = QueryType.FACTUAL

        configs = {
            QueryType.FACTUAL: {
                "strategy": "direct",
                "use_query_processing": False,
                "retrieval_method": "dense",
                "retrieval_top_k": 5,
                "use_reranking": True,
                "reranker_top_n": 3,
                "max_iterations": 1,
            },
            QueryType.ANALYTICAL: {
                "strategy": "enhanced",
                "use_query_processing": True,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 10,
                "use_reranking": True,
                "reranker_top_n": 5,
                "use_hyde": False,
                "max_iterations": 2,
            },
            QueryType.COMPARATIVE: {
                "strategy": "multi_query",
                "use_query_processing": True,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 15,
                "use_reranking": True,
                "reranker_top_n": 8,
                "use_decomposition": True,
                "max_iterations": 2,
            },
            QueryType.PROCEDURAL: {
                "strategy": "step_back",
                "use_query_processing": True,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 10,
                "use_reranking": True,
                "reranker_top_n": 5,
                "use_step_back": True,
                "max_iterations": 2,
            },
            QueryType.CONVERSATIONAL: {
                "strategy": "contextual",
                "use_query_processing": True,
                "retrieval_method": "dense",
                "retrieval_top_k": 8,
                "use_reranking": True,
                "reranker_top_n": 4,
                "use_conversation_context": True,
                "max_iterations": 1,
            },
            QueryType.EXPLORATORY: {
                "strategy": "broad",
                "use_query_processing": True,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 20,
                "use_reranking": True,
                "reranker_top_n": 10,
                "max_iterations": 2,
            },
            QueryType.UNCLEAR: {
                "strategy": "clarify",
                "use_query_processing": True,
                "retrieval_method": "dense",
                "retrieval_top_k": 10,
                "use_reranking": True,
                "reranker_top_n": 5,
                "max_iterations": 1,
            },
        }

        return configs.get(qt, configs[QueryType.FACTUAL])

    def should_iterate(self, query_type: QueryType, current_iteration: int) -> bool:
        """Check if another iteration should be performed."""
        config = self.get_pipeline_config(query_type.value)
        max_iterations = min(
            config.get("max_iterations", 1),
            self.config.max_iterations,
        )
        return current_iteration < max_iterations
