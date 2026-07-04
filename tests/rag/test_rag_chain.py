"""Task 5 — RAGChain on the shared pipeline, with a structured trace and the
B4 double-count fix. Uses the injection seam (retriever/llm) so no Milvus or
OpenAI is touched."""

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from config import RagConfig
from rag.rag_chain import RAGChain


class _FakeRetriever:
    def __init__(self, docs):
        self._docs = docs

    def invoke(self, _query):
        return list(self._docs)


def _make_chain(captured, *, config=None, chat_history=None, docs=None, request_id=None):
    config = config or RagConfig(use_hyde=False, use_query_rewrite=False, use_reranking=False)
    docs = docs if docs is not None else [Document(page_content="context chunk", metadata={"file_id": "f1"})]

    def fake_llm_fn(prompt_value):
        captured["messages"] = prompt_value.to_messages()
        return AIMessage(content="the answer")

    return RAGChain(
        collection_name="x",
        config=config,
        workspace_id="w",
        chatroom_id="c",
        chat_history=chat_history or [],
        retriever=_FakeRetriever(docs),
        chat_retriever=None,
        llm=RunnableLambda(fake_llm_fn),
        request_id=request_id,
    )


def test_live_question_not_duplicated_into_chat_history():
    """B4: the live question must appear once (question slot), never echoed into
    the chat_history slot."""
    captured = {}
    chain = _make_chain(captured, chat_history=[HumanMessage("earlier"), AIMessage("reply")])
    out = "".join(chain.stream_query("LIVE_Q", include_citations=False))
    assert out == "the answer"
    contents = [m.content for m in captured["messages"]]
    assert contents.count("LIVE_Q") == 1
    assert captured["messages"][-1].content == "LIVE_Q"


def test_trace_populated_after_query():
    captured = {}
    cfg = RagConfig(use_hyde=False, use_query_rewrite=False, use_reranking=False,
                    openai_model="gpt-test")
    chain = _make_chain(captured, config=cfg)
    list(chain.stream_query("myq", include_citations=False))
    t = chain.trace
    assert t.original_query == "myq"
    assert t.final_context == "context chunk"
    assert t.model == "gpt-test"
    assert t.file_candidates[0]["metadata"]["file_id"] == "f1"
    assert "myq" in t.prompt
    assert t.hyde_used is False
    assert t.effective_config["use_reranking"] is False


def test_prepare_then_stream_answer_matches_stream_query():
    """prepare() does retrieval eagerly; stream_answer() only generates."""
    captured = {}
    chain = _make_chain(captured, chat_history=[HumanMessage("earlier")])
    prepared = chain.prepare("LIVE_Q")
    assert prepared.question == "LIVE_Q"
    assert "context chunk" in prepared.context      # retrieval already happened
    assert [m.content for m in prepared.history] == ["earlier"]
    out = "".join(chain.stream_answer(prepared, include_citations=False))
    assert out == "the answer"
    assert chain.trace.original_query == "LIVE_Q"   # trace filled by stream_answer


def test_prepare_raises_on_retriever_failure():
    """Retrieval errors surface from prepare(), NOT mid-stream."""
    class _Boom:
        def invoke(self, _q):
            raise RuntimeError("milvus down")
    captured = {}
    chain = _make_chain(captured)
    chain.retriever = _Boom()
    import pytest
    with pytest.raises(RuntimeError, match="milvus down"):
        chain.prepare("q")


def test_stream_query_still_works_as_wrapper():
    captured = {}
    chain = _make_chain(captured)
    out = "".join(chain.stream_query("q", include_citations=False))
    assert out == "the answer"


def test_trace_records_timing_and_request_id():
    captured = {}
    chain = _make_chain(captured, request_id="req-123")
    prepared = chain.prepare("q")
    "".join(chain.stream_answer(prepared, include_citations=False))
    assert chain.trace.request_id == "req-123"
    assert chain.trace.retrieval_ms >= 0.0
    assert chain.trace.generation_ms >= 0.0


def test_request_id_constructor_arg():
    captured = {}
    chain = _make_chain(captured)
    assert hasattr(chain, "request_id")
