from openai import OpenAI
from enum import Enum
from typing import Dict, List, Optional
import os


class QueryType(Enum):
    """Query types with corresponding processing strategies."""
    FACTUAL = "factual"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    PROCEDURAL = "procedural"
    CONVERSATIONAL = "conversational"
    EXPLORATORY = "exploratory"
    UNCLEAR = "unclear"


class RetrievalStrategy(Enum):
    """Retrieval strategies based on query requirements."""
    SIMPLE = "simple"
    ENHANCED = "enhanced"
    MULTI_HOP = "multi_hop"
    ITERATIVE = "iterative"


class QueryRouter:
    """
    Advanced query router implementing adaptive orchestration patterns
    from the Modular RAG framework.

    Supports:
    - Query classification into 7 distinct types
    - Strategy selection based on query complexity
    - Adaptive pipeline configuration
    - Iterative refinement for complex queries
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        knowledge_base_context: str = None,
        max_iterations: int = 3
    ):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.kb_context = knowledge_base_context or "general information"
        self.max_iterations = max_iterations

    def classify_query(self, query: str) -> QueryType:
        """Classify query into one of the predefined types."""
        messages = [
            {
                "role": "system",
                "content": f"""Classify the query for a knowledge base about {self.kb_context}.

Categories:
1. FACTUAL - Direct questions asking for ONE specific fact (e.g., "Who is the team lead?", "What is the deadline?")
2. ANALYTICAL - Questions requiring analysis or explanation of concepts
3. COMPARATIVE - Questions comparing multiple items or concepts
4. PROCEDURAL - Questions about processes, steps, or how things work
5. CONVERSATIONAL - Follow-up questions or context-dependent queries (e.g., "tell me more", "what about that?")
6. EXPLORATORY - Questions seeking MULTIPLE pieces of information or broad overview (e.g., "tell me about the team", "what are all the facts", "list all members")
7. UNCLEAR - Vague, ambiguous, or poorly formed questions

Important: If asking for multiple items, lists, or broad information, classify as EXPLORATORY not FACTUAL.

Respond with ONLY one word from: FACTUAL, ANALYTICAL, COMPARATIVE, PROCEDURAL, CONVERSATIONAL, EXPLORATORY, UNCLEAR"""
            },
            {
                "role": "user",
                "content": f"Query: {query}"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            max_tokens=10
        )

        classification = response.choices[0].message.content.strip().upper()

        try:
            return QueryType[classification]
        except KeyError:
            return QueryType.FACTUAL

    def get_retrieval_strategy(self, query_type: QueryType) -> RetrievalStrategy:
        """Determine the best retrieval strategy for the query type."""
        strategy_map = {
            QueryType.FACTUAL: RetrievalStrategy.SIMPLE,
            QueryType.ANALYTICAL: RetrievalStrategy.ENHANCED,
            QueryType.COMPARATIVE: RetrievalStrategy.MULTI_HOP,
            QueryType.PROCEDURAL: RetrievalStrategy.ENHANCED,
            QueryType.CONVERSATIONAL: RetrievalStrategy.SIMPLE,
            QueryType.EXPLORATORY: RetrievalStrategy.ITERATIVE,
            QueryType.UNCLEAR: RetrievalStrategy.ENHANCED
        }
        return strategy_map.get(query_type, RetrievalStrategy.SIMPLE)

    def get_pipeline_config(self, query_type: QueryType) -> Dict:
        """Get comprehensive pipeline configuration for a query type."""
        strategy = self.get_retrieval_strategy(query_type)

        configs = {
            QueryType.FACTUAL: {
                "use_query_processing": False,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 6,
                "use_reranking": True,
                "reranker_top_n": 4
            },
            QueryType.ANALYTICAL: {
                "use_query_processing": False,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 8,
                "use_reranking": True,
                "reranker_top_n": 5
            },
            QueryType.COMPARATIVE: {
                "use_query_processing": False,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 10,
                "use_reranking": True,
                "reranker_top_n": 6
            },
            QueryType.PROCEDURAL: {
                "use_query_processing": False,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 8,
                "use_reranking": True,
                "reranker_top_n": 5
            },
            QueryType.CONVERSATIONAL: {
                "use_query_processing": False,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 6,
                "use_reranking": True,
                "reranker_top_n": 4
            },
            QueryType.EXPLORATORY: {
                "use_query_processing": False,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 10,
                "use_reranking": True,
                "reranker_top_n": 6
            },
            QueryType.UNCLEAR: {
                "use_query_processing": True,
                "retrieval_method": "hybrid",
                "retrieval_top_k": 8,
                "use_reranking": True,
                "reranker_top_n": 5
            }
        }

        return configs.get(query_type, configs[QueryType.FACTUAL])

    def should_iterate(
        self,
        query_type: QueryType,
        current_iteration: int,
        answer_quality: Optional[float] = None
    ) -> bool:
        """
        Determine if another retrieval iteration should be performed.
        Used for iterative refinement of complex queries.
        """
        config = self.get_pipeline_config(query_type)
        max_iter = config.get("max_iterations", 1)

        if current_iteration >= max_iter:
            return False

        if answer_quality is not None and answer_quality > 0.8:
            return False

        return True

    def get_transformations(self, query_type: QueryType) -> List[str]:
        """Get the list of query transformations to apply for a query type."""
        config = self.get_pipeline_config(query_type)
        transformations = []

        if config.get("use_query_processing"):
            transformations.extend(["rewrite", "expand"])

        if config.get("use_hyde"):
            transformations.append("hyde")

        if config.get("use_step_back"):
            transformations.append("step_back")

        if config.get("use_decomposition"):
            transformations.append("decompose")

        return transformations

    def assess_answer_completeness(
        self,
        query: str,
        answer: str,
        context_chunks: List[str]
    ) -> float:
        """
        Assess whether the answer adequately addresses the query.
        Returns a score between 0 and 1.
        """
        messages = [
            {
                "role": "system",
                "content": """Assess how completely the answer addresses the question based on the provided context.

Score from 0.0 to 1.0:
- 0.0-0.3: Answer is incomplete or off-topic
- 0.4-0.6: Answer is partial, missing key information
- 0.7-0.8: Answer is good but could be more comprehensive
- 0.9-1.0: Answer fully addresses the question

Return ONLY a decimal number."""
            },
            {
                "role": "user",
                "content": f"Question: {query}\n\nAnswer: {answer}\n\nContext available: {len(context_chunks)} chunks\n\nCompleteness score:"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            max_tokens=10
        )

        try:
            score = float(response.choices[0].message.content.strip())
            return max(0.0, min(1.0, score))
        except:
            return 0.5

    def refine_query_for_iteration(
        self,
        original_query: str,
        previous_answer: str,
        iteration: int
    ) -> str:
        """
        Refine the query for the next iteration based on gaps in the previous answer.
        """
        messages = [
            {
                "role": "system",
                "content": """Based on the original question and the previous partial answer,
generate a refined follow-up question that seeks the missing information.
Return ONLY the refined question."""
            },
            {
                "role": "user",
                "content": f"Original question: {original_query}\n\nPartial answer: {previous_answer}\n\nRefined question:"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=100
        )

        return response.choices[0].message.content.strip()
