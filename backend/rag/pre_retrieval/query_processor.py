from openai import OpenAI
from typing import List, Optional, Dict
from enum import Enum
import os


class QueryTransformationType(Enum):
    REWRITE = "rewrite"
    EXPAND = "expand"
    HYDE = "hyde"
    STEP_BACK = "step_back"
    DECOMPOSE = "decompose"


class QueryProcessor:
    """
    Advanced query processor implementing multiple pre-retrieval strategies
    based on the Modular RAG framework.

    Strategies:
    - Query Rewriting: Clarify and fix ambiguous queries
    - Query Expansion: Add synonyms and related terms
    - HyDE: Generate hypothetical documents for better retrieval
    - Step-Back Prompting: Generate broader context queries
    - Sub-Query Decomposition: Break complex queries into simpler parts
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        enable_expansion: bool = True,
        enable_rewriting: bool = True,
        enable_hyde: bool = False,
        enable_step_back: bool = False,
        enable_decomposition: bool = False
    ):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.enable_expansion = enable_expansion
        self.enable_rewriting = enable_rewriting
        self.enable_hyde = enable_hyde
        self.enable_step_back = enable_step_back
        self.enable_decomposition = enable_decomposition

    def process(
        self,
        query: str,
        conversation_context: Optional[str] = None,
        strategies: Optional[List[QueryTransformationType]] = None
    ) -> Dict:
        """
        Process a query using configured or specified strategies.

        Returns a dictionary with processed query and any additional outputs
        (sub-queries, hypothetical documents, etc.)
        """
        result = {
            "original_query": query,
            "processed_query": query,
            "sub_queries": [],
            "hypothetical_doc": None,
            "step_back_query": None,
            "transformations_applied": []
        }

        processed = query

        if conversation_context:
            processed = self._resolve_conversational_query(processed, conversation_context)
            if processed != query:
                result["transformations_applied"].append("conversational_resolution")

        if strategies:
            if QueryTransformationType.REWRITE in strategies:
                processed = self._rewrite_query(processed)
                result["transformations_applied"].append("rewrite")

            if QueryTransformationType.EXPAND in strategies:
                processed = self._expand_query(processed)
                result["transformations_applied"].append("expand")

            if QueryTransformationType.HYDE in strategies:
                result["hypothetical_doc"] = self._generate_hypothetical_document(processed)
                result["transformations_applied"].append("hyde")

            if QueryTransformationType.STEP_BACK in strategies:
                result["step_back_query"] = self._generate_step_back_query(processed)
                result["transformations_applied"].append("step_back")

            if QueryTransformationType.DECOMPOSE in strategies:
                result["sub_queries"] = self._decompose_query(processed)
                result["transformations_applied"].append("decompose")
        else:
            if self.enable_rewriting:
                processed = self._rewrite_query(processed)
                result["transformations_applied"].append("rewrite")

            if self.enable_hyde:
                result["hypothetical_doc"] = self._generate_hypothetical_document(processed)
                result["transformations_applied"].append("hyde")

            if self.enable_step_back:
                result["step_back_query"] = self._generate_step_back_query(processed)
                result["transformations_applied"].append("step_back")

            if self.enable_decomposition:
                result["sub_queries"] = self._decompose_query(processed)
                result["transformations_applied"].append("decompose")

        result["processed_query"] = processed
        return result

    def _resolve_conversational_query(self, query: str, conversation_context: str) -> str:
        """Resolve pronouns and references using conversation context."""
        messages = [
            {
                "role": "system",
                "content": """Convert follow-up questions into standalone queries by replacing pronouns and references with specific entities from the conversation context.

Rules:
- Replace "it", "that", "this", "they" with specific entities
- Keep the same intent and meaning
- Make the query understandable without context
- If already standalone, return as-is
- Return ONLY the resolved query"""
            },
            {
                "role": "user",
                "content": f"{conversation_context}\n\nNew question: {query}\n\nStandalone query:"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            max_tokens=150
        )

        return response.choices[0].message.content.strip()

    def _rewrite_query(self, query: str) -> str:
        """Rewrite query for clarity and better retrieval."""
        messages = [
            {
                "role": "system",
                "content": """Minimally rewrite the query to fix errors while preserving meaning.
- Fix typos and spelling errors
- Fix grammar only if broken
- Keep the same wording and structure
- Do NOT rephrase or make it more formal
- Return ONLY the fixed query"""
            },
            {
                "role": "user",
                "content": f"Fix: {query}"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            max_tokens=100
        )

        return response.choices[0].message.content.strip()

    def _expand_query(self, query: str) -> str:
        """Expand query with synonyms and related terms."""
        messages = [
            {
                "role": "system",
                "content": """Expand the query by adding a few related terms while KEEPING all original words.
- Keep the original query words intact
- Add 2-3 related terms at the end
- Do NOT replace original words with synonyms
- Return ONLY the expanded query"""
            },
            {
                "role": "user",
                "content": f"Expand: {query}"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=150
        )

        return response.choices[0].message.content.strip()

    def _generate_hypothetical_document(self, query: str) -> str:
        """
        Generate a hypothetical document that would answer the query (HyDE).
        This document is used for retrieval instead of the query itself.
        """
        messages = [
            {
                "role": "system",
                "content": """Generate a hypothetical document passage that would perfectly answer the given question.
Write as if you're creating a knowledge base entry that contains the answer.
The document should be factual in tone and contain relevant details.
Keep it to 2-3 sentences.
Return ONLY the hypothetical document text."""
            },
            {
                "role": "user",
                "content": f"Question: {query}\n\nHypothetical document:"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.5,
            max_tokens=200
        )

        return response.choices[0].message.content.strip()

    def _generate_step_back_query(self, query: str) -> str:
        """
        Generate a broader, more general step-back query.
        Used for retrieving background context.
        """
        messages = [
            {
                "role": "system",
                "content": """Generate a step-back question that asks about a broader concept or background information related to the specific question.

Example:
- Specific: "What tasks did Sarah complete in Sprint 3?"
- Step-back: "What is the overall sprint planning and task assignment process?"

Return ONLY the step-back question."""
            },
            {
                "role": "user",
                "content": f"Specific question: {query}\n\nStep-back question:"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=100
        )

        return response.choices[0].message.content.strip()

    def _decompose_query(self, query: str, num_sub_queries: int = 3) -> List[str]:
        """
        Decompose a complex query into simpler sub-queries.
        Each sub-query targets a specific aspect of the original question.
        """
        messages = [
            {
                "role": "system",
                "content": f"""Decompose the complex question into {num_sub_queries} simpler sub-questions.
Each sub-question should:
- Target a specific aspect of the original question
- Be answerable independently
- Together cover all aspects of the original question

Return ONLY the sub-questions, one per line, no numbering."""
            },
            {
                "role": "user",
                "content": f"Decompose: {query}"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.4,
            max_tokens=300
        )

        sub_queries = response.choices[0].message.content.strip().split('\n')
        return [q.strip() for q in sub_queries if q.strip()][:num_sub_queries]

    def generate_multi_queries(self, query: str, num_queries: int = 3) -> List[str]:
        """Generate multiple query variations for better retrieval coverage."""
        messages = [
            {
                "role": "system",
                "content": f"""Generate {num_queries} different variations of the query.
Each variation should:
- Ask the same thing with different wording
- Use different synonyms and phrasings
- Be concise

Return ONLY the variations, one per line, no numbering."""
            },
            {
                "role": "user",
                "content": f"Generate variations: {query}"
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=200
        )

        variations = response.choices[0].message.content.strip().split('\n')
        return [v.strip() for v in variations if v.strip()][:num_queries]
