"""
Response parser for LLM outputs.

Validates and structures LLM responses.
"""

import re
from typing import Any, Dict, List, Optional

from src.core.base_interfaces import Document
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ResponseParser:
    """
    Parser for LLM responses.

    Extracts structured information and validates outputs.
    """

    def __init__(
        self,
        max_length: Optional[int] = None,
        strip_thinking: bool = True,
    ):
        """
        Initialize response parser.

        Args:
            max_length: Maximum response length
            strip_thinking: Whether to strip thinking/reasoning sections
        """
        self.max_length = max_length
        self.strip_thinking = strip_thinking

    def parse(self, response: str) -> Dict[str, Any]:
        """
        Parse LLM response.

        Args:
            response: Raw LLM response

        Returns:
            Parsed response with extracted information
        """
        # Clean response
        cleaned = self._clean_response(response)

        # Extract citations
        citations = self._extract_citations(cleaned)

        # Extract confidence
        confidence = self._extract_confidence(cleaned)

        return {
            "answer": cleaned,
            "citations": citations,
            "confidence": confidence,
            "word_count": len(cleaned.split()),
            "char_count": len(cleaned),
        }

    def _clean_response(self, response: str) -> str:
        """Clean and normalize response."""
        if not response:
            return ""

        cleaned = response.strip()

        # Remove thinking sections if enabled
        if self.strip_thinking:
            # Remove <thinking>...</thinking> blocks
            cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL)
            # Remove [THINKING]...[/THINKING] blocks
            cleaned = re.sub(r"\[THINKING\].*?\[/THINKING\]", "", cleaned, flags=re.DOTALL)

        # Truncate if too long
        if self.max_length and len(cleaned) > self.max_length:
            # Try to truncate at sentence boundary
            truncated = cleaned[:self.max_length]
            last_period = truncated.rfind(".")
            if last_period > self.max_length * 0.8:
                cleaned = truncated[:last_period + 1]
            else:
                cleaned = truncated + "..."

        return cleaned.strip()

    def _extract_citations(self, response: str) -> List[Dict[str, Any]]:
        """Extract citation references from response."""
        citations = []

        # Pattern: [Document N] or [N] or (Document N)
        patterns = [
            r"\[Document\s+(\d+)\]",
            r"\[(\d+)\]",
            r"\(Document\s+(\d+)\)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, response, re.IGNORECASE)
            for match in matches:
                doc_num = int(match)
                if doc_num not in [c["document_index"] for c in citations]:
                    citations.append({"document_index": doc_num})

        return citations

    def _extract_confidence(self, response: str) -> Optional[float]:
        """Extract confidence indicators from response."""
        # Look for uncertainty phrases
        uncertain_phrases = [
            "i'm not sure",
            "i don't know",
            "uncertain",
            "might be",
            "possibly",
            "i think",
            "may be",
            "could be",
            "not certain",
            "no information",
        ]

        confident_phrases = [
            "definitely",
            "certainly",
            "clearly",
            "based on the context",
            "according to",
            "the document states",
        ]

        response_lower = response.lower()

        uncertain_count = sum(1 for phrase in uncertain_phrases if phrase in response_lower)
        confident_count = sum(1 for phrase in confident_phrases if phrase in response_lower)

        # Simple heuristic
        if uncertain_count > confident_count:
            return 0.5
        elif confident_count > uncertain_count:
            return 0.9
        else:
            return 0.7  # Default moderate confidence

    def validate(
        self,
        response: str,
        min_length: int = 10,
        required_citations: bool = False,
    ) -> tuple[bool, List[str]]:
        """
        Validate response.

        Args:
            response: Response to validate
            min_length: Minimum character length
            required_citations: Whether citations are required

        Returns:
            Tuple of (is_valid, list of issues)
        """
        issues = []

        if not response or not response.strip():
            issues.append("Response is empty")
            return False, issues

        if len(response.strip()) < min_length:
            issues.append(f"Response too short (min {min_length} chars)")

        if required_citations:
            citations = self._extract_citations(response)
            if not citations:
                issues.append("No citations found in response")

        return len(issues) == 0, issues
