# 09 · Working with LLMs on this codebase — direct, and verify

You will build a lot of this system by directing an LLM (or a teammate) and then
checking the work. This chapter is the distilled method from *this project's real
history* — the briefs that produced clean code, and the five review checks that
each caught a real, shipped-to-a-branch bug before it reached main. The thesis:
**an LLM is a fast, confident junior engineer.** It will produce plausible code
that passes a happy-path test and hides a correctness bug in the seams —
connection affinity, re-validation, coercion, races, arithmetic. Your job is not
to write less; it's to *verify harder*, with evidence.

---

## 1 · How to write a task brief

The briefs that worked on Talos shared five parts. Skip any one and you get
plausible-but-wrong.

1. **Context — where it lives and what's canonical.** State the branch, the
   file(s), and the *ground truth* the model must not re-derive. Talos's canonical
   facts live in memory and the manual: sync SQLAlchemy, `PYTHONPATH=src`, UUID
   PKs, `config()` vs `global_rag_config`, "no Alembic — `create_all` in
   lifespan." The stale root `CLAUDE.md` is *wrong* about the architecture — say
   so explicitly, or the model will follow it.

2. **Exact interfaces — signatures, not vibes.** Give the function signature, the
   return type, the config field name, the trace field. "Add a knob" produces
   drift; "add `chat_recall_overlap_threshold: float = 0.6` to `RagConfig`, read
   it through the `config=` seam in `select_chat_context`, add it to `OVERRIDABLE`
   and `AiConfigPatch` with `Field(ge=0, le=1)`" produces the right diff.

3. **Global constraints — the invariants (chapter 08).** Name the ones in scope:
   tenancy exprs always conjoin `workspace_id`; eval == ship (edit
   `build_rag_pipeline`, not a fork); config threads by seam; chat memory can
   never kill an answer; **never touch teammate-owned files — report instead.**
   These are non-negotiable and the model won't infer them.

4. **TDD requirement — test first, and name the file.** "Write/extend the test in
   `tests/rag/test_ai_settings.py` *before* the implementation; it must assert the
   coercion (`"9"` → int 9) and the out-of-bounds drop." A brief that demands the
   test first gets you a test that actually constrains the code, not one
   retrofitted to pass.

5. **Explicit staging paths — where new files go.** "Docs under `docs/mastery/`,
   touch nothing else." "Eval arms in `evaluation/live_pdf_eval/run_ablation.py`."
   Ungrounded, the model scatters files and invents directories.

A good brief reads like R1–R12 in chapter 08: edit *these lines*, test *this
file* first, verify *this way*, blast radius *this*.

---

## 2 · The review checklist that caught real bugs here

These are not hypotheticals. Each is a bug that an LLM (or the flow of
LLM-assisted work) actually produced on this branch, that passed its happy-path
test, and that a *specific* verification question exposed. Learn the five
questions; they generalize to almost every correctness bug this codebase can grow.

### Case 1 — the advisory lock on the ORM session (connection-affinity leak)

**What was written:** the chat indexer took a Postgres session-level advisory lock
to prevent concurrent double-runs — naturally, on the ORM `Session` that was
already open. It worked in the test (one run, no contention).

**The bug:** pg session locks bind to the **connection**, not the session object.
The ORM session commits freely mid-run, and a commit can **return its pooled
connection to the pool** — so the later `pg_advisory_unlock` could execute on a
*different* pooled connection, silently no-op, and **leak the lock forever**,
wedging every future tick.

**The fix (shipped):** take the lock on a **dedicated `engine.connect()`**
connection held for the whole run, unlock + close it in `finally`
(`src/processing/chat_indexing.py:135-180`). Crash-safe: pg drops session locks
when the connection dies.

> **Reusable verification question:** *For any lock, transaction, or
> session-bound resource — is it acquired and released on the SAME connection,
> and does that connection stay pinned across every commit in between?* If the
> resource lives on a pooled/ORM handle that can be recycled, it's wrong.

### Case 2 — `model_copy` doesn't re-validate (poisoned-row injection)

**What was written:** per-workspace overrides are validated by `AiConfigPatch` on
**write**, then stored as JSONB and applied on **read** via
`global_rag_config.model_copy(update=overrides)`. Clean, symmetric, wrong.

**The bug:** pydantic's `model_copy(update=…)` does **not** re-run validators. A
row written before a bound was tightened — or a model since removed from the
allow-list, or a hand-edited JSONB value — flows straight into a live `RagConfig`
unchecked. Write-time validation is not read-time safety when the read path
bypasses the validator.

**The fix (shipped):** `_clean` re-validates **every stored override on read**,
per key, and drops anything that fails (`src/rag/ai_settings.py:79-103`); a model
that fell off the allow-list is neutralized on read, not trusted
(`ai_settings.py:71-76`, comment at `config.py:99-101`).

> **Reusable verification question:** *Does the read path re-validate data that
> the write path validated — or does it trust storage?* Any time validated data
> is persisted and later rehydrated through a mechanism that skips validators
> (`model_copy`, `model_construct`, raw dict spread, ORM load), the read path
> owns validation too.

### Case 3 — raw vs coerced value storage (the `"false"` truthy inversion)

**What was written:** validated overrides stored the value the user sent. A
`use_hyde: false` from a JSON body, or `retrieval_top_k: "9"`, got persisted as
received.

**The bug:** JSONB round-trips strings. `model_copy(update={"use_hyde": "false"})`
sets the field to the **string** `"false"` — which is **truthy** — so "turn HyDE
off" silently turns it *on*. `"9"` as a string breaks arithmetic and comparisons
downstream. The value looked validated but was the wrong *type*.

**The fix (shipped):** `_clean` stores the **coerced** value from the validated
model (`cleaned[k] = getattr(patch, k)`), so `"9"` lands as int `9` and `"false"`
as bool `False`, never as a truthy string (`ai_settings.py:99-102`).

> **Reusable verification question:** *Is the value stored the coerced,
> post-validation value — or the raw input?* Especially across a
> string-serializing boundary (JSON, env, query params), a bool or int that
> survives as a string is a silent-inversion bug waiting to fire.

### Case 4 — check-then-insert upsert race (IntegrityError retry)

**What was written:** the AI-config PATCH did the obvious upsert: `SELECT` the
scope row; if absent, `INSERT`; else merge. Passes every single-threaded test.

**The bug:** two concurrent first-PATCHes for the same scope both `SELECT` (find
nothing), both `INSERT` — the second hits the unique constraint
(`uq_ai_settings_scope` / the partial `uq_ai_settings_ws_default`,
`ai_settings.py:37-43`) and the request 500s. Check-then-act across a uniqueness
constraint is a classic TOCTOU race.

**The fix (shipped):** catch `IntegrityError`, `rollback`, **re-select** the now-
existing row, merge into it, commit — exactly one retry
(`src/rag/settings_router.py:67-76`). The database's constraint is the source of
truth; the code reconciles to it instead of assuming its earlier read still holds.

> **Reusable verification question:** *Between the read that decides to insert and
> the insert itself, could another writer have created the row?* If a uniqueness
> constraint exists, assume the race happens and handle `IntegrityError` with a
> re-read — don't gate on `SELECT`.

### Case 5 — selection-stats arithmetic that didn't close (truncated count)

**What was written:** `select_chat_context` reported `dropped_redundant` and
`kept` in its stats dict. The numbers were individually correct.

**The bug:** they didn't **sum to the input**. Candidates never visited after the
k-cap `break` (`chat_selection.py:53-54`) were neither `kept` nor
`dropped_redundant` — they simply vanished from the accounting. A reader of the
trace couldn't tell whether the pipeline dropped a segment on purpose or lost it
to a bug, because `fetched` didn't reconcile. Observability that doesn't add up is
worse than none — it lies with authority.

**The fix (shipped):** compute `truncated = considered − dropped_redundant − kept`
explicitly, so the identity **closes**: `considered == dropped_redundant + kept +
truncated` (`chat_selection.py:63-69`), surfaced up as `fetched == dropped_tail +
dropped_redundant + truncated + kept` (`rag_chain.py:172-178`, Invariant I6).

> **Reusable verification question:** *Do the reported counts reconcile to the
> input — does every item land in exactly one bucket, and do the buckets sum?* Any
> filter/select/partition that emits stats must account for 100% of its input;
> a missing bucket is a hidden bug or a hidden drop.

---

## 3 · Verifying the LLM's work — evidence, not assertions

The five cases share a root cause: **the code passed a test and the summary said
"done," and both were true and insufficient.** Here is how to not be fooled.

**Never trust "tests pass" without the command and its output.** An LLM saying
"all tests pass" is a claim, not evidence. Require the exact command
(`IS_TEST=1 uv run python -m pytest tests/rag tests/chat tests/processing -q`) and
its actual tail — pass counts, not prose. If you didn't see the output, it didn't
happen. (This is the entire premise of the `verification-before-completion`
discipline: evidence before assertions, always.)

**Demand file:line evidence for every claim.** "Tenancy is scoped" is unverifiable;
"tenancy is scoped at `rag_chain.py:103-107` where the expr conjoins
`workspace_id`" is checkable in five seconds. A brief that asks for grounded
claims gets grounded code; this chapter and chapter 08 are written that way on
purpose. When you review, open the cited line — the citation being *wrong* is
itself a finding.

**Ask adversarial review questions, not "does this look right?"** The five
reusable questions above *are* the adversarial prompt set. Generalized:
- "Is anything acquired on one connection and released on another?"
- "Does any read path trust data a write path validated?"
- "Does any value cross a string boundary and get used as a bool/int?"
- "Is there a check-then-act across a uniqueness or existence constraint?"
- "Do all emitted counts reconcile to the input?"
- "Which invariant (chapter 08) does this touch, and where's the guard test?"
- "What happens on the second concurrent call? On disconnect mid-stream? On a
  crash between two commits?"

Point these at the diff explicitly. "Find the connection-affinity bug in this lock
code" surfaces Case 1; "review this lock code" often doesn't.

**Re-dispatch vs fix yourself — the decision rule.** Fix it yourself when the
defect is local and you can see it (a wrong bound, a missing `await`, a citation
error) — faster than a round-trip. Re-dispatch when the defect is *structural* and
the fix must respect constraints the model didn't hold: a wrong invariant
(re-brief with the invariant named and the guard test required), a
misunderstanding of the architecture (re-brief with the canonical facts), or a
change that sprawled across files it shouldn't touch (re-brief with tighter
staging paths). If you find yourself hand-repairing the same class of mistake
twice, the brief was underspecified — fix the brief, re-dispatch, and add the
missing constraint to your standing checklist.

**One more, specific to this repo:** never let an LLM "fix" a teammate-owned file
(`chat/*`, `workspace/router.py`, filesystem hooks). The correct output is a
*report* in the handoff doc, not a patch (chapter 08, R12 / Invariant I7). If a
brief's cleanest solution edits a teammate file, the brief is wrong — re-scope it.

---

*The LLM writes the plausible version fast. You own the seams: connection
affinity, read-path validation, coercion, races, and arithmetic that closes.
Brief with exact interfaces and named invariants; verify with commands, output,
and file:line — never with "looks right."*
