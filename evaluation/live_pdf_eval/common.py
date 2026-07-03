"""Shared helpers for the live-PDF retrieval ablation."""
import json
import os
from pathlib import Path

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
GEN_MODEL = "openai/gpt-4o-mini"      # matches the live strong profile
JUDGE_MODEL = "openai/gpt-4o"
# The evaluation corpus is a private document; it lives at a neutral,
# git-ignored path and is referred to generically throughout the eval.
PDF_PATH = str(Path(__file__).parent / "data" / "guide.pdf")
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


# --- retrieval metric helpers (ablation runner) ---


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
