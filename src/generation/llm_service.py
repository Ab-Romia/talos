"""
LLM service for response generation.

Supports multiple providers including OpenAI and Anthropic.
"""

import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional

from src.core.base_interfaces import BaseGenerator, Document, GenerationResult
from src.core.config_loader import GeneratorConfig
from src.core.exceptions import GenerationError, GenerationRateLimitError
from src.utils.logger import get_logger
from src.utils.async_helpers import sync_retry

logger = get_logger(__name__)


class LLMService(BaseGenerator, ABC):
    """Abstract base class for LLM services."""

    def __init__(self, config: GeneratorConfig):
        self.config = config

    @abstractmethod
    def _call(
        self,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> Dict[str, Any]:
        """Make API call to LLM."""
        pass


class OpenAILLM(LLMService):
    """OpenAI LLM implementation."""

    def __init__(self, config: Optional[GeneratorConfig] = None):
        config = config or GeneratorConfig(provider="openai")
        super().__init__(config)

        self._client = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize OpenAI client."""
        try:
            from openai import OpenAI

            api_key = os.getenv(self.config.api_key_env)
            if not api_key:
                raise GenerationError(
                    f"API key not found: {self.config.api_key_env}",
                    model=self.config.model_name,
                )

            client_kwargs = {"api_key": api_key}
            if self.config.base_url:
                client_kwargs["base_url"] = self.config.base_url

            self._client = OpenAI(**client_kwargs)

        except ImportError:
            raise ImportError(
                "openai is required for OpenAI LLM. "
                "Install with: pip install openai"
            )

    @sync_retry(max_retries=3, base_delay=1.0)
    def _call(
        self,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> Dict[str, Any]:
        """Make OpenAI API call."""
        try:
            response = self._client.chat.completions.create(
                model=kwargs.get("model", self.config.model_name),
                messages=messages,
                temperature=kwargs.get("temperature", self.config.temperature),
                max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
                top_p=kwargs.get("top_p", self.config.top_p),
                frequency_penalty=kwargs.get("frequency_penalty", self.config.frequency_penalty),
                presence_penalty=kwargs.get("presence_penalty", self.config.presence_penalty),
            )

            return {
                "content": response.choices[0].message.content,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "model": response.model,
            }

        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise GenerationRateLimitError(cause=e)
            raise GenerationError(
                f"OpenAI API call failed: {e}",
                model=self.config.model_name,
                cause=e,
            )

    def generate(
        self,
        query: str,
        context: List[Document],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> GenerationResult:
        """Generate response using OpenAI."""
        start_time = time.perf_counter()

        # Build messages
        messages = self._build_messages(query, context, conversation_history)

        # Make API call
        result = self._call(messages)

        latency_ms = (time.perf_counter() - start_time) * 1000

        logger.log_generation(
            prompt_tokens=result["prompt_tokens"],
            completion_tokens=result["completion_tokens"],
            latency_ms=latency_ms,
            model=result["model"],
        )

        return GenerationResult(
            answer=result["content"],
            sources=context,
            prompt_tokens=result["prompt_tokens"],
            completion_tokens=result["completion_tokens"],
            latency_ms=latency_ms,
            metadata={"model": result["model"]},
        )

    def generate_stream(
        self,
        query: str,
        context: List[Document],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Generator[str, None, None]:
        """Generate streaming response."""
        messages = self._build_messages(query, context, conversation_history)

        try:
            stream = self._client.chat.completions.create(
                model=self.config.model_name,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                stream=True,
            )

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            raise GenerationError(
                f"Streaming failed: {e}",
                model=self.config.model_name,
                cause=e,
            )

    def _build_messages(
        self,
        query: str,
        context: List[Document],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """Build message list for API call."""
        messages = []

        # System message
        system_prompt = self._build_system_prompt(context)
        messages.append({"role": "system", "content": system_prompt})

        # Conversation history
        if conversation_history:
            for turn in conversation_history[-3:]:  # Last 3 turns
                messages.append({"role": "user", "content": turn.get("question", "")})
                messages.append({"role": "assistant", "content": turn.get("answer", "")})

        # Current query
        messages.append({"role": "user", "content": query})

        return messages

    def _build_system_prompt(self, context: List[Document]) -> str:
        """Build system prompt with context."""
        context_text = "\n\n".join([
            f"[Document {i+1}]\n{doc.content}"
            for i, doc in enumerate(context)
        ])

        return f"""You are a helpful assistant that answers questions based on the provided context.
Use the following context to answer the user's question. If the answer cannot be found in the context,
say so clearly. Always be accurate and cite relevant parts of the context.

Context:
{context_text}

Instructions:
- Answer based on the context provided
- Be concise but comprehensive
- If unsure, acknowledge uncertainty
- Cite document numbers when referencing specific information"""


class AnthropicLLM(LLMService):
    """Anthropic Claude LLM implementation."""

    def __init__(self, config: Optional[GeneratorConfig] = None):
        config = config or GeneratorConfig(
            provider="anthropic",
            model_name="claude-3-sonnet-20240229",
            api_key_env="ANTHROPIC_API_KEY",
        )
        super().__init__(config)

        self._client = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize Anthropic client."""
        try:
            import anthropic

            api_key = os.getenv(self.config.api_key_env)
            if not api_key:
                raise GenerationError(
                    f"API key not found: {self.config.api_key_env}",
                    model=self.config.model_name,
                )

            self._client = anthropic.Anthropic(api_key=api_key)

        except ImportError:
            raise ImportError(
                "anthropic is required for Anthropic LLM. "
                "Install with: pip install anthropic"
            )

    @sync_retry(max_retries=3, base_delay=1.0)
    def _call(
        self,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> Dict[str, Any]:
        """Make Anthropic API call."""
        try:
            # Extract system message
            system = ""
            chat_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system = msg["content"]
                else:
                    chat_messages.append(msg)

            response = self._client.messages.create(
                model=kwargs.get("model", self.config.model_name),
                max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
                system=system,
                messages=chat_messages,
            )

            return {
                "content": response.content[0].text,
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "model": response.model,
            }

        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise GenerationRateLimitError(cause=e)
            raise GenerationError(
                f"Anthropic API call failed: {e}",
                model=self.config.model_name,
                cause=e,
            )

    def generate(
        self,
        query: str,
        context: List[Document],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> GenerationResult:
        """Generate response using Anthropic."""
        start_time = time.perf_counter()

        messages = self._build_messages(query, context, conversation_history)
        result = self._call(messages)

        latency_ms = (time.perf_counter() - start_time) * 1000

        logger.log_generation(
            prompt_tokens=result["prompt_tokens"],
            completion_tokens=result["completion_tokens"],
            latency_ms=latency_ms,
            model=result["model"],
        )

        return GenerationResult(
            answer=result["content"],
            sources=context,
            prompt_tokens=result["prompt_tokens"],
            completion_tokens=result["completion_tokens"],
            latency_ms=latency_ms,
            metadata={"model": result["model"]},
        )

    def generate_stream(
        self,
        query: str,
        context: List[Document],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Generator[str, None, None]:
        """Generate streaming response."""
        messages = self._build_messages(query, context, conversation_history)

        # Extract system
        system = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                chat_messages.append(msg)

        try:
            with self._client.messages.stream(
                model=self.config.model_name,
                max_tokens=self.config.max_tokens,
                system=system,
                messages=chat_messages,
            ) as stream:
                for text in stream.text_stream:
                    yield text

        except Exception as e:
            raise GenerationError(
                f"Streaming failed: {e}",
                model=self.config.model_name,
                cause=e,
            )

    def _build_messages(
        self,
        query: str,
        context: List[Document],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """Build message list."""
        messages = []

        # System
        context_text = "\n\n".join([
            f"[Document {i+1}]\n{doc.content}"
            for i, doc in enumerate(context)
        ])

        system = f"""You are a helpful assistant. Answer questions based on the provided context.

Context:
{context_text}

Be accurate, concise, and cite sources when relevant."""

        messages.append({"role": "system", "content": system})

        # History
        if conversation_history:
            for turn in conversation_history[-3:]:
                messages.append({"role": "user", "content": turn.get("question", "")})
                messages.append({"role": "assistant", "content": turn.get("answer", "")})

        messages.append({"role": "user", "content": query})

        return messages


def create_llm_service(config: GeneratorConfig) -> LLMService:
    """
    Factory function to create LLM service.

    Args:
        config: Generator configuration

    Returns:
        Appropriate LLM service instance
    """
    providers = {
        "openai": OpenAILLM,
        "anthropic": AnthropicLLM,
        "azure_openai": OpenAILLM,  # Uses same client with different base_url
    }

    provider_class = providers.get(config.provider)
    if provider_class is None:
        raise GenerationError(
            f"Unknown LLM provider: {config.provider}",
            details={"supported_providers": list(providers.keys())},
        )

    return provider_class(config)
