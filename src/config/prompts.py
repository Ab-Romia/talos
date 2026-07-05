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

If you cannot answer based on the context provided, say so clearly.

Do not write a "Sources" or citations section yourself; one is appended automatically after your answer.

Context:
{context}""",
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{question}"),
    ]
)
