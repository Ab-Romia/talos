from openai import OpenAI
from typing import List, Optional, Dict
import os


class LLMGenerator:
    def __init__(self, model: str = "gpt-4o-mini", knowledge_base_context: str = None):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.kb_context = knowledge_base_context or "a general knowledge base"

    def generate(
        self,
        query: str,
        context_chunks: List[str],
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        Generate an answer using retrieved context and optional conversation history.

        Args:
            query: User's question
            context_chunks: Retrieved document chunks
            conversation_history: Previous conversation turns

        Returns:
            Generated answer
        """
        context = "\n".join(context_chunks)

        # Build messages with conversation history if available
        messages = [
            {
                "role": "system",
                "content": f"""You are a helpful AI assistant for a team workspace. You have access to {self.kb_context}.

Guidelines:
- Use the retrieved context to answer questions about the team, project, plans, meetings, and tasks
- Consider the conversation history for context and continuity
- If the question references previous conversation, use that context
- Be specific and cite relevant information from the workspace (team members, deadlines, tasks, etc.)
- If the context doesn't contain enough information, say so clearly
- Keep answers concise and relevant to the team's work
- When discussing tasks or deadlines, be precise about dates and assignments"""
            }
        ]

        # Add conversation history if available (last 3 turns)
        if conversation_history:
            for turn in conversation_history[-3:]:
                messages.append({
                    "role": "user",
                    "content": turn["question"]
                })
                messages.append({
                    "role": "assistant",
                    "content": turn["answer"]
                })

        # Add current question with context
        user_content = f"""Context:
{context}

Question: {query}"""

        messages.append({
            "role": "user",
            "content": user_content
        })

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )

        return response.choices[0].message.content
