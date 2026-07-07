from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    PromptTemplate,
)

# TODO:

QUERY_REWRITE_PROMPT = PromptTemplate(
    input_variables=["query"],
    template="""Rewrite the following question to be more specific and searchable for document retrieval.
Make it clearer and add relevant keywords, but keep the core intent.

Original Question: {query}

Rewritten Query:""",
)

RAG_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a helpful AI assistant. Use the following context to answer the question.

The conversation history in this thread IS available to you — never say you
cannot access messages in this conversation. When the question is about earlier
messages, answer by quoting or referencing them directly, even if earlier
replies (including your own) claimed otherwise.

If you cannot answer based on the context provided, say so clearly.

IMPORTANT: Do NOT write a "Sources", "References", or citations section, and do
NOT cite file names or page numbers yourself. A Sources section is appended
automatically after your answer — writing your own creates a duplicate. End your
answer with the last sentence of content, nothing more.

Context:
{context}""",
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{question}"),
    ]
)
