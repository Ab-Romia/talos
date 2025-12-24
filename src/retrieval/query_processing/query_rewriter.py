"""
Query rewriting for improved retrieval.

Uses LLM to transform queries into more effective search queries.
"""

from typing import Any, Dict, List, Optional

from src.core.base_interfaces import BaseQueryProcessor
from src.core.config_loader import QueryProcessorConfig
from src.core.exceptions import QueryProcessingError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class QueryRewriter(BaseQueryProcessor):
    """
    LLM-based query rewriter for improved retrieval.

    Transforms user queries into more effective search queries.
    """

    def __init__(
        self,
        config: QueryProcessorConfig,
        llm_service: Optional[Any] = None,
    ):
        """
        Initialize query rewriter.

        Args:
            config: Query processor configuration
            llm_service: LLM service for query rewriting
        """
        self.config = config
        self.llm_service = llm_service

        self.rewrite_prompt = """You are an expert at converting user questions into optimized search queries.
Your task is to rewrite the given question to improve document retrieval.

Guidelines:
- Make the query more specific and searchable
- Expand abbreviations if present
- Add relevant synonyms or related terms
- Remove filler words and conversational elements
- Keep the core intent of the original question

Original Question: {query}

Rewritten Query:"""

    def set_llm_service(self, llm_service: Any) -> None:
        """Set LLM service."""
        self.llm_service = llm_service

    def process(
        self,
        query: str,
        conversation_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process query with all enabled transformations.

        Args:
            query: Original query
            conversation_context: Optional conversation context

        Returns:
            Processing results including transformed queries
        """
        result = {
            "original_query": query,
            "processed_query": query,
            "transformations_applied": [],
            "expanded_queries": [],
            "hypothetical_doc": None,
            "step_back_query": None,
            "sub_queries": [],
        }

        if not self.config.enabled:
            return result

        # Apply rewriting if enabled
        if self.config.rewriting:
            try:
                rewritten = self.rewrite(query)
                if rewritten and rewritten != query:
                    result["processed_query"] = rewritten
                    result["transformations_applied"].append("rewriting")
            except Exception as e:
                logger.warning(f"Query rewriting failed: {e}")

        return result

    def rewrite(self, query: str) -> str:
        """
        Rewrite query for better retrieval.

        Args:
            query: Original query

        Returns:
            Rewritten query
        """
        if not self.config.rewriting or self.llm_service is None:
            return query

        try:
            prompt = self.rewrite_prompt.format(query=query)

            # Use LLM to rewrite
            from src.core.base_interfaces import Document
            result = self.llm_service.generate(
                query=prompt,
                context=[],
            )

            rewritten = result.answer.strip()

            # Validate rewritten query
            if rewritten and len(rewritten) > 5:
                logger.debug(f"Query rewritten: '{query}' -> '{rewritten}'")
                return rewritten

            return query

        except Exception as e:
            raise QueryProcessingError(
                f"Query rewriting failed: {e}",
                query=query,
                processing_step="rewriting",
                cause=e,
            )

    def expand(self, query: str) -> List[str]:
        """Generate query expansions."""
        # Delegate to QueryExpander if needed
        return [query]


class HyDEQueryProcessor(QueryRewriter):
    """
    HyDE (Hypothetical Document Embedding) query processor.

    Generates a hypothetical answer to use for retrieval.
    Also supports step-back prompting and query decomposition.
    """

    def __init__(
        self,
        config: QueryProcessorConfig,
        llm_service: Optional[Any] = None,
    ):
        super().__init__(config, llm_service)

        self.hyde_prompt = """Given the following question, write a detailed paragraph that would be the ideal answer.
The paragraph should contain specific information that would help answer the question.

Question: {query}

Ideal Answer Paragraph:"""

        self.step_back_prompt = """Given the following specific question, generate a more general "step-back" question
that would help provide background context for answering the original question.

Original Question: {query}

Step-back Question:"""

        self.decomposition_prompt = """Break down the following complex question into simpler sub-questions
that can be answered independently. Return one sub-question per line.

Complex Question: {query}

Sub-questions:"""

    def process(
        self,
        query: str,
        conversation_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process query with all enabled transformations.

        Supports:
        - Query rewriting (from parent)
        - HyDE (Hypothetical Document Embedding)
        - Step-back prompting
        - Query decomposition
        """
        result = super().process(query, conversation_context)

        # HyDE: Generate hypothetical document
        if self.config.hyde and self.llm_service:
            try:
                hypothetical = self._generate_hypothetical(query)
                if hypothetical:
                    result["hypothetical_doc"] = hypothetical
                    result["transformations_applied"].append("hyde")
            except Exception as e:
                logger.warning(f"HyDE generation failed: {e}")

        # Step-back: Generate broader context query
        if self.config.step_back and self.llm_service:
            try:
                step_back = self._generate_step_back(query)
                if step_back:
                    result["step_back_query"] = step_back
                    result["transformations_applied"].append("step_back")
            except Exception as e:
                logger.warning(f"Step-back generation failed: {e}")

        # Decomposition: Break into sub-queries
        if self.config.decomposition and self.llm_service:
            try:
                sub_queries = self._decompose_query(query)
                if sub_queries and len(sub_queries) > 1:
                    result["sub_queries"] = sub_queries
                    result["transformations_applied"].append("decomposition")
            except Exception as e:
                logger.warning(f"Query decomposition failed: {e}")

        return result

    def _generate_hypothetical(self, query: str) -> Optional[str]:
        """Generate hypothetical document for query."""
        try:
            prompt = self.hyde_prompt.format(query=query)

            result = self.llm_service.generate(
                query=prompt,
                context=[],
            )

            hypothetical = result.answer.strip()

            if hypothetical and len(hypothetical) > 20:
                logger.debug(f"Generated HyDE document: {hypothetical[:100]}...")
                return hypothetical

            return None

        except Exception as e:
            logger.warning(f"HyDE generation failed: {e}")
            return None

    def _generate_step_back(self, query: str) -> Optional[str]:
        """Generate step-back query for broader context."""
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

    def _decompose_query(self, query: str) -> List[str]:
        """Decompose complex query into sub-queries."""
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

            return []

        except Exception as e:
            logger.warning(f"Query decomposition failed: {e}")
            return []
