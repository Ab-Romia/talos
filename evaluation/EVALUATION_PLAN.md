# RAG Evaluation Plan — Talos

This document specifies the evaluation methodology for the Retrieval-Augmented
Generation pipeline used by Talos. Every design choice is grounded in a
published reference; the full citation list is in §10. The runnable
companion is `rag_evaluation.ipynb`, the helpers are in `eval_utils.py`.

It builds on the four metric families our earlier design note (`Evaluation.md`)
identified — **Correctness, Helpfulness, Groundedness, Retrieval Relevance** —
but re-states them under the names used in the published RAG-eval literature
(Ragas [7], ARES [8], TruLens RAG Triad [9], G-Eval [10]) so the report
aligns with current practice.

---

## 1. System under evaluation

The Talos RAG pipeline (`src/rag/`) — and the academic reference for each
component:

| Stage | Component | Library / model | Reference |
|---|---|---|---|
| End-to-end paradigm | retrieve-then-generate | — | Lewis et al., NeurIPS 2020 [1] |
| Chunking | recursive char splitter, 1000 / 200 | `RecursiveCharacterTextSplitter` | Wang et al., EMNLP 2024 [6] |
| Embedding | dense | OpenAI `text-embedding-3-small` | — (closed model) |
| Vector store | dense ANN | Milvus (prod) / `InMemoryVectorStore` (eval) | — |
| Sparse retrieval | optional BM25 | `langchain_community.BM25Retriever` | Robertson & Zaragoza, FnTIR 2009 [3] |
| Hybrid fusion | weighted ensemble (0.5 / 0.5) | `EnsembleRetriever` | Cormack et al., SIGIR 2009 [4] |
| Query rewriting | LLM-prompted | `QUERY_REWRITE_PROMPT` → `ChatOpenAI` | (production heuristic) |
| HyDE | hypothetical-doc embeddings | `HypotheticalDocumentEmbedder` | Gao et al., ACL 2023 [2] |
| Reranking | cross-encoder | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Nogueira & Cho, 2019 [5] |
| Compression | optional LLM / embeddings filter | `LLMChainExtractor`, `EmbeddingsFilter` | — (engineering option) |
| Generator | RAG answerer | `gpt-4o-mini`, T = 0 | — |

Default top-k is **5** (production setting). The eval uses `RAG_PROMPT_WITHOUT_MEMORY`
so each query is independent. Closed-book uses a separate plain prompt
(no "use the following context" wording).

---

## 2. Metrics

### 2.1 Mapping `Evaluation.md` terms → published terms

| `Evaluation.md` | Ragas / ARES name | Reference |
|---|---|---|
| Correctness | **Answer Correctness** (factual + semantic similarity vs. reference) | Es et al., EACL 2024 [7] |
| Helpfulness | **Answer Relevancy** | Es et al. [7]; Liu et al. (G-Eval), EMNLP 2023 [10] |
| Groundedness | **Faithfulness** | Es et al. [7]; Saad-Falcon et al., NAACL 2024 [8] |
| Retrieval Relevance | **Context Relevance / Contextual Relevancy** | Es et al. [7]; TruLens RAG Triad [9] |

The first three constitute the **RAG Triad** — TruLens's framing,
academically anchored to Ragas [7] and ARES [8]; we cite the underlying
metric papers in the report body and the TruLens documentation only for the
"triad" name (which has no peer-reviewed paper of its own).

### 2.2 Component-level metrics — retrieval only

When the **gold chunk(s)** are known (true for both the synthesised set and
the HotpotQA-intersected set), we report the IR metrics that are standard
in 2024–2025 retrieval papers and BEIR's leaderboards [16]:

- **Hit Rate@k** — fraction of questions where any gold chunk is in the top-k.
- **Recall@k** — gold chunks retrieved / total gold.
- **Precision@k** — gold chunks retrieved / k.
- **MRR (Mean Reciprocal Rank)** — Voorhees, TREC-8 1999 [15].
- **nDCG@k** — Järvelin & Kekäläinen, ACM TOIS 2002 [14]. We report nDCG@5
  (matches our production top-k) **and** nDCG@10 (matches the BEIR
  reporting convention [16]) so our numbers are comparable to published
  retriever baselines.

> ⚠ **Terminology trap.** Ragas's `context_precision` and `context_recall`
> [7] are LLM-judged, *not* the IR Precision@k / Recall@k above. Ragas
> Context Precision is a rank-aware judge over chunks vs. a reference; Ragas
> Context Recall asks whether the retrieved context contains the information
> needed to derive the gold answer. We report both families and label them
> clearly: `ir_*` for the classical IR metrics, `ragas_*` for the
> LLM-judged ones.

### 2.3 Component-level metrics — generation only (oracle context)

Following ARES [8] (which calibrates the judge on labelled examples) and
G-Eval [10] (which uses chain-of-thought judging for NLG), we feed the
**oracle chunk** to the generator and score:

- **Faithfulness** — Es et al. [7]. The judge enumerates claims in the
  answer and marks each as supported / unsupported by the oracle context;
  score = supported / total.
- **Answer Correctness** — Es et al. [7]. Two underlying signals:
  - `answer_factuality` — LLM-judge on a 0 / 0.5 / 1 scale vs. reference.
  - `answer_similarity` — cosine of `text-embedding-3-small` embeddings of
    generated vs. reference answer (Ragas's `semantic_similarity`).

### 2.4 End-to-end metrics

The full pipeline scores on the same questions with all four metrics in
§2.1 plus the IR metrics in §2.2 over the *retrieved* (not gold) context.
**Faithfulness and Context Relevance are reported as N/A for the
closed-book / no-retrieval baseline** — both are structurally undefined
when `retrieved_contexts` is empty (Ragas docs; survey [13]).

---

## 3. Datasets

### 3.1 Primary corpus — Wikipedia Computer Science subset

`evaluation/en_wikipedia_cs.pkl` (~344 MB; 16 874 articles). Default sub-
sample: **N = 200 articles → ~6 600 chunks** at 1000 / 200 (the production
chunking heuristic the empirical study by Wang et al., EMNLP 2024 [6]
endorses for short-form QA).

### 3.2 Test set construction

There is no public Q&A set aligned to *this exact corpus*, so we use two
complementary test sets:

**(a) Synthetic Q&A (primary).** Following the Ragas TestsetGenerator
protocol [7] — single-hop / multi-hop-specific / multi-hop-abstract in a
50 / 25 / 25 mix. We re-implement the protocol inline (rather than
depending on Ragas's testset-graph runtime) but match its key invariant:
**multi-hop pairs are sampled by embedding cosine similarity, not
uniformly at random**. Same conceptual scheme as MuSiQue's compositional
multi-hop construction [18]. Cosine bounds: `0.55 ≤ sim ≤ 0.92` (related
but not near-duplicate). The previous random-pair sampler [pre-v2 of this
plan] produced hallucinated bridge answers (the 8087/Qualcomm pdQ
artifact); the topical-pair fix is what aligns us with Ragas / MuSiQue.

**Quality control.** Two-stage filter on synthesised items:

1. Embedding-cosine pre-filter (answer ↔ source chunk, threshold = 0.20)
   — catches pure hallucinations cheaply.
2. LLM judge — adapted from G-Eval's chain-of-thought scoring [10] with
   the rejection criteria from Ragas [7].

Default test set size: **N_q = 60** raw → ~40–55 after review. Sample-
size justification: ≥ 30 paired observations is the threshold below which
paired Wilcoxon [24] loses meaningful power for medium effects (d ≈ 0.4).

**(b) HotpotQA intersected with our corpus (secondary, optional).** The
distractor / validation split of HotpotQA [17], filtered to questions
whose gold supporting articles all appear in our CS corpus by title. Each
question's gold is mapped to the chunk(s) whose article matches a gold
title — so retrieval IR is well-defined. This is the strongest evidence
for the report: human-authored, with gold supporting facts, no LLM-as-
writer self-grading loop. Comparable approaches: MuSiQue [18],
2WikiMultiHopQA [19] for multi-hop; Natural Questions [20] for single-hop.

### 3.3 Closed-book / contamination control

`gpt-4o-mini` and the cross-encoder were both trained on Wikipedia, so a
question synthesised from a Wikipedia article can often be answered
**without retrieval** — inflating Correctness and Helpfulness while
leaving Faithfulness deceptively high (or undefined). Three controls:

1. **Closed-book baseline variant** — the ablation grid (§4.2) includes
   `closed_book` (no retrieval). The "lift" in Correctness over closed-
   book per category is the value retrieval is actually adding. This is
   the methodology of Mallen et al., ACL 2023 [22] ("When Not to Trust
   Language Models"), the most-cited 2023+ source for the closed-book-
   vs-RAG-lift contamination control.
2. **Counterfactual / noisy-context diagnostic** — replace retrieved
   chunks with random in-corpus chunks; if Correctness barely drops, the
   model is bypassing retrieval. Standard 2024 cite: Yoran et al.,
   ICLR 2024 [23].
3. **(Future work) RePCS KL-divergence** — Sui et al., 2025 [21] —
   diagnoses memorisation via KL between parametric-only and retrieval-
   augmented output distributions. Not implementable on `gpt-4o-mini`
   because it requires full-vocabulary logprobs (the API exposes
   `top_logprobs ≤ 20`); flagged as future work with open-weight models.

---

## 4. Methodology

### 4.1 Judge LLM

`gpt-4o-mini` at temperature 0. Same model as the generator deliberately:
the production default, and a stronger judge would inflate scores
relative to what the deployed system can self-evaluate against. The
report flags the **self-enhancement bias** this introduces (Zheng et al.,
NeurIPS 2023 [11]) as a known threat (§7).

Each judge prompt asks for a numeric score on a fixed scale (binary or
0 / 0.5 / 1) plus a short rationale (G-Eval style [10]). Rationales are
logged but not used in aggregation. Where a metric is computed over
multiple atoms (faithfulness over each claim in the answer; context
relevance over each of k chunks) the per-atom binary judgements are
averaged, as in Ragas [7].

All judge calls use **OpenAI native Structured Outputs**
(`with_structured_output(method="json_schema", strict=True)`) so the
response is guaranteed to match the pydantic schema — no regex extraction.

### 4.2 Ablation grid (v3)

The headline variant is `production_default` — it matches `src/config/config.py`
exactly, so the report can claim "the configuration we ship scored X". The
v2 grid had no row matching the deployed config; v3 fixes that.

| Variant | Retrieval | Rewrite | HyDE | Rerank | Compression | Notes |
|---|---|---|---|---|---|---|
| `closed_book` | none | – | – | – | – | contamination control |
| `dense_only` | dense top-5 | no | no | no | none | minimal RAG |
| **`production_default`** | dense | no | no | **yes** | none | **what we ship** |
| `+rewrite` | dense | yes | no | no | none | single-component ablation |
| `+hyde` | dense | yes | yes | no | none | + HyDE [2] |
| `+rerank` | dense | yes | yes | yes | none | + rerank [5] |
| `hybrid+rerank` | dense + BM25 (0.5/0.5) | yes | yes | yes | none | + sparse fusion [3,4] |
| `compression_calibrated` | dense + BM25 | yes | yes | yes | embeddings filter, **threshold = 0.50** | tests whether v2 compression regression is fixable by re-calibration |
| `everything_on_stress` | dense + BM25 | yes | yes | yes | embeddings filter, threshold = 0.76 | every feature on, including production-default-OFF compression at the langchain default; explicitly NOT what ships |

We re-use the production prompts (`QUERY_REWRITE_PROMPT`,
`RAG_PROMPT_WITHOUT_MEMORY`) and exercise the real langchain helpers
(`HypotheticalDocumentEmbedder`, `CrossEncoderReranker`,
`EmbeddingsFilter`). Milvus is swapped for `InMemoryVectorStore` so the
notebook is portable; this only changes the ANN backend, not the
retrieval logic, which is the variable under study.

### 4.3 Determinism

- Random seed fixed (`SEED = 42`) for sampling, splitting, bootstrap.
- LLM temperature pinned to 0 for both generator and judge.
- Embedding model version pinned via OpenAI `text-embedding-3-small`.
- Each `(variant, question)` answer cached on disk (`evaluation/.cache/`)
  keyed by SHA-256 of the prompt; re-runs are free unless the prompt or
  model changes.

---

## 5. Statistical analysis

We follow the practice now standard in published RAG ablation work,
explicitly anchored to:

- **Per-question scores** stored in tidy long form
  (`variant, question_id, metric, score`).
- **Bootstrap percentile 95 % CIs** (R = 5000 resamples) over per-question
  scores. **BCa** [25] for skewed distributions (Faithfulness piles near
  1.0 — the Efron 1987 BCa correction is the published remedy).
- **Paired Wilcoxon signed-rank** [24] (Dror et al., ACL 2018, "The
  Hitchhiker's Guide to Testing Statistical Significance in NLP") for each
  ablation comparison vs. `dense_only`. Rank-biserial / matched-pairs r
  for effect size in the same table.
- **Holm step-down** [26] (Holm, Scand. J. Stat. 1979) for family-wise
  error correction across the six variant contrasts.
- **Sample-size guard** — Wilcoxon and bootstrap are skipped (with a
  warning) when n < 30, the practical threshold for medium-effect-size
  detection at α = 0.05.

---

## 6. Reproducibility

- Run from the repo root: `uv run jupyter lab evaluation/rag_evaluation.ipynb`
  (or PyCharm). `uv sync --group eval` brings in jupyter / nbconvert /
  ipykernel / datasets / scipy / pandas / matplotlib (project's `eval`
  dep group).
- Required env: `OPENAI_API_KEY` in `.env`. No Milvus needed for the
  default in-memory mode.
- All knobs at the top of the notebook (`SEED`, `N_ARTICLES`,
  `N_QUESTIONS`, `JUDGE_MODEL`, `GENERATOR_MODEL`, `EMBEDDING_MODEL`,
  `TOP_K`, `MIN_TEST_SET_SIZE`, `MIN_N_FOR_STATS`, `RUN_HOTPOT`).
- Outputs: `evaluation/runs/<timestamp>/` — tidy CSVs, summary tables,
  plots, manifest.

---

## 7. Threats to validity

1. **Test-set contamination.** Wikipedia is in `gpt-4o-mini`'s training
   data. Mitigated by the closed-book baseline (§3.3) [22], the
   counterfactual-noise diagnostic (§3.3) [23], and the optional
   HotpotQA intersection (§3.2) [17]. Acknowledged future work: RePCS
   KL-divergence [21] when we have an open-weight LLM.
2. **LLM-as-judge biases** — Zheng et al., NeurIPS 2023 [11]:
   - **Verbosity bias** — judges prefer longer answers; mitigated by
     pinning generator temperature 0 and Faithfulness penalising
     unsupported additions.
   - **Self-enhancement bias** — judge and generator are the same model
     family. We accept this for cost reasons and flag it; the report can
     be re-run with GPT-4o as judge if the supervisor prefers a stronger
     evaluator.
   - **Position bias** — irrelevant: we score one answer at a time, not
     pairwise comparisons.
3. **Single-judge variance.** A single judge model can be wrong in
   correlated ways. We do not run a multi-judge ensemble in v1 because of
   cost; partial mitigation in §8 is to add a 2-judge consistency check
   on a 20 % slice (Zheng et al. [11], §4 protocol).
4. **Synthetic-Q&A drift.** Even with cosine-pair selection, synthesised
   answers are constrained to be derivable from the source chunks, so
   Recall@k is an upper bound on real-world recall. Mitigated by the
   HotpotQA-intersected set (§3.2), whose questions weren't written
   against our corpus.
5. **Sample size.** With our default knobs (N_q ≈ 40–55 surviving
   review), bootstrap CIs and paired Wilcoxon are calibrated for medium
   effect sizes (d ≈ 0.4) at α = 0.05; effects below d ≈ 0.3 will not
   reach significance. The report says so.

---

## 8. Protocol upgrades — status

These were the upgrades the literature called for; v3 implements all of the
no-cost ones and provides scaffolding for the labour-bound ones.

| # | Upgrade | Reference | v3 status |
|---|---|---|---|
| 1 | nDCG@10 alongside @5 | Thakur et al., NeurIPS 2021 [16] | ✅ implemented (notebook §5) — all IR metrics reported at both k=5 and k=10 |
| 2 | Human-rated calibration subset → Pearson/Spearman of LLM-judge vs. human | Es et al. [7] §4; Saad-Falcon et al. [8] | 🟡 scaffold ready (notebook §14): exports `human_calibration_template.csv`; user fills `human_*` columns and re-runs the next cell to compute Pearson + Spearman per metric |
| 3 | ARES PPI-style CIs on judge scores | Saad-Falcon et al. [8] | ⏸ deferred — implement after #2 produces labelled data |
| 4 | 2-judge consistency check on a 10–20 % slice | Zheng et al., NeurIPS 2023 [11] §4 | ✅ implemented (notebook §12) — re-judges a 10-question slice with `gpt-4o`, reports Pearson/Spearman/MAD vs. `gpt-4o-mini` |
| 5 | Counterfactual-context diagnostic per category | Yoran et al., ICLR 2024 [23] | ✅ implemented (notebook §10) — `counterfactual_noise.csv` + per-category aggregation |
| 6 | Closed-book delta per category | Mallen et al., ACL 2023 [22] | ✅ implemented (notebook §11) — `closed_book_lift.csv` with per-category breakdown |
| 7 | Effect-size + Holm-adjusted p in the same plot | Dror et al., ACL 2018 [24] | ✅ implemented (notebook §9) — Δ-vs-baseline panel marks Holm-significant differences with red `*` |

**v3 also adds (not in the original §8 list):**

* **`production_default` variant** matching `src/config/config.py` exactly
  — closes the "no row matches what we ship" gap.
* **Compression-threshold sweep** (notebook §13) — runs the embeddings
  filter at thresholds 0.30 → 0.76 to recommend a calibrated value.
  Surfaces the v2 finding (`threshold = 0.76` strips ~90% of chunks for
  `text-embedding-3-small`) as a quantitative recommendation rather than
  an anecdote.
* **`compression_calibrated` ablation variant** at threshold 0.50 —
  validates whether the compression regression is purely a config bug.

---

## 9. Deliverables

- `EVALUATION_PLAN.md` — this file.
- `eval_utils.py` — corpus loading, IR metrics, structured-output LLM-
  judge prompts, bootstrap + Wilcoxon, RAG variant builder, HotpotQA
  intersection.
- `rag_evaluation.ipynb` — the runnable evaluation.
- `evaluation/runs/<timestamp>/` — per-run artefacts: tidy results CSV,
  summary table, bar charts, raw judge rationales, manifest.

---

## 10. References

[1] Lewis, P. et al. **Retrieval-Augmented Generation for Knowledge-Intensive
NLP Tasks.** NeurIPS 2020. arXiv:2005.11401.

[2] Gao, L., Ma, X., Lin, J., Callan, J. **Precise Zero-Shot Dense Retrieval
without Relevance Labels** (HyDE). ACL 2023. arXiv:2212.10496.

[3] Robertson, S., Zaragoza, H. **The Probabilistic Relevance Framework: BM25
and Beyond.** Foundations and Trends in IR 3(4), 2009. DOI:10.1561/1500000019.

[4] Cormack, G. V., Clarke, C. L. A., Büttcher, S. **Reciprocal Rank Fusion
Outperforms Condorcet and Individual Rank Learning Methods.** SIGIR 2009.
DOI:10.1145/1571941.1572114.

[5] Nogueira, R., Cho, K. **Passage Re-ranking with BERT.** 2019.
arXiv:1901.04704. (Standard cite for the cross-encoder paradigm
`ms-marco-MiniLM-L-6-v2` instantiates.)

[6] Wang, X. et al. **Searching for Best Practices in Retrieval-Augmented
Generation.** EMNLP 2024. arXiv:2407.01219. Plus LangChain
`RecursiveCharacterTextSplitter` documentation.

[7] Es, S., James, J., Espinosa-Anke, L., Schockaert, S. **RAGAS: Automated
Evaluation of Retrieval Augmented Generation.** EACL 2024 (Demo).
arXiv:2309.15217.

[8] Saad-Falcon, J., Khattab, O., Potts, C., Zaharia, M. **ARES: An Automated
Evaluation Framework for Retrieval-Augmented Generation Systems.** NAACL 2024.
arXiv:2311.09476.

[9] TruLens / TruEra. **The RAG Triad** (Context Relevance → Groundedness →
Answer Relevance). Documentation only; the academic anchor is [7] and [8].

[10] Liu, Y., Iter, D., Xu, Y., Wang, S., Xu, R., Zhu, C. **G-Eval: NLG
Evaluation using GPT-4 with Better Human Alignment.** EMNLP 2023.
arXiv:2303.16634.

[11] Zheng, L. et al. **Judging LLM-as-a-Judge with MT-Bench and Chatbot
Arena.** NeurIPS 2023. arXiv:2306.05685.

[12] Friel, R., Belyi, M., Sanyal, A. **RAGBench: Explainable Benchmark for
Retrieval-Augmented Generation Systems.** 2024. arXiv:2407.11005.

[13] Yu, H., Gan, A., Zhang, K., Tong, S., Liu, Q., Liu, Z. **Evaluation of
Retrieval-Augmented Generation: A Survey.** 2024. arXiv:2405.07437.

[14] Järvelin, K., Kekäläinen, J. **Cumulated Gain-Based Evaluation of IR
Techniques.** ACM TOIS 20(4), 2002. DOI:10.1145/582415.582418.

[15] Voorhees, E. M. **The TREC-8 Question Answering Track Report.** TREC-8,
1999. NIST SP 500-246.

[16] Thakur, N., Reimers, N., Rücklé, A., Srivastava, A., Gurevych, I.
**BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information
Retrieval Models.** NeurIPS 2021 (Datasets & Benchmarks). arXiv:2104.08663.

[17] Yang, Z. et al. **HotpotQA: A Dataset for Diverse, Explainable
Multi-hop Question Answering.** EMNLP 2018. arXiv:1809.09600.

[18] Trivedi, H., Balasubramanian, N., Khot, T., Sabharwal, A. **MuSiQue:
Multihop Questions via Single-hop Question Composition.** TACL 10, 2022.
arXiv:2108.00573.

[19] Ho, X., Duong Nguyen, A.-K., Sugawara, S., Aizawa, A. **Constructing A
Multi-hop QA Dataset for Comprehensive Evaluation of Reasoning Steps.**
COLING 2020. arXiv:2011.01060.

[20] Kwiatkowski, T. et al. **Natural Questions: A Benchmark for Question
Answering Research.** TACL 7, 2019. DOI:10.1162/tacl_a_00276.

[21] Sui, Y. et al. **RePCS: Diagnosing Data Memorization in LLM-Powered
Retrieval-Augmented Generation.** 2025. arXiv:2506.15513.

[22] Mallen, A., Asai, A., Zhong, V., Das, R., Khashabi, D., Hajishirzi, H.
**When Not to Trust Language Models: Investigating Effectiveness of
Parametric and Non-Parametric Memories.** ACL 2023. arXiv:2212.10511.

[23] Yoran, O., Wolfson, T., Ram, O., Berant, J. **Making Retrieval-Augmented
Language Models Robust to Irrelevant Context.** ICLR 2024. arXiv:2310.01558.

[24] Dror, R., Baumer, G., Shlomov, S., Reichart, R. **The Hitchhiker's Guide
to Testing Statistical Significance in Natural Language Processing.** ACL
2018. DOI:10.18653/v1/P18-1128.

[25] Efron, B. **Better Bootstrap Confidence Intervals.** JASA 82(397), 1987.
DOI:10.1080/01621459.1987.10478410.

[26] Holm, S. **A Simple Sequentially Rejective Multiple Test Procedure.**
Scand. J. Stat. 6(2), 1979. JSTOR:4615733.
