"""
Prompt builder for constructing LLM prompts.

Supports template-based prompt construction with variable substitution.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.core.base_interfaces import Document
from src.core.config_loader import PromptConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PromptTemplate:
    """
    Template for prompt construction.

    Supports variable substitution and conditional sections.
    """

    def __init__(
        self,
        template: str,
        input_variables: Optional[List[str]] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize prompt template.

        Args:
            template: Template string with {variable} placeholders
            input_variables: Expected variable names
            name: Optional template name
        """
        self.template = template
        self.input_variables = input_variables or self._extract_variables()
        self.name = name

    def _extract_variables(self) -> List[str]:
        """Extract variable names from template."""
        import re

        pattern = r"\{(\w+)\}"
        return list(set(re.findall(pattern, self.template)))

    def format(self, **kwargs) -> str:
        """
        Format template with provided variables.

        Args:
            **kwargs: Variable values

        Returns:
            Formatted prompt string
        """
        # Check for missing variables
        missing = set(self.input_variables) - set(kwargs.keys())
        if missing:
            logger.warning(f"Missing template variables: {missing}")

        return self.template.format(**kwargs)

    @classmethod
    def from_file(cls, file_path: str) -> "PromptTemplate":
        """Load template from file."""
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {file_path}")

        content = path.read_text()

        if path.suffix in [".yaml", ".yml"]:
            data = yaml.safe_load(content)
            return cls(
                template=data.get("template", ""),
                input_variables=data.get("input_variables"),
                name=data.get("name", path.stem),
            )
        else:
            return cls(template=content, name=path.stem)


class PromptBuilder:
    """
    Builder for constructing RAG prompts.

    Manages templates and builds prompts with context.
    """

    def __init__(self, config: Optional[PromptConfig] = None):
        """
        Initialize prompt builder.

        Args:
            config: Prompt configuration
        """
        self.config = config or PromptConfig()
        self.templates: Dict[str, PromptTemplate] = {}

        self._load_default_templates()

    def _load_default_templates(self) -> None:
        """Load default prompt templates."""
        # QA Template
        self.templates["qa"] = PromptTemplate(
            template="""You are a helpful assistant that answers questions based on the provided context.

Context:
{context}

Question: {question}

Instructions:
- Answer based only on the provided context
- Be accurate and concise
- If the answer is not in the context, say "I don't have enough information to answer this question"
- Cite relevant document numbers when appropriate

Answer:""",
            input_variables=["context", "question"],
            name="qa",
        )

        # Query rewrite template
        self.templates["query_rewrite"] = PromptTemplate(
            template="""Rewrite the following question to be more effective for document retrieval.
Make it more specific and include relevant keywords.

Original question: {question}

Rewritten question:""",
            input_variables=["question"],
            name="query_rewrite",
        )

        # HyDE template
        self.templates["hyde"] = PromptTemplate(
            template="""Write a detailed paragraph that would be an ideal answer to the following question.
Include specific information and facts.

Question: {question}

Ideal answer:""",
            input_variables=["question"],
            name="hyde",
        )

        # Summarization template
        self.templates["summarize"] = PromptTemplate(
            template="""Summarize the following text concisely while preserving key information.

Text:
{text}

Summary:""",
            input_variables=["text"],
            name="summarize",
        )

    def load_template(self, name: str, file_path: str) -> None:
        """Load template from file."""
        template = PromptTemplate.from_file(file_path)
        template.name = name
        self.templates[name] = template
        logger.debug(f"Loaded template '{name}' from {file_path}")

    def get_template(self, name: str) -> PromptTemplate:
        """Get template by name."""
        if name not in self.templates:
            raise KeyError(f"Template '{name}' not found")
        return self.templates[name]

    def build_qa_prompt(
        self,
        question: str,
        documents: List[Document],
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Build QA prompt with context.

        Args:
            question: User question
            documents: Context documents
            system_prompt: Optional custom system prompt

        Returns:
            Formatted prompt
        """
        # Format context
        context = self._format_context(documents)

        # Use custom template if provided
        if system_prompt:
            return f"{system_prompt}\n\nContext:\n{context}\n\nQuestion: {question}\n\nAnswer:"

        template = self.templates.get("qa")
        if template:
            return template.format(context=context, question=question)

        # Fallback
        return f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"

    def _format_context(self, documents: List[Document]) -> str:
        """Format documents as context string."""
        if not documents:
            return "No context available."

        parts = []
        for i, doc in enumerate(documents, 1):
            source = doc.metadata.get("source", "Unknown")
            parts.append(f"[Document {i}] (Source: {source})\n{doc.content}")

        return "\n\n".join(parts)

    def build_rewrite_prompt(self, question: str) -> str:
        """Build query rewrite prompt."""
        template = self.templates.get("query_rewrite")
        if template:
            return template.format(question=question)
        return f"Rewrite this question: {question}"

    def build_hyde_prompt(self, question: str) -> str:
        """Build HyDE prompt."""
        template = self.templates.get("hyde")
        if template:
            return template.format(question=question)
        return f"Write an ideal answer to: {question}"

    def build_custom_prompt(
        self,
        template_name: str,
        **kwargs,
    ) -> str:
        """Build prompt from named template."""
        template = self.get_template(template_name)
        return template.format(**kwargs)
