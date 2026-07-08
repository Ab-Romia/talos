# RAG Retrieval-Quality Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix weak @ai answers (root cause: element-level chunk fragmentation + MiniLM embeddings + shallow rerank pool) via section-aware chunking, a bge-small embedding swap, and eval-tuned retrieval defaults — every change validated on a real-substrate ablation before it ships.

**Architecture:** Track D first builds a judged question set over the live PDF (the workspace guide) and an ablation runner that drives the PRODUCTION chunking + retrieval code (eval == ship). Tracks A (chunk_by_title hygiene) and B (bge-small-en-v1.5) land as config-gated code, OFF by default. The ablation then picks winners; Track C flips defaults, re-ingests the live corpus, and smokes the original failing query. Evidence base: `docs/audits/2026-07-02-rag-retrieval-quality-findings.md`.

**Tech Stack:** Python 3.14 (uv venv), unstructured (`chunk_by_title`), langchain (HuggingFaceEmbeddings / HuggingFaceBgeEmbeddings from langchain_community), Milvus, OpenRouter (generation `openai/gpt-4o-mini`, judge `openai/gpt-4o`), existing eval harness `tests/rag_evaluation/eval_utils.py`.

## Global Constraints

- Branch: `feature/chat-message-memory` in `/home/romia/talos-main`. NEVER commit to `main`.
- NEVER touch teammates' code: `src/backend/auth/**`, `src/chat/router.py`, `src/chat/realtime.py`, `src/workspace/**`, `src/filesystem/**`. (Note: `src/chat/model.py` and `src/chat/realtime.py` currently have uncommitted modifications in the worktree — leave them exactly as they are; do not stage, revert, or commit them.)
- NO AI attribution anywhere: no `Co-Authored-By`, no AI session links, no AI references in commits/code/docs. Author = Ab-Romia <aabouroumia@gmail.com>.
- All imports relative to `src/` (PYTHONPATH=src). Scripts run as `PYTHONPATH=src uv run python <script>` from `/home/romia/talos-main`.
- Tests: `IS_TEST=1 uv run python -m pytest tests/rag -q` (NOT bare `pytest`; needs `docker compose up -d postgres-test` once). Full gate before each commit: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`.
- OpenRouter: `OPENROUTER_API_KEY` is in `/home/romia/gp_artifact/.env` (NOT in talos-main). Load it explicitly; never print or commit it.
- Eval == ship: the ablation must import the production chunking function and `build_rag_pipeline` — no reimplemented retrieval.
- Simplicity / YAGNI: no new dependencies, no new services, smallest change that the eval can validate.
- Milvus store is LIVE and shared — eval uses `InMemoryVectorStore` only; nothing in Tasks 1–5 may write to Milvus. Only Task 6 (re-ingest) touches Milvus, deliberately.
- Eval artifacts >1MB (results JSON, caches) go under `evaluation/live_pdf_eval/results/` and get a `.gitignore` for caches; commit summary JSON + report, not raw caches.

## File Structure

- `evaluation/live_pdf_eval/gen_questions.py` — question-set builder (Task 1)
- `evaluation/live_pdf_eval/questions.json` — ~60 judged Q/A/gold-pages items (Task 1)
- `evaluation/live_pdf_eval/common.py` — OpenRouter clients, boilerplate classifier, page metrics (Task 1, extended Task 4)
- `src/processing/documents.py` — chunk hygiene: element filtering + `chunk_by_title` path (Task 2)
- `src/config/config.py` — `chunk_prepend_section_title` flag; later default flips (Tasks 2, 6)
- `src/rag/vector_store.py` — HF embedder honors config, bge support, dim assert (Task 3)
- `tests/rag/test_chunking.py`, `tests/rag/test_embeddings_selection.py` — new tests (Tasks 2–3)
- `evaluation/live_pdf_eval/run_ablation.py` — retrieval sweep + judged end-to-end arms (Task 4)
- `evaluation/live_pdf_eval/results/` + `REPORT.md` — run outputs (Task 5)
- `scripts/reingest_workspace_files.py` — live corpus re-ingest + chat-vector reset (Task 6)

---

### Task 1: Live-PDF question set (Track D, part 1)

**Files:**
- Create: `evaluation/live_pdf_eval/common.py`
- Create: `evaluation/live_pdf_eval/gen_questions.py`
- Create: `evaluation/live_pdf_eval/questions.json` (generated artifact, committed)
- Create: `evaluation/live_pdf_eval/.gitignore` (content: `results/cache/`)

**Interfaces:**
- Consumes: `/home/romia/Downloads/the workspace guide PDF` (verified present), `OPENROUTER_API_KEY` from `/home/romia/gp_artifact/.env`.
- Produces: `questions.json` — list of `{"id": "q001", "question": str, "reference_answer": str, "gold_pages": [int, ...], "source_window": [int, int]}`; `common.py` exports `openrouter_chat(model: str, temperature: float = 0.0) -> ChatOpenAI`, `load_questions(path) -> list[dict]`, `pdf_pages(pdf_path) -> dict[int, str]`.

- [ ] **Step 1: Write `common.py`**

```python
"""Shared helpers for the live-PDF retrieval ablation."""
import json
import os
from pathlib import Path

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
GEN_MODEL = "openai/gpt-4o-mini"      # matches the live strong profile
JUDGE_MODEL = "openai/gpt-4o"
PDF_PATH = "/home/romia/Downloads/the workspace guide PDF"
QUESTIONS_PATH = Path(__file__).parent / "questions.json"


def _load_openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env_file = Path("/home/romia/gp_artifact/.env")
    for line in env_file.read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("OPENROUTER_API_KEY not found in env or /home/romia/gp_artifact/.env")


def openrouter_chat(model: str, temperature: float = 0.0):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url=OPENROUTER_BASE,
        api_key=_load_openrouter_key(),
        timeout=120,
        max_retries=3,
    )


def pdf_pages(pdf_path: str = PDF_PATH) -> dict[int, str]:
    """Page-number → concatenated element text, via the same partitioner prod uses."""
    from unstructured.partition.auto import partition
    pages: dict[int, list[str]] = {}
    for el in partition(filename=pdf_path, strategy="fast"):
        if not getattr(el, "text", None):
            continue
        page = getattr(el.metadata, "page_number", 0) or 0
        pages.setdefault(page, []).append(el.text)
    return {p: "\n".join(parts) for p, parts in sorted(pages.items())}


def load_questions(path=QUESTIONS_PATH) -> list[dict]:
    return json.loads(Path(path).read_text())


# --- boilerplate classifier (ported from the 2026-07-02 live-corpus probe) ---
import re

_PAGE_NUM_RE = re.compile(r"^\s*(page\s+)?\d{1,4}\s*$", re.IGNORECASE)


def is_boilerplate(text: str) -> bool:
    t = text.strip()
    words = t.split()
    if _PAGE_NUM_RE.match(t):
        return True                                   # bare page number
    if len(words) <= 3 and len(t) <= 40:
        return True                                   # bare heading/label fragment
    if len(words) <= 6 and t.upper() == t and any(c.isalpha() for c in t):
        return True                                   # short all-caps heading
    if len(words) <= 10:
        non_alpha = sum(1 for c in t if not (c.isalpha() or c.isspace()))
        if non_alpha / max(len(t), 1) > 0.40:
            return True                               # symbol-heavy fragment
    if "...." in t or "table of contents" in t.lower():
        return True                                   # TOC leaders
    return False
```

- [ ] **Step 2: Write `gen_questions.py`**

```python
"""Generate a judged question set over the workspace guide PDF.

Two passes: (1) a strong model authors realistic questions per 8-page window,
under a paraphrase constraint so questions don't lexically copy the doc
(avoids the v6 leaky-wash trap); (2) a judge verifies each question is
answerable SOLELY from its gold pages and self-contained. Near-duplicate
questions are dropped via embedding cosine.
"""
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent))
from common import GEN_MODEL, JUDGE_MODEL, QUESTIONS_PATH, openrouter_chat, pdf_pages

WINDOW = 8            # pages per authoring window
PER_WINDOW = 6        # questions requested per window
TARGET_MIN = 60       # minimum accepted questions


class _QA(BaseModel):
    question: str = Field(description="A realistic user question, paraphrased — reuse NO distinctive phrase of 4+ consecutive words from the text")
    reference_answer: str = Field(description="Correct answer in <=80 words, grounded only in the given pages")
    gold_pages: list[int] = Field(description="The page numbers (from the provided page markers) that contain the answer")


class _QAList(BaseModel):
    items: list[_QA]


class _Review(BaseModel):
    answerable_from_pages: bool
    self_contained: bool


AUTHOR_PROMPT = """You are building a retrieval-evaluation set for an interview-preparation guide.
Below are pages {lo}-{hi} of the guide, each preceded by a marker like [PAGE 12].

Write {n} questions a real user preparing for interviews would ask an assistant
that has this guide as its knowledge base. Rules:
- Each question must be answerable from these pages alone.
- PARAPHRASE: do not reuse any distinctive phrase of 4+ consecutive words from the text.
- Mix granularities: some about specific advice/numbers, some "summarize the steps for X".
- gold_pages must list the exact page number(s) containing the answer.

{pages_text}"""

REVIEW_PROMPT = """Question: {question}
Claimed answer: {answer}
Pages that supposedly contain the answer:
{pages_text}

Judge strictly: (1) Is the question fully answerable from ONLY these pages?
(2) Is the question self-contained (understandable without seeing the pages)?"""


def main() -> None:
    pages = pdf_pages()
    author = openrouter_chat(JUDGE_MODEL, temperature=0.7).with_structured_output(_QAList)
    reviewer = openrouter_chat(JUDGE_MODEL).with_structured_output(_Review)

    page_nums = sorted(pages)
    raw: list[dict] = []
    for i in range(0, len(page_nums), WINDOW):
        win = page_nums[i : i + WINDOW]
        pages_text = "\n\n".join(f"[PAGE {p}]\n{pages[p]}" for p in win)
        out = author.invoke(AUTHOR_PROMPT.format(lo=win[0], hi=win[-1], n=PER_WINDOW, pages_text=pages_text))
        for qa in out.items:
            gold = [p for p in qa.gold_pages if p in win]
            if gold:
                raw.append({"question": qa.question, "reference_answer": qa.reference_answer,
                            "gold_pages": gold, "source_window": [win[0], win[-1]]})
        print(f"window {win[0]}-{win[-1]}: {len(raw)} raw so far", flush=True)

    kept: list[dict] = []
    for item in raw:
        pages_text = "\n\n".join(f"[PAGE {p}]\n{pages[p]}" for p in item["gold_pages"])
        verdict = reviewer.invoke(REVIEW_PROMPT.format(
            question=item["question"], answer=item["reference_answer"], pages_text=pages_text))
        if verdict.answerable_from_pages and verdict.self_contained:
            kept.append(item)
    print(f"review kept {len(kept)}/{len(raw)}")

    # near-duplicate drop (cosine > 0.90 on MiniLM — dedupe only, not eval-critical)
    from langchain_huggingface import HuggingFaceEmbeddings
    emb = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vecs = emb.embed_documents([k["question"] for k in kept])
    import numpy as np
    V = np.array(vecs); V = V / np.linalg.norm(V, axis=1, keepdims=True)
    S = V @ V.T
    deduped: list[dict] = []
    for i, item in enumerate(kept):
        if any(S[i, j] > 0.90 for j in range(i) if kept[j].get("_kept")):
            continue
        item["_kept"] = True
        deduped.append(item)
    for i, item in enumerate(deduped):
        item.pop("_kept", None)
        item["id"] = f"q{i + 1:03d}"

    if len(deduped) < TARGET_MIN:
        print(f"WARNING: only {len(deduped)} questions (< {TARGET_MIN}) — inspect quality before proceeding")
    QUESTIONS_PATH.write_text(json.dumps(deduped, indent=2))
    print(f"wrote {len(deduped)} questions -> {QUESTIONS_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the generator**

Run: `cd /home/romia/talos-main && CUDA_VISIBLE_DEVICES="" PYTHONPATH=src uv run python evaluation/live_pdf_eval/gen_questions.py`
Expected: progress lines per window, `review kept N/M`, final `wrote N questions` with N ≥ 60. Cost: ~76 pages authored + ~90 reviews on gpt-4o ≈ low single-digit dollars.

- [ ] **Step 4: Manual quality gate**

Print 10 random items (`PYTHONPATH=src uv run python -c "import json,random; qs=json.load(open('evaluation/live_pdf_eval/questions.json')); [print(q['id'], q['gold_pages'], '—', q['question']) for q in random.sample(qs, 10)]"`). Check: questions read like real user asks, gold_pages plausible, no verbatim copying. **STOP and show the sample to the user if anything looks off.**

- [ ] **Step 5: Commit**

```bash
git add evaluation/live_pdf_eval/
git commit -m "eval(rag): judged question set + shared helpers for live-PDF retrieval ablation"
```

---

### Task 2: Section-aware chunk hygiene in production ingestion (Track A)

**Files:**
- Modify: `src/processing/documents.py` (functions around lines 34–120)
- Modify: `src/config/config.py` (RagConfig, near `chunking_strategy` at line ~51)
- Test: `tests/rag/test_chunking.py` (create)

**Interfaces:**
- Consumes: `global_rag_config` (`chunk_size`, `chunk_overlap`, `chunking_strategy`, new `chunk_prepend_section_title`).
- Produces: `build_chunk_documents(elements, *, base_metadata: dict, config) -> list[Document]` in `src/processing/documents.py` — the SINGLE chunking entrypoint. `elements` = unstructured Element objects; returns final chunk Documents (no `chunk_index`; caller adds it). Also `_partition_elements(file_path: str) -> list` (raises ImportError if unstructured missing). Task 4's runner imports both — names must match exactly.
- Behavior contract: `chunking_strategy == "recursive"` reproduces today's output byte-for-byte (ablation baseline arm). `"by_title"` = drop noise categories (`Header`, `Footer`, `PageBreak`, `Image`) → `chunk_by_title(max_characters=chunk_size, new_after_n_chars=min(800, chunk_size), combine_text_under_n_chars=200, multipage_sections=True, include_orig_elements=True)` → one Document per composite chunk with `page_number` + `section` metadata; if `config.chunk_prepend_section_title`, page_content becomes `f"[{section}]\n{text}"`.

- [ ] **Step 1: Add the config flag**

In `src/config/config.py`, directly under `chunking_strategy: str = "recursive"` (~line 51):

```python
    # "by_title" only: prepend the active section heading to each chunk's text
    # before embedding ("[Section]\ntext"). Cheap contextual anchor; ablated in
    # evaluation/live_pdf_eval before any default flip.
    chunk_prepend_section_title: bool = False
```

- [ ] **Step 2: Write the failing tests**

`tests/rag/test_chunking.py`:

```python
"""Chunking hygiene: element filtering + section-aware chunk_by_title path."""
import pytest
from unstructured.documents.elements import (
    ElementMetadata, Footer, Header, NarrativeText, Title,
)

from config import RagConfig
from processing.documents import build_chunk_documents

BASE_META = {"workspace_id": "ws1", "file_id": "f1", "filename": "guide.pdf"}


def _el(cls, text, page=1):
    el = cls(text=text)
    el.metadata = ElementMetadata(page_number=page)
    return el


@pytest.fixture
def elements():
    return [
        _el(Header, "ACME GUIDE — CONFIDENTIAL", page=1),
        _el(Title, "System Design", page=1),
        _el(NarrativeText, "Do one hard system design question per day. " * 5, page=1),
        _el(NarrativeText, "Use mock interviews to practice articulating tradeoffs. " * 5, page=2),
        _el(Title, "Behavioral", page=3),
        _el(NarrativeText, "Prepare STAR stories for your five biggest projects. " * 5, page=3),
        _el(Footer, "page 3", page=3),
    ]


def test_by_title_drops_header_and_footer(elements):
    cfg = RagConfig(chunking_strategy="by_title")
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    joined = " ".join(d.page_content for d in docs)
    assert "CONFIDENTIAL" not in joined
    assert "page 3" not in joined


def test_by_title_merges_fragments_and_keeps_section_metadata(elements):
    cfg = RagConfig(chunking_strategy="by_title")
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    # no bare-title fragment chunks: every chunk carries real prose
    assert all(len(d.page_content) > 60 for d in docs)
    sections = {d.metadata.get("section") for d in docs}
    assert "System Design" in sections and "Behavioral" in sections
    assert all(d.metadata["workspace_id"] == "ws1" for d in docs)
    assert all(isinstance(d.metadata.get("page_number"), int) for d in docs)


def test_by_title_respects_max_characters(elements):
    cfg = RagConfig(chunking_strategy="by_title", chunk_size=1000)
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    assert all(len(d.page_content) <= 1000 for d in docs)


def test_prepend_section_title_flag(elements):
    cfg = RagConfig(chunking_strategy="by_title", chunk_prepend_section_title=True)
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    sys_docs = [d for d in docs if d.metadata.get("section") == "System Design"]
    assert sys_docs and all(d.page_content.startswith("[System Design]\n") for d in sys_docs)


def test_recursive_strategy_preserves_legacy_behavior(elements):
    """recursive = today's pipeline: one doc per element (incl. Header/Footer), split >1000."""
    cfg = RagConfig(chunking_strategy="recursive")
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    joined = " ".join(d.page_content for d in docs)
    assert "CONFIDENTIAL" in joined            # legacy keeps noise (baseline arm fidelity)
    assert any(d.page_content == "System Design" for d in docs)  # bare title fragment survives
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_chunking.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_chunk_documents'`.

- [ ] **Step 4: Implement in `src/processing/documents.py`**

Replace `_extract_text` usage in `process_file` and add the new functions. The diff, precisely:

(a) Add near the top of the module (after existing imports):

```python
# Element categories that are retrieval noise: running headers/footers, page
# breaks, images. Dropped ONLY on the "by_title" path so "recursive" stays a
# faithful reproduction of the legacy corpus for the ablation baseline.
_NOISE_CATEGORIES = {"Header", "Footer", "PageBreak", "Image"}


def _partition_elements(file_path: str) -> list:
    """Partition a file into unstructured elements. Raises ImportError when
    unstructured is unavailable (caller falls back to plain-text extraction)."""
    from unstructured.partition.auto import partition
    return partition(filename=file_path, strategy="fast")


def _section_title_of(chunk) -> str | None:
    for el in getattr(chunk.metadata, "orig_elements", None) or []:
        if el.category == "Title" and (el.text or "").strip():
            return el.text.strip()
    return None


def build_chunk_documents(elements: list, *, base_metadata: dict, config=None) -> list[Document]:
    """Single chunking entrypoint: unstructured elements -> retrieval-ready Documents.

    strategy "recursive" (legacy): one Document per element, RecursiveCharacterTextSplitter
    splits oversized ones — it never merges, so short elements stay fragments.
    strategy "by_title": noise elements dropped, sections packed/merged by
    chunk_by_title, section title carried in metadata (optionally prepended).
    """
    cfg = config if config is not None else global_rag_config

    if cfg.chunking_strategy == "by_title":
        from unstructured.chunking.title import chunk_by_title
        kept = [
            el for el in elements
            if el.category not in _NOISE_CATEGORIES and (getattr(el, "text", "") or "").strip()
        ]
        chunks = chunk_by_title(
            kept,
            max_characters=cfg.chunk_size,
            new_after_n_chars=min(800, cfg.chunk_size),
            combine_text_under_n_chars=200,
            multipage_sections=True,
            include_orig_elements=True,
        )
        docs = []
        for chunk in chunks:
            section = _section_title_of(chunk)
            text = chunk.text
            if cfg.chunk_prepend_section_title and section:
                text = f"[{section}]\n{text}"
            docs.append(Document(
                page_content=text,
                metadata={
                    **base_metadata,
                    "page_number": getattr(chunk.metadata, "page_number", 0) or 0,
                    "section": section or "",
                },
            ))
        return docs

    # legacy path — must reproduce the pre-2026-07 corpus exactly
    docs = [
        Document(
            page_content=el.text,
            metadata={
                **base_metadata,
                "page_number": (getattr(el.metadata, "page_number", 0) or 0) if hasattr(el, "metadata") else 0,
            },
        )
        for el in elements
        if getattr(el, "text", None) and el.text.strip()
    ]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg.chunk_size,
        chunk_overlap=cfg.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(docs)
```

(b) In `process_file`, replace the element-extraction + doc-building + splitting block (current lines 34–64: `elements = _extract_text(...)` through `chunks = splitter.split_documents(docs)`) with:

```python
        base_metadata = {
            "workspace_id": str(file_record.workspace_id),
            "file_id": str(file_record.id),
            "filename": file_record.filename,
        }
        try:
            elements = _partition_elements(tmp_path)
            chunks = build_chunk_documents(elements, base_metadata=base_metadata)
        except ImportError:
            logger.warning("unstructured not installed, using fallback text extraction")
            docs = [
                Document(page_content=text, metadata={**base_metadata, "page_number": meta.get("page_number", 0)})
                for text, meta in _fallback_extract(tmp_path, file_record.content_type)
                if text and text.strip()
            ]
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=global_rag_config.chunk_size,
                chunk_overlap=global_rag_config.chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
            )
            chunks = splitter.split_documents(docs)

        if not chunks:
            logger.warning("No text extracted from document", file_id=str(file_record.id))
            file_record.chunk_count = 0  # not a mapped column yet — silently dropped (reported to filesystem owner)
            db.commit()
            return
```

Keep the rest of the function (chunk_index loop, delete_file_chunks, ingest, logging) unchanged, except: in the final `logger.info("Document chunked and ingested", ...)` call, delete the `num_raw_elements=len(docs)` kwarg (`docs` no longer exists on the main path); keep `num_chunks=len(chunks)`. Delete the now-unused `_extract_text` function (`_fallback_extract` stays).

- [ ] **Step 5: Run tests to verify they pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_chunking.py -q`
Expected: 5 passed.

- [ ] **Step 6: Full suite + commit**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q` — expected: all pass (previously 68+).

```bash
git add src/processing/documents.py src/config/config.py tests/rag/test_chunking.py
git commit -m "feat(rag): section-aware by_title chunking with noise-element filtering, config-gated (default unchanged)"
```

---

### Task 3: Embedding selection honors config + bge support + dim assert (Track B)

**Files:**
- Modify: `src/rag/vector_store.py:85-103` (`_build_embeddings`, `get_embeddings`) and `get_workspace_vectorstore` (~line 155)
- Test: `tests/rag/test_embeddings_selection.py` (create)

**Interfaces:**
- Consumes: `RagConfig.embedding_provider`, `RagConfig.embedding_model`.
- Produces: `_hf_embeddings_for(model: str) -> Embeddings` (module-level, monkeypatchable); huggingface branch of `_build_embeddings` returns `_hf_embeddings_for(model)`; `BGE_QUERY_INSTRUCTION` constant; `_assert_collection_dim(collection_name: str, embeddings) -> None` called from `get_workspace_vectorstore` when it builds the default embedder. Task 4/6 set `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5` + `EMBEDDING_PROVIDER=huggingface` and get a correctly-prefixed bge embedder.

- [ ] **Step 1: Write the failing tests**

`tests/rag/test_embeddings_selection.py`:

```python
"""HF embedder selection: honor config.embedding_model; bge gets query instruction."""
import pytest

import rag.vector_store as vs


class _FakeEmb:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_hf_branch_honors_model_name(monkeypatch):
    captured = {}
    monkeypatch.setattr(vs, "HuggingFaceEmbeddings", lambda **kw: captured.update(kw) or _FakeEmb(**kw))
    vs._build_embeddings.cache_clear()
    vs._build_embeddings("huggingface", "thenlper/gte-small", None)
    assert captured["model_name"] == "thenlper/gte-small"


def test_bge_model_gets_query_instruction(monkeypatch):
    captured = {}

    class _FakeBge(_FakeEmb):
        def __init__(self, **kw):
            captured.update(kw)
            super().__init__(**kw)

    monkeypatch.setattr(vs, "_bge_embeddings_cls", lambda: _FakeBge)
    vs._build_embeddings.cache_clear()
    vs._build_embeddings("huggingface", "BAAI/bge-small-en-v1.5", None)
    assert captured["model_name"] == "BAAI/bge-small-en-v1.5"
    assert captured["query_instruction"] == vs.BGE_QUERY_INSTRUCTION
    assert captured["encode_kwargs"] == {"normalize_embeddings": True}


def test_unknown_provider_still_raises():
    vs._build_embeddings.cache_clear()
    with pytest.raises(ValueError):
        vs._build_embeddings("nope", "x", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_embeddings_selection.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_bge_embeddings_cls'` / wrong model_name (hardcoded MiniLM).

- [ ] **Step 3: Implement in `src/rag/vector_store.py`**

Replace `_build_embeddings` (lines 85–97) with:

```python
# bge-en-v1.5 retrieval instruction (query side only) — per the BAAI model card.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def _bge_embeddings_cls():
    from langchain_community.embeddings import HuggingFaceBgeEmbeddings
    return HuggingFaceBgeEmbeddings


def _hf_embeddings_for(model: str) -> Embeddings:
    """HF embedder for the configured model. bge-en models need the query-side
    instruction prefix or retrieval quality silently degrades."""
    if "bge-" in model:
        return _bge_embeddings_cls()(
            model_name=model,
            query_instruction=BGE_QUERY_INSTRUCTION,
            encode_kwargs={"normalize_embeddings": True},
        )
    return HuggingFaceEmbeddings(model_name=model)


@lru_cache(maxsize=None)
def _build_embeddings(provider: str, model: str, api_key: str | None) -> Embeddings:
    # Cached: constructing the embedder (esp. the HuggingFace sentence-transformer)
    # loads the model from disk and costs ~3.5s — otherwise paid on every query.
    # Keyed on (provider, model) so two different models don't collide.
    if provider == "openai":
        return OpenAIEmbeddings(model=model, api_key=api_key)
    elif provider == "huggingface":
        return _hf_embeddings_for(model)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
```

Then add the dim assert and wire it into `get_workspace_vectorstore`:

```python
@lru_cache(maxsize=None)
def _assert_collection_dim(collection_name: str, provider: str, model: str) -> None:
    """Fail fast if the configured embedder's dimension doesn't match the live
    collection (e.g. env lost EMBEDDING_PROVIDER and fell back to OpenAI/1536
    against a 384-dim corpus). Cached: one probe embedding per process."""
    _ensure_milvus_connection()
    if not utility.has_collection(collection_name):
        return
    field = next((f for f in Collection(collection_name).schema.fields if f.name == "vector"), None)
    if field is None:
        return
    coll_dim = field.params.get("dim")
    emb_dim = len(get_embeddings(provider).embed_query("dimension probe"))
    if coll_dim is not None and emb_dim != int(coll_dim):
        raise RuntimeError(
            f"Embedding dim mismatch: {provider}/{model} produces {emb_dim}-dim vectors "
            f"but collection '{collection_name}' is {coll_dim}-dim. Fix EMBEDDING_* env "
            f"or re-ingest the collection."
        )
```

In `get_workspace_vectorstore`, inside the `if embeddings is None:` branch (line ~165), after `embeddings = get_embeddings(embedding_provider)` add:

```python
        _assert_collection_dim(
            collection_name,
            embedding_provider or global_rag_config.embedding_provider,
            global_rag_config.embedding_model,
        )
```

(Callers that inject `embeddings=` — HyDE, eval — skip the check by design.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_embeddings_selection.py tests/rag -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/rag/vector_store.py tests/rag/test_embeddings_selection.py
git commit -m "feat(rag): huggingface embedder honors embedding_model, bge query instruction, collection dim assert"
```

---

### Task 4: Ablation runner on the real substrate (Track D, part 2)

**Files:**
- Create: `evaluation/live_pdf_eval/run_ablation.py`
- Modify: `evaluation/live_pdf_eval/common.py` (add metric helpers)

**Interfaces:**
- Consumes: `questions.json` (Task 1), `build_chunk_documents`/`_partition_elements` (Task 2), `_hf_embeddings_for` via `_build_embeddings` (Task 3), production `build_rag_pipeline` (`rag.retrieval.retrievers`), `RAG_PROMPT` (`config.prompts`), `judge_correctness` + `paired_wilcoxon` + `holm_bonferroni` + `JsonCache` (`tests/rag_evaluation/eval_utils.py`).
- Produces: `results/retrieval_sweep.json` (per-arm per-question retrieval metrics), `results/judged_arms.json` (per-arm per-question correctness), console summary tables. NO Milvus writes: vector stores are `langchain_core.vectorstores.InMemoryVectorStore`.

- [ ] **Step 1: Add metric helpers to `common.py`**

Append:

```python
def page_recall_at_k(retrieved_docs, gold_pages: set[int], k: int) -> float:
    got = {int(d.metadata.get("page_number", -1)) for d in retrieved_docs[:k]}
    return len(got & gold_pages) / len(gold_pages) if gold_pages else 0.0


def first_gold_rank(retrieved_docs, gold_pages: set[int]) -> int | None:
    """1-based rank of the first chunk on a gold page; None if absent."""
    for i, d in enumerate(retrieved_docs):
        if int(d.metadata.get("page_number", -1)) in gold_pages:
            return i + 1
    return None


def boilerplate_rate(retrieved_docs, k: int) -> float:
    top = retrieved_docs[:k]
    return sum(1 for d in top if is_boilerplate(d.page_content)) / max(len(top), 1)
```

- [ ] **Step 2: Write `run_ablation.py`**

```python
"""Retrieval ablation on the REAL substrate (the workspace guide PDF).

Phase 1 (CPU-only, free): full retrieval sweep —
  chunking {recursive, by_title, by_title_prefix} x embedder {minilm, bge}
  x rerank {off, on(fetch_k in 20/50/100)} x top_k {5, 10}
Metrics per question: page_recall@top_k, first_gold_rank (wide k=100 dense,
burial diagnosis), boilerplate_rate@top_k.

Phase 2 (OpenRouter, judged): 4 arms end-to-end through the production
RAGChain-equivalent (build_rag_pipeline + RAG_PROMPT), gpt-4o-mini generation,
gpt-4o correctness judge vs the reference answer. Paired stats.

Eval == ship: chunking and retrieval are the production functions; the only
substitution is InMemoryVectorStore for Milvus (same cosine geometry; the
vector backend is not under test). Run:
  CUDA_VISIBLE_DEVICES="" PYTHONPATH=src:tests uv run python evaluation/live_pdf_eval/run_ablation.py [--phase 1|2] [--limit N]
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from common import (GEN_MODEL, JUDGE_MODEL, PDF_PATH, boilerplate_rate,
                    first_gold_rank, load_questions, openrouter_chat,
                    page_recall_at_k)

RESULTS = HERE / "results"
CHUNKINGS = ["recursive", "by_title", "by_title_prefix"]
EMBEDDERS = {"minilm": "sentence-transformers/all-MiniLM-L6-v2",
             "bge": "BAAI/bge-small-en-v1.5"}
FETCH_KS = [20, 50, 100]
TOP_KS = [5, 10]
BASE_META = {"workspace_id": "eval", "file_id": "eval", "filename": "the workspace guide PDF"}


def rag_config(chunking: str):
    from config import RagConfig
    strategy = "by_title" if chunking.startswith("by_title") else "recursive"
    return RagConfig(chunking_strategy=strategy,
                     chunk_prepend_section_title=chunking == "by_title_prefix")


def build_corpus(elements, chunking: str):
    from processing.documents import build_chunk_documents
    return build_chunk_documents(elements, base_metadata=BASE_META, config=rag_config(chunking))


def build_store(chunks, embedder_key: str):
    from langchain_core.vectorstores import InMemoryVectorStore
    from rag.vector_store import _build_embeddings
    emb = _build_embeddings("huggingface", EMBEDDERS[embedder_key], None)
    return InMemoryVectorStore.from_documents(chunks, embedding=emb)


def retriever_for(store, *, top_k, use_rerank, fetch_k):
    from config import RagConfig
    from rag.retrieval.retrievers import build_rag_pipeline
    cfg = RagConfig(retrieval_top_k=top_k, use_reranking=use_rerank,
                    rerank_fetch_k=fetch_k, use_hyde=False, use_query_rewrite=False,
                    use_hybrid_retrieval=False)
    return build_rag_pipeline(cfg, store, corpus=None)


def phase1(questions):
    from unstructured.partition.auto import partition
    elements = partition(filename=PDF_PATH, strategy="fast")
    rows = []
    for chunking in CHUNKINGS:
        chunks = build_corpus(elements, chunking)
        print(f"[{chunking}] {len(chunks)} chunks, "
              f"median len {sorted(len(c.page_content) for c in chunks)[len(chunks)//2]}")
        for emb_key in EMBEDDERS:
            store = build_store(chunks, emb_key)
            # wide-k dense ranking once per question (burial diagnosis, rerank-free)
            wide = {q["id"]: store.similarity_search(q["question"], k=100) for q in questions}
            arms = [(False, 0, k) for k in TOP_KS] + [
                (True, f, k) for f, k in itertools.product(FETCH_KS, TOP_KS)]
            for use_rerank, fetch_k, top_k in arms:
                ret = retriever_for(store, top_k=top_k,
                                    use_rerank=use_rerank, fetch_k=fetch_k or top_k)
                for q in questions:
                    docs = ret.invoke(q["question"])
                    gold = set(q["gold_pages"])
                    rows.append({
                        "chunking": chunking, "embedder": emb_key,
                        "rerank": use_rerank, "fetch_k": fetch_k, "top_k": top_k,
                        "qid": q["id"],
                        "page_recall": page_recall_at_k(docs, gold, top_k),
                        "boiler_rate": boilerplate_rate(docs, top_k),
                        "first_gold_rank_topk": first_gold_rank(docs, gold),
                        "first_gold_rank_dense100": first_gold_rank(wide[q["id"]], gold),
                    })
                print(f"  {chunking}/{emb_key} rerank={use_rerank} fetch={fetch_k} k={top_k} done")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "retrieval_sweep.json").write_text(json.dumps(rows, indent=1))
    summarize_phase1(rows)


def summarize_phase1(rows):
    import statistics as st
    keyf = lambda r: (r["chunking"], r["embedder"], r["rerank"], r["fetch_k"], r["top_k"])
    groups = {}
    for r in rows:
        groups.setdefault(keyf(r), []).append(r)
    print(f"\n{'arm':60s} {'recall':>7s} {'boiler':>7s} {'burial>k':>8s}")
    for key in sorted(groups):
        g = groups[key]
        rec = st.mean(x["page_recall"] for x in g)
        boil = st.mean(x["boiler_rate"] for x in g)
        buried = sum(1 for x in g if x["first_gold_rank_topk"] is None) / len(g)
        print(f"{str(key):60s} {rec:7.3f} {boil:7.3f} {buried:8.3f}")


JUDGED_ARMS = {
    # arm -> (chunking, embedder, fetch_k, top_k, use_rewrite)
    # HyDE is deliberately EXCLUDED from judged arms: v7 showed it situational
    # (TOST-equivalent on FiQA) and wiring it here would swap the query embedder;
    # the live env keeps its independent USE_HYDE toggle.
    "A0_live_baseline":   ("recursive", "minilm", 20, 5, True),
    "A1_hygiene":         ("by_title", "minilm", 50, 10, True),
    "A2_hygiene_bge":     ("by_title", "bge", 50, 10, True),
    "A3_hygiene_bge_raw": ("by_title", "bge", 50, 10, False),
}
# NOTE: before running phase 2, UPDATE fetch_k/top_k (and by_title vs
# by_title_prefix) in A1-A3 to phase 1's winners. This table is the pre-run default.


def phase2(questions):
    from eval_utils import JsonCache, judge_correctness  # tests/rag_evaluation on PYTHONPATH
    from config.prompts import RAG_PROMPT
    from unstructured.partition.auto import partition

    gen = openrouter_chat(GEN_MODEL)
    judge = openrouter_chat(JUDGE_MODEL)
    cache = JsonCache(RESULTS / "cache" / "judged.json")
    elements = partition(filename=PDF_PATH, strategy="fast")

    out = {}
    for arm, (chunking, emb_key, fetch_k, top_k, use_rewrite) in JUDGED_ARMS.items():
        chunks = build_corpus(elements, chunking)
        store = build_store(chunks, emb_key)
        from config import RagConfig
        from rag.retrieval.retrievers import build_rag_pipeline
        cfg = RagConfig(retrieval_top_k=top_k, use_reranking=True, rerank_fetch_k=fetch_k,
                        use_hyde=False, use_query_rewrite=False, use_hybrid_retrieval=False)
        ret = build_rag_pipeline(cfg, store, corpus=None)
        rewriter = openrouter_chat(GEN_MODEL) if use_rewrite else None

        arm_rows = []
        for q in questions:
            ck = f"{arm}::{q['id']}"
            if (hit := cache.get(ck)) is not None:
                arm_rows.append(hit); continue
            query = q["question"]
            if rewriter is not None:
                from config.prompts import QUERY_REWRITE_PROMPT
                query = str(rewriter.invoke(QUERY_REWRITE_PROMPT.format(question=query)).content)
            docs = ret.invoke(query)
            context = "\n\n".join(d.page_content for d in docs)
            # RAG_PROMPT is a ChatPromptTemplate with a chat_history placeholder
            msgs = RAG_PROMPT.format_messages(context=context, question=q["question"], chat_history=[])
            answer = str(gen.invoke(msgs).content)
            # eval_utils signature: judge_correctness(answer, reference, question, judge_llm)
            score, reason = judge_correctness(answer, q["reference_answer"], q["question"], judge)
            row = {"qid": q["id"], "arm": arm, "correct": score, "answer": answer, "reason": reason}
            cache.set(ck, row); arm_rows.append(row)
        cache.flush()
        out[arm] = arm_rows
        import statistics as st
        print(f"{arm}: correctness {st.mean(r['correct'] for r in arm_rows):.3f} (n={len(arm_rows)})")

    (RESULTS / "judged_arms.json").write_text(json.dumps(out, indent=1))
    from eval_utils import holm_bonferroni, paired_wilcoxon
    base = {r["qid"]: r["correct"] for r in out["A0_live_baseline"]}
    ps = []
    for arm in [a for a in JUDGED_ARMS if a != "A0_live_baseline"]:
        pair = [(base[r["qid"]], r["correct"]) for r in out[arm] if r["qid"] in base]
        stat = paired_wilcoxon([a for a, _ in pair], [b for _, b in pair])
        ps.append((arm, stat))
        print(f"{arm} vs baseline: {stat}")
    adj = holm_bonferroni([s["p"] for _, s in ps])  # paired_wilcoxon returns {stat, p, effect_r, n_nonzero}
    for (arm, _), p in zip(ps, adj):
        print(f"{arm}: Holm-adjusted p = {p:.2e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, default=1, choices=[1, 2])
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    qs = load_questions()
    if args.limit:
        qs = qs[: args.limit]
    (phase1 if args.phase == 1 else phase2)(qs)
```

Signatures above are verified against the codebase: `judge_correctness(answer, reference, question, judge_llm) -> tuple[float, str]` (`eval_utils.py:1141`), `paired_wilcoxon` returns `{stat, p, effect_r, n_nonzero}` (`:1194`), `JsonCache.get/set/flush` (`:1254`), `QUERY_REWRITE_PROMPT` is a `PromptTemplate` (`.format(question=...)` returns str), `RAG_PROMPT` is a `ChatPromptTemplate` with `context`, `chat_history` (MessagesPlaceholder), `question`. Do not modify eval_utils.

- [ ] **Step 3: Smoke phase 1 on a slice**

Run: `CUDA_VISIBLE_DEVICES="" PYTHONPATH=src:tests/rag_evaluation uv run python evaluation/live_pdf_eval/run_ablation.py --phase 1 --limit 5`
Expected: chunk-count lines per chunking arm (`by_title` should show FAR fewer, LONGER chunks than `recursive`'s 1,778/median-67), arm progress lines, a summary table, `results/retrieval_sweep.json` written. Sanity: `by_title` arms must show boiler_rate well below `recursive` arms.

- [ ] **Step 4: Smoke phase 2 on a slice**

Run: `CUDA_VISIBLE_DEVICES="" PYTHONPATH=src:tests/rag_evaluation uv run python evaluation/live_pdf_eval/run_ablation.py --phase 2 --limit 3`
Expected: 4 arms × 3 questions, correctness in [0,1], cache file created, Wilcoxon lines print. Cost: negligible.

- [ ] **Step 5: Commit**

```bash
git add evaluation/live_pdf_eval/run_ablation.py evaluation/live_pdf_eval/common.py
git commit -m "eval(rag): real-substrate ablation runner — retrieval sweep + judged end-to-end arms"
```

---

### Task 5: Run the ablation, write the results report

**Files:**
- Create: `evaluation/live_pdf_eval/results/retrieval_sweep.json`, `results/judged_arms.json` (run outputs)
- Create: `evaluation/live_pdf_eval/REPORT.md`

**Interfaces:**
- Consumes: Tasks 1–4 outputs.
- Produces: winner tuple (chunking, prefix on/off, embedder, fetch_k, top_k) + judged deltas — the inputs Task 6 needs.

- [ ] **Step 1: Full phase 1 run**

Run: `CUDA_VISIBLE_DEVICES="" PYTHONPATH=src:tests/rag_evaluation uv run python evaluation/live_pdf_eval/run_ablation.py --phase 1 2>&1 | tee evaluation/live_pdf_eval/results/phase1.log`
Expected runtime: tens of minutes on CPU (6 corpus embeds + 42 arms × ~60 questions; cross-encoder over ≤100 candidates per query). Watch the summary table.

- [ ] **Step 2: Pick phase-2 arm parameters from phase-1 winners**

Decision rule: per (chunking, embedder), take the (fetch_k, top_k) with highest mean page_recall; break ties toward smaller fetch_k/top_k. Pick `by_title` vs `by_title_prefix` by page_recall (prefix must beat plain by >0.02 to earn its corpus mutation). Edit `JUDGED_ARMS` in `run_ablation.py` accordingly and note the choice in the commit message.

- [ ] **Step 3: Full phase 2 run**

Run: `CUDA_VISIBLE_DEVICES="" PYTHONPATH=src:tests/rag_evaluation uv run python evaluation/live_pdf_eval/run_ablation.py --phase 2 2>&1 | tee evaluation/live_pdf_eval/results/phase2.log`
Expected: 4 arms × N≈60, per-arm correctness means, Wilcoxon + Holm lines. Cost: ~4×60 generations (gpt-4o-mini) + rewrites + ~240 judge calls (gpt-4o) ≈ a few dollars.

- [ ] **Step 4: Write `REPORT.md`**

Structure (fill with real numbers from the two JSONs/logs):

```markdown
# Live-PDF Retrieval Ablation — Results
## Setup (substrate, arms, metrics, models — 1 short paragraph each)
## Phase 1: retrieval sweep table (mean page_recall / boiler_rate / buried-share per arm)
## Phase 2: judged arms (correctness mean per arm; paired Wilcoxon vs A0; Holm-adjusted p)
## Winners + decision rule applied
## Recommended defaults (exact RagConfig values for Task 6)
## Honest caveats (InMemory vs Milvus backend; single-corpus; judge = gpt-4o)
```

- [ ] **Step 5: REVIEW GATE — present REPORT.md to the user before Task 6.** Defaults change only on user sign-off.

- [ ] **Step 6: Commit**

```bash
git add evaluation/live_pdf_eval/results/retrieval_sweep.json evaluation/live_pdf_eval/results/judged_arms.json evaluation/live_pdf_eval/REPORT.md evaluation/live_pdf_eval/run_ablation.py
git commit -m "eval(rag): live-PDF ablation results — chunking/embedder/pool winners with paired stats"
```

---

### Task 6: Eval-tuned defaults + live re-ingest + smoke (Track C)

**Files:**
- Modify: `src/config/config.py` (defaults per REPORT.md winners)
- Create: `scripts/reingest_workspace_files.py`
- Modify: `.env` files of the running stack (env-only; not committed)

**Interfaces:**
- Consumes: Task 5's winner tuple. Assumed winners for concreteness (REPLACE with actuals): `chunking_strategy="by_title"`, `chunk_prepend_section_title` per eval, `embedding_model="BAAI/bge-small-en-v1.5"` under `embedding_provider="huggingface"`, `rerank_fetch_k=50`, `retrieval_top_k=10`.
- Produces: updated defaults; re-ingested Milvus corpus; passing live smoke on the original failing question.

- [ ] **Step 1: Update `src/config/config.py` defaults**

Apply the REPORT.md winners, e.g. (adjust to actuals):

```python
    retrieval_top_k: int = 10
    rerank_fetch_k: int = 50
    chunking_strategy: str = "by_title"
```

Do NOT change `embedding_provider`/`embedding_model` defaults (they stay OpenAI for API deployments); the local stacks select bge via env: `EMBEDDING_PROVIDER=huggingface EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`. Update the field comments to cite `evaluation/live_pdf_eval/REPORT.md`.

- [ ] **Step 2: Run the suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q` — expected: all pass (fix any test that asserted old defaults).

- [ ] **Step 3: Write `scripts/reingest_workspace_files.py`**

```python
"""Re-ingest every stored file through the current chunking + embedding config,
then reset chat-memory vectors so the indexer re-embeds them with the new model.

DESTRUCTIVE to Milvus rows (file chunks are deleted+rewritten per file by
process_file itself; chat vectors are purged). Postgres only gets
messages.indexed_at=NULL. Run with the TARGET stack's DB env, e.g.:
  DATABASE__NAME=talos_frontend DATABASE__PORT=5433 EMBEDDING_PROVIDER=huggingface \
  EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 CUDA_VISIBLE_DEVICES="" \
  PYTHONPATH=src uv run python scripts/reingest_workspace_files.py [--dry-run]
"""
import argparse
import asyncio

import src  # noqa: F401  — registers all SQLAlchemy mappers (import_sa_models)
from sqlalchemy import select, text

from database import SessionLocal
from files.models import FileAttachment, ProcessingStatus
from processing.tasks import process_file  # worker task: async def process_file(file_id: uuid.UUID)
from rag.vector_store import WORKSPACE_COLLECTION


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with SessionLocal() as db:
        files = db.scalars(
            select(FileAttachment).where(
                FileAttachment.deleted_at.is_(None),
                FileAttachment.processing_status == ProcessingStatus.COMPLETED,
            )
        ).all()
        print(f"{len(files)} completed files to re-ingest")
        if args.dry_run:
            for f in files:
                print(f"  would re-ingest {f.id} {f.filename}")
            return

        for f in files:
            print(f"re-ingesting {f.id} {f.filename} ...", flush=True)
            asyncio.run(process_file(f.id))

        # chat memory: purge segment vectors + reset indexed_at so the cron
        # indexer re-embeds with the new embedding model
        from pymilvus import MilvusClient
        from config import global_rag_config as cfg
        client = MilvusClient(uri=f"http://{cfg.milvus_host}:{cfg.milvus_port}")
        client.delete(collection_name=WORKSPACE_COLLECTION, filter='source == "chat"')
        n = db.execute(text("UPDATE messages SET indexed_at = NULL WHERE indexed_at IS NOT NULL")).rowcount
        db.commit()
        print(f"chat vectors purged; {n} messages queued for re-indexing")


if __name__ == "__main__":
    main()
```

Verified: `process_file(file_id: uuid.UUID)` is the async worker task in `src/processing/tasks.py:19` (it builds its own session/storage and calls `process_document`); the chat table is `messages` (`src/chat/model.py:43`). One check remains for the implementer: read `process_file`'s body once to confirm it can run outside the taskiq worker context (no broker-injected args) — if it needs the worker, call `process_document(file_record, db, storage)` from `src/processing/documents.py:19` directly instead, constructing the session and the workspace-scoped `MinIOFileSystem` the same way `process_file` does. Do not modify chat models.

- [ ] **Step 4: Dry-run, then verify the target DB env**

Run: `psql -h localhost -p 5433 -U talos_app -l` (password `password`) — confirm which DB (`talos_frontend` vs `talos_dev`) holds the demo workspace. Then:
`DATABASE__NAME=<target> DATABASE__PORT=5433 PYTHONPATH=src uv run python scripts/reingest_workspace_files.py --dry-run`
Expected: lists the workspace guide PDF (+ demo_note.txt). **STOP if the file list looks wrong.**

- [ ] **Step 5: Real re-ingest**

Same command without `--dry-run`, plus `EMBEDDING_PROVIDER=huggingface EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 CUDA_VISIBLE_DEVICES=""`.
Expected: per-file progress; afterwards verify: `PYTHONPATH=src uv run python -c "from rag.vector_store import get_collection_info; print(get_collection_info())"` — entity count should be FAR below 1,883 (by_title merges fragments) and > 0.

- [ ] **Step 6: Restart the serving stack from talos-main with the new env**

The old integration worktree code lacks bge support — after re-ingest its MiniLM queries would mismatch the corpus (the new dim assert can't catch same-dim/different-model). Kill the old uvicorn/worker/scheduler and relaunch **from /home/romia/talos-main** with the strong-profile env PLUS `EMBEDDING_PROVIDER=huggingface EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 CUDA_VISIBLE_DEVICES="" OPENAI_BASE_URL=https://openrouter.ai/api/v1 OPENAI_API_KEY=<from gp_artifact/.env> OPENAI_MODEL=openai/gpt-4o-mini USE_HYDE=<per REPORT.md> USE_QUERY_REWRITE=<per REPORT.md>` and the target `DATABASE__NAME`. (Worker needs `PYTHONPATH=/home/romia/talos-main/src:/home/romia/talos-main`.)

- [ ] **Step 7: Live smoke — the original failing question**

Run `scripts/debug_ask.py` (existing harness) with the question "what system design prep steps does the guide recommend?" against the restarted stack.
Expected vs the 2026-07-02 trace: retrieved chunks are substantive section chunks (no bare "System design"/"Preparation required" fragments), answer lists concrete multi-step advice, trace `effective_config` shows the new defaults. Save the debug JSON to `evaluation/live_pdf_eval/results/live_smoke.json`.

- [ ] **Step 8: Commit**

```bash
git add src/config/config.py scripts/reingest_workspace_files.py evaluation/live_pdf_eval/results/live_smoke.json
git commit -m "feat(rag): eval-tuned retrieval defaults + workspace re-ingest script; live smoke of the burial query"
```

- [ ] **Step 9: Update the Owner's Manual note (small)**

Append a short "2026-07 retrieval remediation" paragraph to `docs/rag-manual/` source (chunking by_title, bge embedder env, new defaults, pointer to REPORT.md) — regenerating the PDF can wait; commit the `.typ` change:

```bash
git add docs/rag-manual/
git commit -m "docs(rag-manual): note by_title chunking, bge embeddings, eval-tuned retrieval defaults"
```
