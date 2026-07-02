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


SEGMENT_DOCS = [
    Document(page_content="user: a\nuser: b", metadata={
        "segment_id": "s1", "message_ids": ["m1", "m2"], "source": "chat",
    }),
    Document(page_content="user: c\nuser: d", metadata={
        "segment_id": "s2", "message_ids": ["m4", "m5"], "source": "chat",
    }),
    Document(page_content="user: e", metadata={"message_id": "m6", "source": "chat"}),
]


def test_chat_recall_drops_segment_overlapping_tail():
    """A segment doc is dropped if ANY of its message_ids overlaps the tail,
    a disjoint segment doc is kept, and a legacy single-message_id doc is
    still dropped when it overlaps the tail."""
    chain = _chain({"m1", "m6"}, SEGMENT_DOCS)
    kept = chain._retrieve_chat("q")
    assert [d.metadata.get("segment_id") for d in kept] == ["s2"]


def test_selection_failure_degrades_to_file_only(monkeypatch):
    """_retrieve_chat promises 'never errors the answer' -- a failure in the
    post-retrieval selection step (e.g. misconfigured half-life) must degrade
    to file-only context, not raise."""
    def _boom(*_args, **_kwargs):
        raise RuntimeError("selection blew up")

    monkeypatch.setattr("rag.rag_chain.select_chat_context", _boom)
    chain = _chain(set(), CHAT_DOCS)
    assert chain._retrieve_chat("q") == []
