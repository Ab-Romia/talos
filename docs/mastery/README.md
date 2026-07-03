# Talos RAG — Mastery Guide

**Purpose:** make you the genuine owner of this system — able to point at any
file, explain any line, change anything yourself without an LLM, and, when you
do use an LLM, direct and verify it like a lead engineer.

This guide complements the **Owner's Manual** (`docs/rag-manual/RAG_Owners_Manual.pdf`):
the manual is the *system-level* story (concepts, diagrams, ops); this guide is
the *code-level* one (every file, every function, every library, every seam).

## Chapters

| # | File | What it makes you master |
|---|------|--------------------------|
| 00 | `00-foundations.md` | The concepts beneath the code — embeddings, chunking, bge vs MiniLM, reranking, HyDE, the eval story — assuming nothing |
| 01 | `01-mental-model.md` | The system in layers, the ownership map, repo orientation, the running stack |
| 02 | `02-rag-core-walkthrough.md` | Every function in `src/rag/` core: chain, router, trace, retrieval |
| 03 | `03-config-and-settings-walkthrough.md` | `RagConfig`, prompts, `ai_settings` (incl. the security story) |
| 04 | `04-background-pipelines-walkthrough.md` | Chat indexer, file pipeline, taskiq wiring |
| 05 | `05-tests-and-eval-walkthrough.md` | Every test and what invariant it guards; the eval harness |
| 06 | `06-libraries-as-used.md` | Each third-party library, exactly as Talos uses it |
| 07 | `07-integration-map.md` | Every seam with teammate code; cross-branch coordination |
| 08 | `08-change-playbook.md` | Recipes: how to change anything, and verify it yourself |
| 09 | `09-working-with-llms.md` | How to brief and *verify* LLM work (with this project's real bug case studies) |
| 10 | `10-viva-qa.md` | Defense Q&A bank — examiner-grade questions with model answers |

## How to study this (suggested)

1. **Day 1:** Chapter 00 first — slowly, it's the vocabulary everything else is
   written in. Then Owner's Manual cover-to-cover, then chapter 01, then 02. After
   02, do the drill: run one `@ai` ask with `debug:true` and narrate every
   trace field out loud from memory.
2. **Day 2:** Chapters 03–05. Drill: add a throwaway `RagConfig` field, watch
   it appear in `effective_config`, then revert.
3. **Day 3:** Chapters 06–07. Drill: draw the integration map on paper from
   memory, then check it against 07.
4. **Day 4:** Chapter 08 — actually perform two recipes end-to-end (e.g. change
   the prompt; tune `chat_recall_k` via the ai-config API). Chapter 09.
5. **Before the defense:** Chapter 10 twice — once open-book, once closed.

Every chapter ends with **self-test questions**. If you can't answer one,
re-read that section — the answer is always in it.

## Scope

Your code (this guide's subject): `src/rag/`, `src/processing/`,
`src/config/config.py`+`prompts.py`, `tests/rag*`, `tests/processing/`,
`tests/chat/test_chat_indexing.py`, `docs/`. Teammate code is covered only at
the seams (chapter 07) — the rule is you never hand-edit it.
