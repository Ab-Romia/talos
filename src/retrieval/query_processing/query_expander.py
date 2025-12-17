"""
Query expansion for improved recall.

Generates multiple query variations to improve retrieval coverage.
"""

from typing import Any, List, Optional

from src.core.config_loader import QueryProcessorConfig
from src.core.exceptions import QueryProcessingError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class QueryExpander:
    """
    Query expander for generating query variations.

    Improves recall by searching with multiple query formulations.
    """

    def __init__(
        self,
        config: QueryProcessorConfig,
        llm_service: Optional[Any] = None,
    ):
        """
        Initialize query expander.

        Args:
            config: Query processor configuration
            llm_service: LLM service for expansion
        """
        self.config = config
        self.llm_service = llm_service

        self.expansion_prompt = """Generate {num_queries} different versions of the following question.
Each version should search for the same information but use different words or perspectives.
Return only the queries, one per line.

Original Question: {query}

Alternative Queries:"""

        self.step_back_prompt = """Given the following specific question, generate a more general "step-back" question
that would help provide background context for answering the original question.

Original Question: {query}

Step-back Question:"""

        self.decomposition_prompt = """Break down the following complex question into simpler sub-questions
that can be answered independently. Return one sub-question per line.

Complex Question: {query}

Sub-questions:"""

    def set_llm_service(self, llm_service: Any) -> None:
        """Set LLM service."""
        self.llm_service = llm_service

    def expand(
        self,
        query: str,
        num_queries: int = 3,
    ) -> List[str]:
        """
        Generate query expansions.

        Args:
            query: Original query
            num_queries: Number of variations to generate

        Returns:
            List of query variations
        """
        if not self.config.expansion or self.llm_service is None:
            return [query]

        try:
            prompt = self.expansion_prompt.format(
                query=query,
                num_queries=num_queries,
            )

            result = self.llm_service.generate(
                query=prompt,
                context=[],
            )

            # Parse response
            lines = result.answer.strip().split("\n")
            expansions = [
                line.strip().lstrip("0123456789.-) ")
                for line in lines
                if line.strip() and len(line.strip()) > 5
            ]

            # Include original query
            all_queries = [query] + expansions[:num_queries]

            logger.debug(f"Generated {len(expansions)} query expansions")
            return all_queries

        except Exception as e:
            logger.warning(f"Query expansion failed: {e}")
            return [query]

    def generate_step_back(self, query: str) -> Optional[str]:
        """
        Generate step-back query for broader context.

        Args:
            query: Original specific query

        Returns:
            More general step-back query
        """
        if not self.config.step_back or self.llm_service is None:
            return None

        try:
            prompt = self.step_back_prompt.format(query=query)

            result = self.llm_service.generate(
                query=prompt,
                context=[],
            )

            step_back = result.answer.strip()

            if step_back and len(step_back) > 10:
                logger.debug(f"Generated step-back query: {step_back}")
                return step_back

            return None

        except Exception as e:
            logger.warning(f"Step-back generation failed: {e}")
            return None

    def decompose(self, query: str) -> List[str]:
        """
        Decompose complex query into sub-queries.

        Args:
            query: Complex query

        Returns:
            List of simpler sub-queries
        """
        if not self.config.decomposition or self.llm_service is None:
            return [query]

        try:
            prompt = self.decomposition_prompt.format(query=query)

            result = self.llm_service.generate(
                query=prompt,
                context=[],
            )

            # Parse sub-queries
            lines = result.answer.strip().split("\n")
            sub_queries = [
                line.strip().lstrip("0123456789.-) ")
                for line in lines
                if line.strip() and len(line.strip()) > 5
            ]

            if sub_queries:
                logger.debug(f"Decomposed into {len(sub_queries)} sub-queries")
                return sub_queries

            return [query]

        except Exception as e:
            logger.warning(f"Query decomposition failed: {e}")
            return [query]
