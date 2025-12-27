from collections import deque
from langchain_core.messages import HumanMessage, AIMessage
from src_v2.config.settings import settings


class ConversationMemory:
    def __init__(self, k: int | None = None):
        self.k = k if k is not None else settings.conversation_memory_k
        self.messages = deque(maxlen=self.k * 2)  # 2x for human + AI pairs

    def add_user_message(self, message: str):
        self.messages.append(HumanMessage(content=message))

    def add_ai_message(self, message: str):
        self.messages.append(AIMessage(content=message))

    def get_messages(self):
        return list(self.messages)

    def clear(self):
        self.messages.clear()


def get_memory():
    return ConversationMemory()
