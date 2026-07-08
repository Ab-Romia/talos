"""Generate a judged question set over the private guide PDF (data/guide.pdf, git-ignored).

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
