# Talos-realistic corpus — curated

25 documents representative of what users upload to Talos workspaces. Loaded by
`rag_evaluation_talos.ipynb` via `eu.load_local_corpus("talos_corpus/")`.

## Composition

| Category | Files | Notes |
|---|---|---|
| Distributed-systems lectures | `netcentric_*.pdf` × 4 | RPCs, Dynamo, consistency models, MapReduce |
| Data-mining lectures | `datamining_*.pdf` × 4 | spread across the semester |
| Computer-vision lectures | `cv_*.pdf` × 4 | early + mid + late |
| Talos design docs (Markdown) | `talos_design_*.md` × 10 | Requirements, Technologies, Backend, Frontend, RAG, Auth, AI Assistant, Document DB, Global Search, API Directory |
| Talos project README + MCP contract | `talos_README.md`, `talos_MCP_CONTRACT.md` | guaranteed-unseen-by-LLM |
| Talos system-design PDF | `talos_System_Design_Documentation.pdf` | semester-1 documentation, ~2 MB |

## What this corpus tests
* Real CS / ML / distributed-systems lecture PDFs — the lecture content matches what students upload.
* Talos's own design documentation — guaranteed unseen by `gpt-4o-mini` (closed-book Correctness on these is a clean retrieval-vs-memorisation diagnostic).
* Mixed format: PDFs (image+text mix), short Markdown design docs, longer multi-page PDFs.

## Re-curating

Replace files in this folder. Re-run `rag_evaluation_talos.ipynb` from §1; the rest is pipelined.
