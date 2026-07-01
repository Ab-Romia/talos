"""Task 6 — B5: a message briefly present in both tiers (vector already in
Milvus, indexed_at not yet committed) must be counted once. RAGChain drops
tail message_ids from tier-2 recall so the context never double-counts."""

from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from config import RagConfig
from rag.rag_chain import RAGChain


class _Fake:
    def __init__(self, docs):
        self._docs = docs

    def invoke(self, _query):
        return list(self._docs)


def _chain(exclude, chat_docs):
    return RAGChain(
        collection_name="x",
        config=RagConfig(use_hyde=False, use_query_rewrite=False, use_reranking=False),
        workspace_id="w",
        chatroom_id="c",
        exclude_message_ids=exclude,
        retriever=_Fake([]),
        chat_retriever=_Fake(chat_docs),
        llm=RunnableLambda(lambda pv: AIMessage(content="x")),
    )


CHAT_DOCS = [
    Document(page_content="user: a", metadata={"message_id": "m1", "source": "chat"}),
    Document(page_content="user: b", metadata={"message_id": "m3", "source": "chat"}),
]


def test_chat_recall_drops_tail_message_ids():
    chain = _chain({"m1"}, CHAT_DOCS)
    kept = chain._retrieve_chat("q")
    assert [d.metadata["message_id"] for d in kept] == ["m3"]


def test_no_exclusion_keeps_all():
    chain = _chain(set(), CHAT_DOCS)
    kept = chain._retrieve_chat("q")
    assert [d.metadata["message_id"] for d in kept] == ["m1", "m3"]
