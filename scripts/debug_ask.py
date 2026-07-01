"""Debug harness: reproduce /ask internals and print everything.

Shows, for a given channel + question: the model/embedding config, the
un-indexed tail (tier-1), the retrieved chunks with full metadata (tier-2),
the EXACT prompt sent to the LLM, and the answer. Run with the same env as the
running app.
"""
import sys
from sqlalchemy import select
from langchain_core.messages import AIMessage, HumanMessage

from config import RAG_PROMPT, global_rag_config as C
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

rule("1. CONFIG ACTUALLY IN EFFECT")
print(f"  LLM model            : {C.openai_model}")
print(f"  base_url             : {__import__('os').environ.get('OPENAI_BASE_URL', '(OpenAI default)')}")
print(f"  embedding provider   : {C.embedding_provider}")
print(f"  use_hyde             : {C.use_hyde}")
print(f"  use_query_rewrite    : {C.use_query_rewrite}")
print(f"  use_reranking        : {C.use_reranking}")
print(f"  retrieval_top_k      : {C.retrieval_top_k}   chat_recall_k: {C.chat_recall_k}   chat_context_cap: {C.chat_context_cap}")
print(f"  workspace_id         : {ws}")
print(f"  channel_id           : {CH}")

chain = RAGChain(collection_name=WORKSPACE_COLLECTION, workspace_id=str(ws), chatroom_id=str(CH), chat_history=tail)

rule("2. TIER-1  un-indexed tail injected as chat_history (indexed_at IS NULL)")
if tail:
    for m in tail:
        print(f"  [{m.type}] {m.content}")
else:
    print("  (empty — all messages in this channel are indexed; recall is via tier-2)")

# retrieval (file docs -> self.retrieved_docs ; chat docs appended)
all_docs = chain._rewrite_and_retrieve(Q)
file_docs = chain.retrieved_docs
chat_docs = all_docs[len(file_docs):]

rule("3. TIER-2  retrieved chunks (what the vector search returned)")
print(f"  query embedded (rewritten): {chain.last_query_info.get('rewritten_query')!r}")
print(f"\n  FILE chunks (source=file): {len(file_docs)}")
for i, d in enumerate(file_docs, 1):
    print(f"    [{i}] {d.metadata}  ::  {d.page_content[:120]!r}")
print(f"\n  CHAT chunks (source=chat, this channel): {len(chat_docs)}")
for i, d in enumerate(chat_docs, 1):
    print(f"    [{i}] {d.metadata}")
    print(f"        {d.page_content!r}")

context = chain._format_docs(all_docs)
messages = RAG_PROMPT.format_messages(context=context, question=Q, chat_history=tail)

rule("4. EXACT PROMPT SENT TO THE LLM")
for msg in messages:
    print(f"\n----- {msg.type.upper()} MESSAGE -----")
    print(msg.content)

rule("5. LLM ANSWER (from that exact prompt)")
print(chain.llm.invoke(messages).content)
print()
