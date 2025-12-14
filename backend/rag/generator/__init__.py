"""
Generator Module

Generates answers from retrieved context using LLMs:
- LLM API integration (OpenAI, Anthropic, local models)
- Prompt template management
- Context optimization
"""

from .llm_generator import LLMGenerator

__all__ = ['LLMGenerator']