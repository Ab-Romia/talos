"""Helpers for the Talos RAG evaluation notebook.

Designed to be imported from `evaluation/rag_evaluation.ipynb`. Exposes:

* corpus loading + chunking
* in-memory dense / hybrid retriever builders that mirror src/rag/retrieval
* a `RagVariant` runner exercising the production query-rewriter, HyDE,
  reranker, and compression code paths
* synthetic Q&A generation (single-hop specific, multi-hop specific,
  multi-hop abstract) and a second-pass quality filter
* classical retrieval IR metrics (Hit@k, Recall@k, Precision@k, MRR, nDCG@k)
* LLM-as-judge metrics (Faithfulness, Answer Relevancy, Context Relevance,
  Answer Correctness) and an embedding-based Answer Similarity
* bootstrap CIs and paired Wilcoxon with rank-biserial effect size
* an on-disk JSON cache so re-runs don't re-bill the LLM

The intent is to leave heavy logic here so the notebook stays narrative.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, Field

# Make `src/` importable so we can re-use production code.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Lazily import langchain pieces so importing this module is cheap.
def _lc():
    from langchain_core.documents import Document
    from langchain_core.vectorstores.in_memory import InMemoryVectorStore
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.retrievers import BM25Retriever
    from langchain_classic.retrievers import (
        EnsembleRetriever,
        ContextualCompressionRetriever,
    )
    from langchain_classic.retrievers.document_compressors import (
        CrossEncoderReranker,
    )
    from langchain_community.cross_encoders import HuggingFaceCrossEncoder

    return {
        "Document": Document,
        "InMemoryVectorStore": InMemoryVectorStore,
        "RecursiveCharacterTextSplitter": RecursiveCharacterTextSplitter,
        "BM25Retriever": BM25Retriever,
        "EnsembleRetriever": EnsembleRetriever,
        "ContextualCompressionRetriever": ContextualCompressionRetriever,
        "CrossEncoderReranker": CrossEncoderReranker,
        "HuggingFaceCrossEncoder": HuggingFaceCrossEncoder,
    }


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


def load_corpus(
    path: str | Path,
    max_articles: int | None = 500,
    min_chars: int = 200,
    seed: int = 42,
):
    """Load a pickled Wikipedia subset and return a list of Documents.

    Accepts these on-disk shapes:
      - list[str]: each element is article text
      - list[dict]: dict with 'text' (required), 'title', 'url', 'id' (optional)
      - list[Document]: passed through, only re-sampled
      - dict[str, str | dict]: values become docs, keys become ids
    """
    Document = _lc()["Document"]
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Corpus not found: {path}")
    with open(path, "rb") as f:
        raw = pickle.load(f)  # noqa: S301 — eval-time, user-supplied corpus

    docs: list = []
    if isinstance(raw, dict):
        items: Iterable[tuple[Any, Any]] = raw.items()
        for key, value in items:
            doc = _coerce_doc(value, default_id=str(key), Document=Document)
            if doc is not None:
                docs.append(doc)
    elif isinstance(raw, list):
        for i, value in enumerate(raw):
            doc = _coerce_doc(value, default_id=f"art_{i}", Document=Document)
            if doc is not None:
                docs.append(doc)
    else:
        raise TypeError(f"Unsupported corpus type: {type(raw).__name__}")

    docs = [d for d in docs if len(d.page_content) >= min_chars]

    if max_articles is not None and len(docs) > max_articles:
        rng = random.Random(seed)
        docs = rng.sample(docs, max_articles)

    for i, d in enumerate(docs):
        d.metadata.setdefault("article_id", d.metadata.get("id", f"art_{i}"))
    return docs


def load_local_corpus(folder: str | Path, *, max_files: int | None = None):
    """Load a folder of local documents (PDF / Markdown / text / source code)
    into Documents matching the shape produced by `load_corpus`.

    Used by `rag_evaluation_talos.ipynb` to evaluate against a corpus of
    documents representative of what users actually upload to Talos
    workspaces (CS course PDFs, API docs, recent CS papers, the project's
    own `docs/`), rather than against the Wikipedia-CS pickle.

    Supported extensions: .pdf, .md, .markdown, .txt, .rst, .py, .yaml,
    .yml, .json (treated as text), .toml, .html (text-only via stripping
    tags), .ipynb (cell sources only).
    """
    Document = _lc()["Document"]
    folder = Path(folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Talos corpus folder not found: {folder}")

    text_exts = {".md", ".markdown", ".txt", ".rst", ".py", ".yaml", ".yml",
                 ".json", ".toml", ".cfg", ".ini", ".env.example", ".sh"}
    docs: list = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        try:
            if ext == ".pdf":
                text = _read_pdf(path)
            elif ext == ".ipynb":
                text = _read_ipynb(path)
            elif ext == ".html" or ext == ".htm":
                text = _read_html(path)
            elif ext in text_exts or path.name in {"README", "Makefile"}:
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                continue
        except Exception as e:
            sys.stderr.write(f"[load_local_corpus] skip {path}: {e}\n")
            continue
        text = (text or "").strip()
        if len(text) < 200:
            continue  # too short to be useful
        article_id = f"talos_{len(docs):04d}"
        docs.append(
            Document(
                page_content=text,
                metadata={
                    "article_id": article_id,
                    "title": path.stem,
                    "source": str(path.relative_to(folder)),
                    "ext": ext,
                },
            )
        )
        if max_files is not None and len(docs) >= max_files:
            break
    return docs


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _read_ipynb(path: Path) -> str:
    nb = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    parts = []
    for cell in nb.get("cells", []):
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        if cell.get("cell_type") == "markdown":
            parts.append(src)
        elif cell.get("cell_type") == "code":
            parts.append(f"```python\n{src}\n```")
    return "\n\n".join(parts)


def _read_html(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return re.sub(r"<[^>]+>", " ", text)


def _coerce_doc(value, default_id: str, Document):
    if isinstance(value, Document):
        value.metadata.setdefault("article_id", default_id)
        return value
    if isinstance(value, str):
        return Document(page_content=value, metadata={"article_id": default_id})
    if isinstance(value, dict):
        text = value.get("text") or value.get("content") or value.get("body")
        if not text:
            return None
        meta = {
            "article_id": value.get("id") or default_id,
            "title": value.get("title", ""),
            "url": value.get("url", ""),
        }
        return Document(page_content=text, metadata=meta)
    return None


def chunk_documents(
    docs: list,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list:
    """Split documents into chunks. Each chunk gets a stable `chunk_id`."""
    splitter = _lc()["RecursiveCharacterTextSplitter"](
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    for i, c in enumerate(chunks):
        article_id = c.metadata.get("article_id", "art_unk")
        c.metadata["chunk_id"] = f"{article_id}::chunk_{i}"
    return chunks


# ---------------------------------------------------------------------------
# Index / retriever construction
# ---------------------------------------------------------------------------


def build_vectorstore(chunks, embeddings):
    InMemoryVectorStore = _lc()["InMemoryVectorStore"]
    vs = InMemoryVectorStore.from_documents(chunks, embedding=embeddings)
    return vs


@lru_cache(maxsize=1)
def _cross_encoder():
    HuggingFaceCrossEncoder = _lc()["HuggingFaceCrossEncoder"]
    return HuggingFaceCrossEncoder(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")


def build_retriever(
    vectorstore,
    chunks,
    *,
    top_k: int = 5,
    use_hybrid: bool = False,
    use_rerank: bool = False,
):
    """Mirror of `src/rag/retrieval/retrievers.py::get_retriever` for eval.

    We re-implement here (rather than calling the production function) because
    the production function depends on `RagConfig`; we want to vary flags
    explicitly per ablation row.
    """
    base_kwargs = {"k": top_k}
    dense = vectorstore.as_retriever(
        search_type="similarity", search_kwargs=base_kwargs
    )
    if use_hybrid:
        BM25Retriever = _lc()["BM25Retriever"]
        EnsembleRetriever = _lc()["EnsembleRetriever"]
        bm25 = BM25Retriever.from_documents(chunks)
        bm25.k = top_k
        base = EnsembleRetriever(retrievers=[dense, bm25], weights=[0.5, 0.5])
    else:
        base = dense

    if use_rerank:
        CrossEncoderReranker = _lc()["CrossEncoderReranker"]
        ContextualCompressionRetriever = _lc()["ContextualCompressionRetriever"]
        reranker = CrossEncoderReranker(model=_cross_encoder(), top_n=top_k)
        return ContextualCompressionRetriever(
            base_compressor=reranker, base_retriever=base
        )
    return base


# ---------------------------------------------------------------------------
# Inlined production helpers
# ---------------------------------------------------------------------------
#
# `src/rag/__init__.py` re-exports `vector_store` at import time, and
# `vector_store.py` currently carries unresolved merge-conflict markers on
# this branch. To keep the eval runnable independent of that, we inline the
# three small helpers we need from `src/rag/retrieval` here. The production
# code paths these mirror are:
#   - `rag.retrieval.query_processing.get_hyde_embeddings`
#   - `rag.retrieval.query_processing.get_query_rewriter` (built from
#     `config.QUERY_REWRITE_PROMPT | llm` — done inline in `RagVariant`)
#   - `rag.retrieval.compression.compression_retriever`


def _hyde_embeddings(base_embeddings, llm):
    """Mirror of `rag.retrieval.query_processing.get_hyde_embeddings`."""
    from langchain_classic.chains.hyde.base import HypotheticalDocumentEmbedder

    return HypotheticalDocumentEmbedder.from_llm(
        llm=llm, base_embeddings=base_embeddings, prompt_key="web_search"
    )


def _compression_retriever(
    base_retriever, compression_type: str, llm, embeddings, threshold: float = 0.76
):
    """Mirror of `rag.retrieval.compression.compression_retriever`. Threshold
    is configurable so the eval can sweep across calibration points (the v2
    run surfaced 0.76 as too aggressive for `text-embedding-3-small`)."""
    from langchain_classic.retrievers import ContextualCompressionRetriever
    from langchain_classic.retrievers.document_compressors import (
        LLMChainExtractor,
        EmbeddingsFilter,
        DocumentCompressorPipeline,
    )

    if compression_type == "embeddings":
        compressor = EmbeddingsFilter(
            embeddings=embeddings, similarity_threshold=threshold
        )
    elif compression_type == "llm":
        compressor = LLMChainExtractor.from_llm(llm)
    elif compression_type == "pipeline":
        compressor = DocumentCompressorPipeline(
            transformers=[
                EmbeddingsFilter(embeddings=embeddings, similarity_threshold=threshold),
                LLMChainExtractor.from_llm(llm),
            ]
        )
    else:
        return base_retriever
    return ContextualCompressionRetriever(
        base_compressor=compressor, base_retriever=base_retriever
    )


# ---------------------------------------------------------------------------
# Variant runner — exercises real production prompts and chains
# ---------------------------------------------------------------------------


@dataclass
class VariantConfig:
    name: str
    use_retrieval: bool = True
    use_rewrite: bool = False
    use_hyde: bool = False
    use_rerank: bool = False
    use_hybrid: bool = False
    compression: Literal["none", "embeddings", "llm", "pipeline"] = "none"
    compression_threshold: float = 0.76
    top_k: int = 5


def default_variants(top_k: int = 5) -> list[VariantConfig]:
    """The ablation grid in EVALUATION_PLAN.md §4.2.

    Includes:
      * `production_default` — the actual `src/config/config.py` ship config
        (dense retrieval + cross-encoder rerank, no rewriting / HyDE / hybrid /
        compression). This is the row the report should headline.
      * Single-component additions on top of `dense_only`: `+rewrite`, `+hyde`,
        `+rerank`, `hybrid+rerank`.
      * `compression_calibrated` — same as `everything_on_stress` but with the
        embeddings filter threshold dropped from 0.76 → 0.50, to test whether
        the compression regression in v2 is a config-only bug.
      * `everything_on_stress` (was `full_system` in v2) — every available
        feature on, including the production-default-OFF embeddings filter at
        its langchain-default threshold. NAME CHANGED to make clear this is a
        stress test, not the deployed config.
    """
    return [
        VariantConfig(name="closed_book", use_retrieval=False, top_k=top_k),
        VariantConfig(name="dense_only", top_k=top_k),
        VariantConfig(
            name="production_default",
            use_rerank=True,
            top_k=top_k,
        ),
        VariantConfig(name="+rewrite", use_rewrite=True, top_k=top_k),
        VariantConfig(name="+hyde", use_rewrite=True, use_hyde=True, top_k=top_k),
        VariantConfig(
            name="+rerank",
            use_rewrite=True,
            use_hyde=True,
            use_rerank=True,
            top_k=top_k,
        ),
        VariantConfig(
            name="hybrid+rerank",
            use_rewrite=True,
            use_hyde=True,
            use_rerank=True,
            use_hybrid=True,
            top_k=top_k,
        ),
        VariantConfig(
            name="compression_calibrated",
            use_rewrite=True,
            use_hyde=True,
            use_rerank=True,
            use_hybrid=True,
            compression="embeddings",
            compression_threshold=0.50,
            top_k=top_k,
        ),
        VariantConfig(
            name="everything_on_stress",
            use_rewrite=True,
            use_hyde=True,
            use_rerank=True,
            use_hybrid=True,
            compression="embeddings",
            compression_threshold=0.76,
            top_k=top_k,
        ),
    ]


class RagVariant:
    """One row of the ablation grid, exercising the real production helpers.

    Vectorstores are built ONCE by the caller and passed in via
    `base_vectorstore` / `hyde_vectorstore` (this avoids re-embedding the
    corpus for each variant). HyDE only changes the *query* embedding path,
    so the document vectors in `base_vectorstore` are reused.

    Closed-book variants use a plain answer prompt (no "use the following
    context" wording) so the baseline isn't biased toward refusals.
    """

    def __init__(
        self,
        config: VariantConfig,
        chunks: list,
        base_embeddings,
        llm,
        *,
        base_vectorstore=None,
        hyde_vectorstore=None,
        cache: "JsonCache | None" = None,
    ):
        self.config = config
        self.chunks = chunks
        self.base_embeddings = base_embeddings
        self.llm = llm
        self.cache = cache

        if config.use_retrieval:
            if config.use_hyde:
                if hyde_vectorstore is None:
                    self.embeddings = _hyde_embeddings(base_embeddings, llm)
                    self.vectorstore = build_vectorstore(chunks, self.embeddings)
                else:
                    self.vectorstore = hyde_vectorstore
                    self.embeddings = hyde_vectorstore.embedding
            else:
                self.embeddings = base_embeddings
                self.vectorstore = base_vectorstore or build_vectorstore(
                    chunks, base_embeddings
                )

            self.retriever = build_retriever(
                self.vectorstore,
                chunks,
                top_k=config.top_k,
                use_hybrid=config.use_hybrid,
                use_rerank=config.use_rerank,
            )
            if config.compression != "none":
                self.retriever = _compression_retriever(
                    self.retriever,
                    compression_type=config.compression,
                    llm=llm,
                    embeddings=base_embeddings,
                    threshold=config.compression_threshold,
                )
        else:
            self.retriever = None

        from config import RAG_PROMPT_WITHOUT_MEMORY, QUERY_REWRITE_PROMPT

        if config.use_rewrite:
            self.rewriter = QUERY_REWRITE_PROMPT | llm
        else:
            self.rewriter = None

        self.answer_prompt = RAG_PROMPT_WITHOUT_MEMORY
        # Closed-book uses a separate plain prompt so the LLM isn't told to
        # "use the following context" when there is none.
        from langchain_core.prompts import ChatPromptTemplate

        self.closed_book_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful assistant. Answer the user's question "
                    "to the best of your knowledge. If you do not know the "
                    "answer, say so honestly.",
                ),
                ("human", "{question}"),
            ]
        )

    # -------- core run ---------------------------------------------------

    def answer(self, question: str) -> tuple[str, list]:
        cache_key = self._cache_key(question)
        if self.cache is not None:
            hit = self.cache.get(cache_key)
            if hit is not None:
                from langchain_core.documents import Document

                retrieved = [Document(**d) for d in hit["retrieved"]]
                return hit["answer"], retrieved

        retrieved: list = []
        query_for_retrieval = question
        if self.rewriter is not None:
            rewritten = self.rewriter.invoke({"query": question})
            query_for_retrieval = (
                rewritten.content
                if not isinstance(rewritten.content, list)
                else str(rewritten)
            ).strip()

        if self.retriever is not None:
            retrieved = list(self.retriever.invoke(query_for_retrieval))
            context = "\n\n".join(d.page_content for d in retrieved)
            msg = self.answer_prompt.invoke({"context": context, "question": question})
        else:
            # Closed-book / no-retrieval baseline — no "context" framing.
            msg = self.closed_book_prompt.invoke({"question": question})

        ai_msg = self.llm.invoke(msg)
        answer = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)

        if self.cache is not None:
            self.cache.set(
                cache_key,
                {
                    "answer": answer,
                    "retrieved": [
                        {"page_content": d.page_content, "metadata": dict(d.metadata)}
                        for d in retrieved
                    ],
                },
            )
        return answer, retrieved

    def answer_with_contexts(self, question: str, contexts: list[str]) -> str:
        """Run the generator with externally supplied contexts (for the
        counterfactual-noise diagnostic). No caching — each call is unique."""
        joined = "\n\n".join(contexts)
        msg = self.answer_prompt.invoke({"context": joined, "question": question})
        ai_msg = self.llm.invoke(msg)
        return ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)

    def _cache_key(self, question: str) -> str:
        body = json.dumps(
            {"v": asdict(self.config), "q": question},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(body.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Q&A synthesis
# ---------------------------------------------------------------------------


@dataclass
class QAItem:
    qid: str
    question: str
    answer: str
    gold_chunk_id: str
    gold_chunk_text: str
    category: str  # single_hop_specific | multi_hop_specific | multi_hop_abstract
    gold_chunk_ids: list[str] | None = None  # multi-hop carries both


# ----- Pydantic schemas for structured output (drop-in replacement for regex) ---


class _QASchema(BaseModel):
    question: str = Field(description="A specific, fact-checkable question.")
    answer: str = Field(description="The answer, fully derivable from the passage(s).")


class _ReviewSchema(BaseModel):
    keep: bool
    reason: str = ""


class _FaithfulnessSchema(BaseModel):
    claims: list[str] = Field(default_factory=list)
    supported: list[int] = Field(default_factory=list)
    score: float
    rationale: str = ""


class _RelevancySchema(BaseModel):
    score: float
    rationale: str = ""


class _ContextRelSchema(BaseModel):
    relevant: int
    rationale: str = ""


class _CorrectnessSchema(BaseModel):
    score: float
    rationale: str = ""


def _structured_invoke(llm, schema_cls, prompt: str, retries: int = 3) -> Any | None:
    """Call llm.with_structured_output(schema_cls).invoke(prompt) with retries.

    Uses OpenAI native Structured Outputs (`method="json_schema", strict=True`)
    so the response is guaranteed to match `schema_cls` — no regex parsing.
    Returns parsed schema instance or None after exhausting retries; doesn't
    raise so caller loops can keep going on transient failures.
    """
    try:
        structured = llm.with_structured_output(
            schema_cls, method="json_schema", strict=True
        )
    except TypeError:
        # Older langchain-openai: fall back to default (function_calling).
        structured = llm.with_structured_output(schema_cls)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return structured.invoke(prompt)
        except Exception as e:  # APIConnectionError / RateLimit / parse failure
            last_err = e
            if attempt == retries - 1:
                break
            time.sleep(1.0 * (2 ** attempt) + random.random() * 0.3)
    if last_err is not None:
        sys.stderr.write(f"[structured_invoke] giving up after {retries}: {last_err}\n")
    return None


_SYNTH_PROMPT_SINGLE = """You are writing exam questions to test whether a reading-
comprehension system has read a specific passage. Use ONLY the passage below.

Rules:
- The question must be specific and fact-checkable; its answer must be fully
  contained in the passage.
- The answer must be a short factual span or sentence (≤30 words), copied or
  paraphrased from the passage. NEVER invent facts.
- Do not write a question whose answer is the article title.
- Do not include "according to the passage" / "in this text" in the question.
- If the passage is too thin (just a list of references, a stub, etc.) to
  ground a clean question, return question="" and answer="" — those will be
  dropped downstream.

Passage:
\"\"\"{chunk}\"\"\"
"""


_SYNTH_PROMPT_MULTI_SPECIFIC = """You are writing exam questions that REQUIRE
combining facts from BOTH passages to answer.

Rules:
- The question must NOT be answerable from either passage alone.
- The answer must be specific (a name, value, technique, or one-sentence claim).
- The answer must be fully supported by the union of the passages — DO NOT
  invent connections, dates, or causal links that aren't stated.
- If the two passages are not actually related enough to support a real
  multi-hop question, return question="" and answer="" — that's fine and
  preferable to an inferred bridge.
- Do not name the passages or use phrases like "passage A".

Passage 1:
\"\"\"{chunk_a}\"\"\"

Passage 2:
\"\"\"{chunk_b}\"\"\"
"""


_SYNTH_PROMPT_MULTI_ABSTRACT = """You are writing one open-ended exam question
for an expert in computer science, asking for a comparison, contrast, or
synthesis between the two passages.

Rules:
- The question must be open-ended (compare / contrast / what trade-off /
  what is the relationship between).
- The answer must be 1–3 sentences, fully derivable from the passages — no
  invented connections.
- If the passages don't support a comparison, return question="" and
  answer="".
- Do not name the passages directly.

Passage 1:
\"\"\"{chunk_a}\"\"\"

Passage 2:
\"\"\"{chunk_b}\"\"\"
"""


_REVIEW_PROMPT = """You are reviewing a synthetic exam question for quality.

Reject (keep=false) ONLY if one of these is clearly true:
- The answer is empty / "unknown" / "not in the passage".
- The question references "the passage" / "the text" / "this article".
- The answer is COMPLETELY unsupported by the passages (a fabricated fact,
  not just an inference). Reasonable inferences across both passages are
  fine for multi-hop questions — that's the point.
- The question is trivial (asking the article title, a yes/no with no
  informational content).

When in doubt, KEEP. Be generous; the goal is a usable test set, not a
perfect one.

Question: {question}
Answer:   {answer}
Passages:
\"\"\"{passages}\"\"\"
"""


def _build_topical_pairs(
    chunks: list,
    embeddings_model,
    n_pairs: int,
    *,
    min_sim: float = 0.55,
    max_sim: float = 0.92,
    pool_cap: int = 1000,
    seed: int = 42,
) -> list[tuple]:
    """Pair chunks by cosine similarity. Returns a list of (chunk_a, chunk_b)
    pairs whose embeddings are between [min_sim, max_sim] (related but not
    near-duplicates). Replaces the previous random-pair sampling that produced
    hallucinated bridge questions.
    """
    if n_pairs <= 0:
        return []
    import numpy as np

    rng = random.Random(seed)
    pool = [c for c in chunks if len(c.page_content) >= 400]
    rng.shuffle(pool)
    pool = pool[: min(len(pool), pool_cap)]
    if len(pool) < 2:
        return []

    texts = [c.page_content[:1500] for c in pool]
    vecs = np.array(embeddings_model.embed_documents(texts), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs_n = vecs / (norms + 1e-9)
    sim = vecs_n @ vecs_n.T  # n×n cosine

    pairs: list[tuple] = []
    used: set[int] = set()
    indices = list(range(len(pool)))
    rng.shuffle(indices)
    for i in indices:
        if len(pairs) >= n_pairs:
            break
        if i in used:
            continue
        # Same-article pairs aren't really "multi-hop" — skip those too.
        article_i = pool[i].metadata.get("article_id")
        candidates = [
            j
            for j in range(len(pool))
            if j != i
            and j not in used
            and pool[j].metadata.get("article_id") != article_i
            and min_sim <= float(sim[i, j]) <= max_sim
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda j: -float(sim[i, j]))
        # Among the top few, pick one randomly so we don't always grab the
        # nearest neighbor (which can collapse pairs into a few clusters).
        top = candidates[: min(5, len(candidates))]
        j = rng.choice(top)
        pairs.append((pool[i], pool[j]))
        used.add(i)
        used.add(j)
    return pairs


def synthesize_qa(
    chunks: list,
    judge_llm,
    *,
    embeddings_model=None,
    n_per_category: dict[str, int] | None = None,
    seed: int = 42,
    progress: Callable[[str], None] | None = None,
) -> list[QAItem]:
    """Generate a stratified test set. Per-item exceptions are caught so a
    single LLM blip can't kill the whole synthesis.

    `embeddings_model` is required when any multi_hop_* category is requested
    — pairs are sampled by cosine similarity rather than uniformly at random.
    """
    n_per_category = n_per_category or {
        "single_hop_specific": 40,
        "multi_hop_specific": 20,
        "multi_hop_abstract": 20,
    }
    log = progress or (lambda s: None)
    rng = random.Random(seed)
    items: list[QAItem] = []

    eligible = [c for c in chunks if len(c.page_content) >= 400]
    if not eligible:
        eligible = chunks

    # ---------- single-hop ----------
    pool = list(eligible)
    rng.shuffle(pool)
    target_sh = n_per_category.get("single_hop_specific", 0)
    log(f"single-hop: trying {target_sh} chunks")
    sh_idx = 0
    attempts = 0
    while len([x for x in items if x.category == "single_hop_specific"]) < target_sh and attempts < target_sh * 3:
        if sh_idx >= len(pool):
            break
        chunk = pool[sh_idx]
        sh_idx += 1
        attempts += 1
        prompt = _SYNTH_PROMPT_SINGLE.format(chunk=chunk.page_content[:2000])
        try:
            qa = _structured_invoke(judge_llm, _QASchema, prompt)
        except Exception as e:
            log(f"  sh skip: {type(e).__name__}: {e}")
            continue
        if qa is None or not qa.question.strip() or not qa.answer.strip():
            continue
        items.append(
            QAItem(
                qid=f"sh_{len([x for x in items if x.category == 'single_hop_specific']):03d}",
                question=qa.question.strip(),
                answer=qa.answer.strip(),
                gold_chunk_id=chunk.metadata["chunk_id"],
                gold_chunk_ids=[chunk.metadata["chunk_id"]],
                gold_chunk_text=chunk.page_content,
                category="single_hop_specific",
            )
        )

    # ---------- multi-hop ----------
    multi_total = n_per_category.get("multi_hop_specific", 0) + n_per_category.get(
        "multi_hop_abstract", 0
    )
    if multi_total > 0:
        if embeddings_model is None:
            log(
                "WARNING: multi-hop requested without embeddings_model; falling "
                "back to random pairs (hallucinated-bridge risk). "
                "Pass embeddings_model=embeddings to synthesize_qa()."
            )
            pairs_specific = [tuple(rng.sample(eligible, 2)) for _ in range(n_per_category.get("multi_hop_specific", 0) * 2)]
            pairs_abstract = [tuple(rng.sample(eligible, 2)) for _ in range(n_per_category.get("multi_hop_abstract", 0) * 2)]
        else:
            log("multi-hop: embedding pool for topical pairing…")
            # Generate ~2× the needed pairs to allow downstream filtering.
            pairs_specific = _build_topical_pairs(
                eligible,
                embeddings_model,
                n_per_category.get("multi_hop_specific", 0) * 2,
                seed=seed,
            )
            pairs_abstract = _build_topical_pairs(
                eligible,
                embeddings_model,
                n_per_category.get("multi_hop_abstract", 0) * 2,
                seed=seed + 1,
            )

        for cat, prompt_tmpl, prefix, pairs, target in [
            (
                "multi_hop_specific",
                _SYNTH_PROMPT_MULTI_SPECIFIC,
                "mhs",
                pairs_specific,
                n_per_category.get("multi_hop_specific", 0),
            ),
            (
                "multi_hop_abstract",
                _SYNTH_PROMPT_MULTI_ABSTRACT,
                "mha",
                pairs_abstract,
                n_per_category.get("multi_hop_abstract", 0),
            ),
        ]:
            log(f"{cat}: trying {len(pairs)} pairs (target {target})")
            for a, b in pairs:
                if len([x for x in items if x.category == cat]) >= target:
                    break
                prompt = prompt_tmpl.format(
                    chunk_a=a.page_content[:1500], chunk_b=b.page_content[:1500]
                )
                try:
                    qa = _structured_invoke(judge_llm, _QASchema, prompt)
                except Exception as e:
                    log(f"  {prefix} skip: {type(e).__name__}: {e}")
                    continue
                if qa is None or not qa.question.strip() or not qa.answer.strip():
                    continue
                items.append(
                    QAItem(
                        qid=f"{prefix}_{len([x for x in items if x.category == cat]):03d}",
                        question=qa.question.strip(),
                        answer=qa.answer.strip(),
                        gold_chunk_id=a.metadata["chunk_id"],
                        gold_chunk_ids=[
                            a.metadata["chunk_id"],
                            b.metadata["chunk_id"],
                        ],
                        gold_chunk_text=f"{a.page_content}\n\n---\n\n{b.page_content}",
                        category=cat,
                    )
                )

    log(f"synthesised {len(items)} items: {dict((c, sum(1 for x in items if x.category == c)) for c in n_per_category)}")
    return items


def review_qa(items: list[QAItem], judge_llm, *, embeddings_model=None, sim_threshold: float = 0.20) -> list[QAItem]:
    """Two-stage filter:

    1. Embedding-cosine pre-filter: reject items where the answer is not
       semantically similar to its source chunk(s) — those are LLM
       hallucinations regardless of what review_qa says.

       Threshold default is 0.20 because text-embedding-3-small cosine
       between a 30-word answer and a 3000-char source paragraph is
       typically 0.3–0.7 even for clean extractive answers; anything ≥0.20
       has at least topical overlap. We're trying to catch pure
       hallucinations (sim ≈ 0), not borderline paraphrases.

    2. LLM judge for the rest.

    `embeddings_model` is optional; if absent, only the LLM judge runs.
    """
    import numpy as np

    kept: list[QAItem] = []

    # Stage 1: embedding pre-filter (cheap, deterministic).
    if embeddings_model is not None and items:
        sources = [item.gold_chunk_text[:3000] for item in items]
        answers = [item.answer for item in items]
        try:
            src_vecs = np.array(embeddings_model.embed_documents(sources), dtype=np.float32)
            ans_vecs = np.array(embeddings_model.embed_documents(answers), dtype=np.float32)
            src_n = src_vecs / (np.linalg.norm(src_vecs, axis=1, keepdims=True) + 1e-9)
            ans_n = ans_vecs / (np.linalg.norm(ans_vecs, axis=1, keepdims=True) + 1e-9)
            sims = (src_n * ans_n).sum(axis=1)
        except Exception as e:
            sys.stderr.write(f"[review_qa] embedding pre-filter failed: {e}\n")
            sims = np.ones(len(items))
    else:
        sims = [1.0] * len(items)

    # Stage 2: LLM judge.
    for item, sim in zip(items, sims):
        if float(sim) < sim_threshold:
            continue
        prompt = _REVIEW_PROMPT.format(
            question=item.question,
            answer=item.answer,
            passages=item.gold_chunk_text[:3000],
        )
        try:
            verdict = _structured_invoke(judge_llm, _ReviewSchema, prompt)
        except Exception as e:
            sys.stderr.write(f"[review_qa] LLM judge failed for {item.qid}: {e}\n")
            continue
        if verdict is not None and verdict.keep:
            kept.append(item)
    return kept


# ---------------------------------------------------------------------------
# Retrieval IR metrics
# ---------------------------------------------------------------------------


def hit_rate_at_k(retrieved_ids: list[str], gold_id: str, k: int) -> float:
    return 1.0 if gold_id in retrieved_ids[:k] else 0.0


def recall_at_k(retrieved_ids: list[str], gold_ids: set[str], k: int) -> float:
    if not gold_ids:
        return 0.0
    hits = sum(1 for r in retrieved_ids[:k] if r in gold_ids)
    return hits / len(gold_ids)


def precision_at_k(retrieved_ids: list[str], gold_ids: set[str], k: int) -> float:
    top = retrieved_ids[:k]
    if not top:
        return 0.0
    return sum(1 for r in top if r in gold_ids) / len(top)


def reciprocal_rank(retrieved_ids: list[str], gold_id: str) -> float:
    for i, r in enumerate(retrieved_ids, 1):
        if r == gold_id:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], gold_ids: set[str], k: int) -> float:
    if not gold_ids:
        return 0.0
    dcg = 0.0
    for i, r in enumerate(retrieved_ids[:k], 1):
        if r in gold_ids:
            dcg += 1.0 / math.log2(i + 1)
    ideal_hits = min(len(gold_ids), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


# ---------------------------------------------------------------------------
# LLM-as-judge metrics
# ---------------------------------------------------------------------------


_JUDGE_FAITHFULNESS = """You are evaluating whether an ANSWER is grounded in
the CONTEXT.

Step 1: list AT MOST 8 atomic factual claims in the ANSWER as a JSON array
        of short strings (one sentence each, ≤ 25 words). If the answer
        contains more than 8 claims, pick the 8 most central ones.
Step 2: for each claim, output 1 if it is fully supported by the CONTEXT,
        0 otherwise.

Score = mean of `supported`. Rationale ≤ 50 words.

If the answer is "I don't know" / "the context does not contain..." score 1
(refusing to fabricate is faithful) and return claims=[].

CONTEXT:
\"\"\"{context}\"\"\"

ANSWER:
\"\"\"{answer}\"\"\"
"""


_JUDGE_ANSWER_RELEVANCY = """You are evaluating whether an ANSWER addresses
the QUESTION asked. Score on a 0/0.5/1 scale:
  1.0 = directly answers the question
  0.5 = partially addresses or hedges
  0.0 = off-topic or refuses without justification

Reply with JSON: {{"score": <0.0|0.5|1.0>, "rationale": "..."}}.

QUESTION: {question}

ANSWER:
\"\"\"{answer}\"\"\"

JSON:"""


_JUDGE_CONTEXT_RELEVANCE = """You are evaluating whether a retrieved CHUNK
is relevant to a QUESTION. Reply with JSON:
{{"relevant": 0|1, "rationale": "..."}}.

A chunk is relevant (1) iff it contains information that helps answer the
question, even if it does not contain the full answer.

QUESTION: {question}

CHUNK:
\"\"\"{chunk}\"\"\"

JSON:"""


_JUDGE_CORRECTNESS = """You are grading an ANSWER against a REFERENCE
answer to the same QUESTION. Score factual correctness on 0 / 0.5 / 1:
  1.0 = factually equivalent to the reference (paraphrase OK)
  0.5 = partially correct, missing or adding minor facts
  0.0 = contradicts or misses the reference

Reply with JSON: {{"score": <0.0|0.5|1.0>, "rationale": "..."}}.

QUESTION: {question}
REFERENCE: {reference}
ANSWER:
\"\"\"{answer}\"\"\"

JSON:"""


def judge_faithfulness(
    answer: str, contexts: list[str], judge_llm
) -> tuple[float | None, str]:
    """Returns (score, rationale). Score is None when faithfulness is
    structurally undefined (no retrieved context) — see Ragas Faithfulness
    docs and arXiv:2504.14891."""
    if not contexts:
        return None, "no retrieved context (faithfulness undefined)"
    # Truncate each chunk individually so all k chunks contribute, then cap
    # the total. 5 chunks × 600 chars = 3000-char context budget — fits
    # comfortably under gpt-4o-mini's 16k completion cap with the claim
    # enumeration on top.
    per_chunk = 600
    parts = [c[:per_chunk] for c in contexts]
    ctx = "\n\n---\n\n".join(parts)[:3500]
    res = _structured_invoke(
        judge_llm,
        _FaithfulnessSchema,
        _JUDGE_FAITHFULNESS.format(context=ctx, answer=answer[:1500]),
    )
    if res is None:
        return 0.0, "judge unreachable"
    return float(res.score), res.rationale


def judge_answer_relevancy(answer: str, question: str, judge_llm) -> tuple[float, str]:
    res = _structured_invoke(
        judge_llm,
        _RelevancySchema,
        _JUDGE_ANSWER_RELEVANCY.format(question=question, answer=answer),
    )
    if res is None:
        return 0.0, "judge unreachable"
    return float(res.score), res.rationale


def judge_context_relevance(
    question: str, contexts: list[str], judge_llm
) -> tuple[float | None, list[str]]:
    """Mean per-chunk relevance over top-k. Returns (mean, per-chunk rationales).
    Returns None when there are no contexts (closed-book/no-retrieval)."""
    if not contexts:
        return None, []
    scores: list[float] = []
    rationales: list[str] = []
    for chunk in contexts:
        res = _structured_invoke(
            judge_llm,
            _ContextRelSchema,
            _JUDGE_CONTEXT_RELEVANCE.format(question=question, chunk=chunk[:3000]),
        )
        if res is None:
            scores.append(0.0)
            rationales.append("judge unreachable")
        else:
            scores.append(float(res.relevant))
            rationales.append(res.rationale)
    return sum(scores) / len(scores), rationales


def judge_correctness(
    answer: str, reference: str, question: str, judge_llm
) -> tuple[float, str]:
    res = _structured_invoke(
        judge_llm,
        _CorrectnessSchema,
        _JUDGE_CORRECTNESS.format(question=question, reference=reference, answer=answer),
    )
    if res is None:
        return 0.0, "judge unreachable"
    return float(res.score), res.rationale


def answer_similarity(answer: str, reference: str, embeddings) -> float:
    """Cosine similarity of OpenAI embeddings — Ragas's `semantic_similarity`."""
    if not answer or not reference:
        return 0.0
    a, b = embeddings.embed_documents([answer, reference])
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def bootstrap_ci(
    values: list[float],
    n_resamples: int = 5000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI. Returns (mean, lo, hi)."""
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int((alpha / 2) * n_resamples)]
    hi = means[int((1 - alpha / 2) * n_resamples) - 1]
    mean = sum(values) / n
    return mean, lo, hi


def paired_wilcoxon(a: list[float], b: list[float]) -> dict:
    """Paired Wilcoxon signed-rank with rank-biserial effect size r.

    Falls back to scipy.stats if available; otherwise computes the basic
    statistic by hand. Returns {stat, p, effect_r, n_nonzero}.
    """
    if len(a) != len(b):
        raise ValueError("paired arrays must be the same length")
    diffs = [x - y for x, y in zip(a, b) if x != y]
    n = len(diffs)
    if n == 0:
        return {"stat": 0.0, "p": 1.0, "effect_r": 0.0, "n_nonzero": 0}

    try:
        from scipy import stats  # type: ignore

        res = stats.wilcoxon(a, b, zero_method="wilcox", alternative="two-sided")
        stat = float(res.statistic)
        p = float(res.pvalue)
    except Exception:  # pragma: no cover — fallback
        # Hand computation: rank |diffs|, sum positive ranks, normal approx.
        abs_diffs = sorted(((abs(d), 1 if d > 0 else -1) for d in diffs))
        ranks = [i + 1 for i, _ in enumerate(abs_diffs)]
        w_pos = sum(r for r, (_, s) in zip(ranks, abs_diffs) if s > 0)
        w_neg = sum(r for r, (_, s) in zip(ranks, abs_diffs) if s < 0)
        stat = float(min(w_pos, w_neg))
        mu = n * (n + 1) / 4
        sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
        z = (stat - mu) / sigma if sigma > 0 else 0.0
        # Two-sided normal-approx p-value.
        p = 2 * 0.5 * math.erfc(abs(z) / math.sqrt(2))

    # Rank-biserial r for paired Wilcoxon (Kerby 2014).
    abs_diffs = sorted(((abs(d), 1 if d > 0 else -1) for d in diffs))
    ranks = [i + 1 for i, _ in enumerate(abs_diffs)]
    w_pos = sum(r for r, (_, s) in zip(ranks, abs_diffs) if s > 0)
    w_neg = sum(r for r, (_, s) in zip(ranks, abs_diffs) if s < 0)
    total = w_pos + w_neg
    effect_r = (w_pos - w_neg) / total if total > 0 else 0.0
    return {"stat": stat, "p": p, "effect_r": effect_r, "n_nonzero": n}


def holm_bonferroni(p_values: list[float]) -> list[float]:
    """Holm step-down adjusted p-values."""
    n = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adj = [0.0] * n
    running_max = 0.0
    for rank, (orig_i, p) in enumerate(indexed):
        candidate = (n - rank) * p
        running_max = max(running_max, candidate)
        adj[orig_i] = min(1.0, running_max)
    return adj


# ---------------------------------------------------------------------------
# JSON cache (cheap protection against re-billing the LLM)
# ---------------------------------------------------------------------------


class JsonCache:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._data: dict[str, Any] = json.load(f)
        else:
            self._data = {}
        self._dirty = False

    def get(self, key: str) -> Any | None:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._dirty = True

    def flush(self) -> None:
        if not self._dirty:
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f)
        tmp.replace(self.path)
        self._dirty = False


# ---------------------------------------------------------------------------
# Convenience: identify which chunk an article maps to, for IR scoring
# ---------------------------------------------------------------------------


def chunk_id_of(doc) -> str:
    return doc.metadata.get("chunk_id") or doc.metadata.get("article_id") or ""


def article_id_of(doc) -> str:
    return doc.metadata.get("article_id") or chunk_id_of(doc).split("::")[0]


def env_check() -> dict[str, bool]:
    """Quick sanity for the notebook's first cell."""
    return {
        "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
        "src_on_path": str(_SRC) in sys.path,
        "corpus_default": (Path(__file__).parent / "en_wikipedia_cs.pkl").exists(),
    }


# ---------------------------------------------------------------------------
# Optional second test set — HotpotQA distractor, intersected with our corpus
# ---------------------------------------------------------------------------
#
# The Wikipedia-CS corpus is great for retrieval but synthesised QA from it is
# at best a proxy for human-authored multi-hop. Real multi-hop benchmarks
# (HotpotQA, MuSiQue, 2WikiMultiHopQA) are human-written and have gold
# supporting-paragraph IDs. We let the user load HotpotQA and filter to the
# subset whose gold article titles intersect our CS corpus, then map each
# question to the chunk(s) whose article matches a gold title.


def _normalise_title(title: str) -> str:
    return re.sub(r"\s+", " ", title or "").strip().lower()


def load_hotpotqa_intersected(
    chunks: list,
    *,
    split: str = "validation",
    config: str = "distractor",
    max_questions: int = 60,
    require_all_gold: bool = True,
    seed: int = 42,
) -> list[QAItem]:
    """Load HotpotQA (default: distractor / validation) and keep questions
    whose gold-supporting articles all appear in our corpus by title.

    Each question's `gold_chunk_id` is set to the FIRST matching chunk for
    the FIRST supporting article; `gold_chunk_ids` carries all matching
    chunks across all supporting articles (so multi-gold IR metrics work).
    """
    from datasets import load_dataset  # local import — datasets is heavy

    title_to_chunks: dict[str, list] = {}
    for c in chunks:
        t = _normalise_title(c.metadata.get("title", ""))
        if t:
            title_to_chunks.setdefault(t, []).append(c)

    ds = load_dataset("hotpotqa/hotpot_qa", config, split=split)
    rng = random.Random(seed)
    indices = list(range(len(ds)))
    rng.shuffle(indices)

    items: list[QAItem] = []
    for idx in indices:
        if len(items) >= max_questions:
            break
        ex = ds[idx]
        sup_titles = {_normalise_title(t) for t in ex["supporting_facts"]["title"]}
        if not sup_titles:
            continue
        if require_all_gold and not sup_titles.issubset(title_to_chunks):
            continue
        if not require_all_gold and not (sup_titles & title_to_chunks.keys()):
            continue
        gold_chunk_ids: list[str] = []
        gold_text_parts: list[str] = []
        for t in sup_titles:
            for c in title_to_chunks.get(t, []):
                gold_chunk_ids.append(c.metadata["chunk_id"])
                gold_text_parts.append(c.page_content)
        if not gold_chunk_ids:
            continue
        # Multi-hop if we have ≥2 supporting articles, else single-hop.
        category = (
            "hotpotqa_multi_hop" if len(sup_titles) >= 2 else "hotpotqa_single_hop"
        )
        items.append(
            QAItem(
                qid=f"hp_{idx:06d}",
                question=ex["question"],
                answer=ex["answer"],
                gold_chunk_id=gold_chunk_ids[0],
                gold_chunk_ids=gold_chunk_ids,
                gold_chunk_text="\n\n---\n\n".join(gold_text_parts)[:6000],
                category=category,
            )
        )
    return items


def ir_metrics_at_k(retrieved_ids: list[str], gold_ids: set[str], k: int) -> dict:
    """Compute Hit@k, Recall@k, Precision@k, MRR@k, nDCG@k in one call.

    Returns a dict with keys f"hit@{k}", f"recall@{k}", f"precision@{k}",
    f"mrr@{k}", f"ndcg@{k}". This is the BEIR-style reporting convention
    [Thakur et al., NeurIPS 2021] — usually report @5 (production top-k)
    AND @10 (BEIR leaderboard convention) so numbers are comparable.
    """
    top = retrieved_ids[:k]
    first_gold_rank = next(
        (i + 1 for i, r in enumerate(top) if r in gold_ids), 0
    )
    return {
        f"hit@{k}":       1.0 if first_gold_rank > 0 else 0.0,
        f"recall@{k}":    recall_at_k(retrieved_ids, gold_ids, k),
        f"precision@{k}": precision_at_k(retrieved_ids, gold_ids, k),
        f"mrr@{k}":       (1.0 / first_gold_rank) if first_gold_rank > 0 else 0.0,
        f"ndcg@{k}":      ndcg_at_k(retrieved_ids, gold_ids, k),
    }


def two_judge_consistency(
    items: list,
    primary_judge,
    alternative_judge,
    *,
    metric: str = "correctness",
    sample_size: int = 10,
    seed: int = 42,
) -> dict:
    """Re-judge a random `sample_size` slice of `items` (each must have
    `question`, `answer`, `reference`) with `alternative_judge` and report
    inter-judge agreement.

    Returns a dict with the per-item primary/alternative scores, plus
    aggregate Pearson/Spearman correlation and mean absolute disagreement
    — the protocol from Zheng et al., NeurIPS 2023 [11] §4 for bounding
    self-enhancement bias.

    `metric` selects which judge function to compare; default `correctness`.
    Supports: `correctness`, `answer_relevancy`, `faithfulness`.
    """
    rng = random.Random(seed)
    pool = list(items)
    rng.shuffle(pool)
    sample = pool[: min(sample_size, len(pool))]

    judge_fn = {
        "correctness": lambda j, it: judge_correctness(
            it["answer"], it["reference"], it["question"], j
        )[0],
        "answer_relevancy": lambda j, it: judge_answer_relevancy(
            it["answer"], it["question"], j
        )[0],
        "faithfulness": lambda j, it: judge_faithfulness(
            it["answer"], it.get("contexts", []), j
        )[0],
    }
    if metric not in judge_fn:
        raise ValueError(f"unsupported metric: {metric}")

    rows = []
    for it in sample:
        p = judge_fn[metric](primary_judge, it)
        a = judge_fn[metric](alternative_judge, it)
        if p is None or a is None:
            continue
        rows.append({"primary": float(p), "alternative": float(a), **it})

    if not rows:
        return {"rows": [], "n": 0}

    primary = [r["primary"] for r in rows]
    alt = [r["alternative"] for r in rows]
    n = len(rows)
    mean_p = sum(primary) / n
    mean_a = sum(alt) / n
    var_p = sum((x - mean_p) ** 2 for x in primary)
    var_a = sum((x - mean_a) ** 2 for x in alt)
    cov = sum((x - mean_p) * (y - mean_a) for x, y in zip(primary, alt))
    pearson = cov / math.sqrt(var_p * var_a) if var_p * var_a > 0 else 0.0

    # Spearman: correlation of ranks.
    def _ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        ranks = [0.0] * len(xs)
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    rp, ra = _ranks(primary), _ranks(alt)
    mp, ma_ = sum(rp) / n, sum(ra) / n
    vp = sum((x - mp) ** 2 for x in rp)
    va = sum((x - ma_) ** 2 for x in ra)
    cv = sum((x - mp) * (y - ma_) for x, y in zip(rp, ra))
    spearman = cv / math.sqrt(vp * va) if vp * va > 0 else 0.0

    mad = sum(abs(p - a) for p, a in zip(primary, alt)) / n

    return {
        "rows": rows,
        "n": n,
        "primary_mean": mean_p,
        "alternative_mean": mean_a,
        "pearson": pearson,
        "spearman": spearman,
        "mean_abs_disagreement": mad,
    }


def random_distractor_contexts(
    chunks: list, gold_ids: set[str], k: int = 5, seed: int = 42
) -> list[str]:
    """Counterfactual-noise contexts: k random chunks that are NOT in gold_ids.

    Used for the contamination diagnostic — feed these as the retrieved
    context. If Answer Correctness barely drops, the model is bypassing
    retrieval.
    """
    rng = random.Random(seed)
    pool = [c for c in chunks if chunk_id_of(c) not in gold_ids]
    rng.shuffle(pool)
    return [c.page_content for c in pool[:k]]
