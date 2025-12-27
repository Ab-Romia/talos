from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful AI assistant. Use the following context to answer the question.

If you cannot answer based on the context provided, say so clearly.

Context:
{context}"""),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{question}")
])


RAG_PROMPT_WITHOUT_MEMORY = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful AI assistant. Use the following context to answer the question.

If you cannot answer based on the context provided, say so clearly.

Context:
{context}"""),
    ("human", "{question}")
])
