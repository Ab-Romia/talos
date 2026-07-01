"""Debug harness: reproduce /ask internals and print everything.

Shows, for a given channel + question: the config actually in effect, the
un-indexed tail (tier-1), the retrieved chunks with metadata (tier-2), the EXACT
prompt sent to the LLM, and the answer. Everything after the query is read from
the SAME RagTrace the /ask debug flag serializes, so this script and the endpoint
can never drift. Run with the same env as the running app.
"""
import sys
from sqlalchemy import select
from langchain_core.messages import AIMessage, HumanMessage

from config import global_rag_config as C
from database import SessionLocal
from workspace.model import Channel
from chat.model import Message, MessageRole
from rag.rag_chain import RAGChain
from rag.vector_store import WORKSPACE_COLLECTION

CH = sys.argv[1] if len(sys.argv) > 1 else "019f1d81-f451-7258-a46b-73c8a03a04ce"
Q = sys.argv[2] if len(sys.argv) > 2 else "Where is the production deployment key stored?"


def rule(t): print("\n" + "═" * 78 + f"\n {t}\n" + "═" * 78)


with SessionLocal() as db:
    ws = db.scalar(select(Channel.workspace_id).where(Channel.id == CH))
    tail_rows = list(db.scalars(
        select(Message).where(Message.channel_id == CH, Message.indexed_at.is_(None))
        .order_by(Message.sent_at.desc()).limit(C.chat_context_cap)))
tail = [AIMessage(content=m.content) if m.role == MessageRole.ASSISTANT else HumanMessage(content=m.content)
        for m in reversed(tail_rows)]
tail_ids = {str(m.id) for m in tail_rows}

rule("1. CONFIG ACTUALLY IN EFFECT")
print(f"  LLM model            : {C.openai_model}")
print(f"  base_url             : {__import__('os').environ.get('OPENAI_BASE_URL', '(OpenAI default)')}")
print(f"  embedding provider   : {C.embedding_provider}")
print(f"  use_hyde             : {C.use_hyde}")
print(f"  use_query_rewrite    : {C.use_query_rewrite}")
print(f"  use_reranking        : {C.use_reranking}")
print(f"  retrieval_top_k      : {C.retrieval_top_k}   rerank_fetch_k: {C.rerank_fetch_k}   chat_recall_k: {C.chat_recall_k}")
print(f"  workspace_id         : {ws}")
print(f"  channel_id           : {CH}")

chain = RAGChain(collection_name=WORKSPACE_COLLECTION, workspace_id=str(ws),
                 chatroom_id=str(CH), chat_history=tail, exclude_message_ids=tail_ids)

rule("2. TIER-1  un-indexed tail injected as chat_history (indexed_at IS NULL)")
if tail:
    for m in tail:
        print(f"  [{m.type}] {m.content}")
else:
    print("  (empty — all messages in this channel are indexed; recall is via tier-2)")

# Run the real query path; this fills chain.trace exactly as /ask does.
answer = chain.query(Q, include_citations=False)
t = chain.trace

rule("3. TIER-2  retrieved chunks (what the vector search returned)")
print(f"  query embedded (rewritten): {t.rewritten_query!r}")
print(f"\n  FILE chunks (source=file): {len(t.file_candidates)}")
for i, d in enumerate(t.file_candidates, 1):
    print(f"    [{i}] {d['metadata']}  ::  {d['snippet']!r}")
print(f"\n  CHAT chunks (source=chat, this channel, tail excluded): {len(t.chat_candidates)}")
for i, d in enumerate(t.chat_candidates, 1):
    print(f"    [{i}] {d['metadata']}")
    print(f"        {d['snippet']!r}")

rule("4. EXACT PROMPT SENT TO THE LLM")
print(t.prompt)

rule("5. LLM ANSWER (from that exact prompt)")
print(answer)
print()
