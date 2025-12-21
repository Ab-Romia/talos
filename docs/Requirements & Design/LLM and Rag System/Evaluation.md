# System Evaluation

The evaluation step is essential to quantify how effective is our implementation of the RAG System compared to a
baseline (usually the plain LLM, or a previous iteration on the implementation).

## Metrics

- **Correctness**
- **Helpfulness**
- **Groundedness**
- **Retrieval Relevance**

### Correctness

Measure the similarity with a reference, ground-truth, answer. (e.g. quiz the system on Q&A dataset, then compare the
outputs to the model answers)

This test is done end-to-end, to evaluate entire system. An "*oracle context*" can be used to validate generation step.

Correctness is highly affected by the quality of the retrieved document chunks:

- Failed to find the chunk containing the fact.
- Irrelevant information.
- Contradictory or outdated data.

### Helpfulness

Quantify whether the output fully answers the original user's query.

It does not directly measure the quality retrieval, but may be useful to validate the generation step or expose bad LLM
configuration.

It may also give insight on the effect of the additional context on the answer, bad context may cause unhelpful
answers (when compared with base model)
e.g. the LLM focuses on a repeated fact in context and ignores the user's intent.

### Groundedness

Measures the extent that the response agrees with the context.
This verifies that the generation step properly uses the retrieved context and not hallucinating or over-using base
knowledge.

### Retrieval Relevance

Measures how relevant the retrieved context to the user query. This directly measures the quality of the retrieval step.

## Methodology

Multiple datasets from different domains are used to avoid over-fitting to a specific domain or task.

- Q&A datasets + quiz
- Encyclopedia articles on specific domains
  - e.g. Wikipedia articles on Computer Science (~20k articles)
- Large code repositories
  - Open-source repositories (large, but may be in model's base knowledge)
  - Our repository (Never seen by the model)
-

One or more of the above metrics is calculated. A standard method is to use a judge LLM (llm-as-a-judge) with system
prompts for evaluating each metric.

Modifications and tweaks are applied to improve scores based on the feedback.

The above is repeated for the base model, and for the end-to-end system, with the goal to measure the base knowledge of
the LLM, and, fine-tune the generation step independently from the rest of the system.


