# Documentation figures

Native **Typst / [fletcher](https://github.com/Jollywatt/typst-fletcher)** diagrams
for the *Talos — Documentation*. They replace the eight `#figure-todo(...)`
placeholders (the amber *"TODO Figure: …"* boxes) and match the house diagram
style used by `registration_sequence.typ` (monochrome, 1 pt black node strokes,
0.8 pt edges, dashed-gray lifelines, serif labels with `monospace` for code).

Each file is a self-contained fletcher `diagram(...)` and **carries no title or
caption of its own** — the caption is supplied by the surrounding `#figure(...)`
so it renders once, underneath, via Typst's figure numbering.

## Setup (do this once)

1. Copy this whole `figures/` folder so it sits **next to your `.typ` source**
   (i.e. `include "figures/<name>.typ"` resolves from the main document).
2. No extra imports are needed: **each figure file imports fletcher itself**, so
   the `include` works even if the main document never imported fletcher. (It
   pulls `@preview/fletcher:0.5.8`, the same version as `registration_sequence.typ`.)
3. Fonts/size are **inherited** — the figure files set no `#set text`/`#set page`,
   so they take the body font (New Computer Modern) automatically.

## Placement guide — find each placeholder, replace with the block

Each figure below lists **exactly** the placeholder to search for (the
`#figure-todo("…")` call — it renders as the amber *TODO Figure: …* box), the
section it lives in, and the sentence right before it so you can locate it fast.
Delete the whole `#figure-todo(...)` line and paste the block in its place.
The `<fig:…>` label lets you cross-reference with `@fig:…` elsewhere.

---

### 1 → `message_orm_layout.typ`  ·  §9.1.1 Message ORM Model (just before *9.1.2 Schema & Validation*)

Right after the sentence: *"…handled gracefully by the tree-assembly logic in `get_thread()`."*

Find and delete:
```typst
#figure-todo("Message ORM column layout: derived columns and GIN indexes")
```
Replace with:
```typst
#figure(
  include "figures/message_orm_layout.typ",
  caption: [Message ORM column layout: derived columns and GIN indexes.],
) <fig:message-orm-layout>
```

---

### 2 → `prosemirror_node_hierarchy.typ`  ·  §9.1.2 Schema & Validation (just before *9.1.3 Storage Layer*)

Right after the sentence: *"…accepted without a client-side mark-name normalisation step."*

Find and delete:
```typst
#figure-todo("Node hierarchy: doc → block nodes → inline group → mention/reference/slash_command atoms, with mark set")
```
Replace with:
```typst
#figure(
  include "figures/prosemirror_node_hierarchy.typ",
  caption: [`chat_schema` node hierarchy: `doc` → block nodes → inline group →
    the `mention` / `reference` / `slash_command` atoms, with the mark set.],
) <fig:prosemirror-node-hierarchy>
```

---

### 3 → `thread_recursive_cte.typ`  ·  §9.1.3 Storage Layer (just before *9.1.4 Real-time Layer*)

Right after the sentence: *"…while still providing observable failure modes."*

Find and delete:
```typst
#figure-todo("Recursive CTE expansion for 3-level thread: anchor → union passes → flat result → Python tree assembly")
```
Replace with:
```typst
#figure(
  include "figures/thread_recursive_cte.typ",
  caption: [`get_thread` assembles a reply tree with one recursive CTE: an anchor
    row, `UNION ALL` passes recursing on the `reply_to_id` self-FK, a flat result
    set, then an $O(n)$ Python pass into a nested tree.],
) <fig:thread-recursive-cte>
```

---

### 4 → `message_delivery_fanout.typ`  ·  §9.1.4 Real-time Layer (just before *9.1.5 REST API*)

Right after the sentence: *"…while maintaining precise control over direct notifications."*

Find and delete:
```typst
#figure-todo("Message delivery fan-out: sender → store_message → channel room broadcast (skip sender) → per-mentioned-user personal room emit")
```
Replace with:
```typst
#figure(
  include "figures/message_delivery_fanout.typ",
  caption: [Message delivery fan-out: both transports converge on `store_message`,
    then one `message` event broadcasts to the channel room (sender skipped) and
    to each mentioned user's personal room.],
) <fig:message-delivery-fanout>
```

---

### 5 → `search_jsonb_vs_ilike.typ`  ·  §11.2 (search implementation, just before *11.3 Pagination and Counting*)

Right after the sentence: *"…would require a ranking model this module does not attempt to provide."*

Find and delete:
```typst
#figure-todo("figure showing the JSONB document tree for a single message next to the serialized string used by the ILIKE cast, highlighting which string are structural (node types, mention attrs) versus user-visible text, to make the false-positive/false-negative risk concrete")
```
Replace with:
```typst
#figure(
  include "figures/search_jsonb_vs_ilike.typ",
  caption: [The JSONB document tree of a message versus the serialized string an
    `ILIKE '%q%'` cast scans — the source of structural false positives and
    fragmented-text false negatives.],
) <fig:search-jsonb-vs-ilike>
```

---

### 6 → `search_two_query_lifecycle.typ`  ·  §11.3 Pagination and Counting (just before *11.4 Response Contract*)

Right after the sentence: *"…not a hard requirement for a channel history search."*

Find and delete:
```typst
#figure-todo("figure showing the two-query lifecycle of a search request: router converts page/page_size to offset/limit, service issues COUNT then SELECT against Postgres, router reassembles the paginated response envelope")
```
Replace with:
```typst
#figure(
  include "figures/search_two_query_lifecycle.typ",
  caption: [Two-query search lifecycle: the router maps `page`/`page_size` to
    `offset`/`limit`, `search_messages` issues `COUNT` then `SELECT`, and the
    router reassembles the paginated response envelope.],
) <fig:search-two-query-lifecycle>
```

---

### 7 → `future_image_search.typ`  ·  §1.2 Platform Enhancements (future-work chapter; just before *"Notifications are limited to in-platform delivery…"*)

Right after the sentence: *"…rather than an extension of the existing text-based one."*

Find and delete:
```typst
#figure-todo("figure showing the current text-based search pipeline alongside the proposed extension with an image embedding branch feeding into the same retrieval index")
```
Replace with:
```typst
#figure(
  include "figures/future_image_search.typ",
  caption: [Proposed multimodal branch: an image embedder maps into the same
    vector space and shares the text pipeline's retrieval index and query
    contract — only the embedding model changes. (Future work.)],
) <fig:future-image-search>
```

---

### 8 → `future_scaled_ai_serving.typ`  ·  §1.3 AI System Evolution (future-work chapter; just before *"A further direction is opening public endpoints…"*)

Right after the sentence: *"…larger than those used during validation."*

Find and delete:
```typst
#figure-todo("figure showing the proposed scaled AI-serving architecture, including a caching layer in front of the inference service and a sharded/distributed vector database")
```
Replace with:
```typst
#figure(
  include "figures/future_scaled_ai_serving.typ",
  caption: [Proposed scaling path: a cache layer fronts a distributed, autoscaled
    inference pool while the vector store is sharded across nodes. (Future work.)],
) <fig:future-scaled-ai-serving>
```

---

> **Note on the exact placeholder text.** The strings above are the captions as
> they appear in the compiled PDF. If your source wrote a `#figure-todo(...)`
> with slightly different whitespace/line-wrapping, match on the distinctive
> words (e.g. *"Recursive CTE expansion"*, *"two-query lifecycle"*) — there is
> exactly **one** placeholder per figure, so there is no chance of a wrong hit.

### Wide diagrams

A few diagrams (fan-out, both sequence-style figures, the thread pipeline) are
wider than a normal text column. If one overflows the page, wrap the `include`
in a `scale` — the caption stays put:

```typst
#figure(
  scale(88%, reflow: true, include "figures/search_two_query_lifecycle.typ"),
  caption: [ … ],
) <fig:search-two-query-lifecycle>
```

## Accuracy notes (figures follow the code, not just the prose)

Built from `src/chat/*` (`model.py`, `schema.py`, `service.py`, `realtime.py`,
`search.py`); where prose and implementation diverge, the code wins:

- The self-referential FK is **`reply_to_id`** (the prose calls it `parent_id`),
  `ON DELETE SET NULL`.
- `messages` indexes: `ix_messages_channel_sent_at` (B-tree on
  `(channel_id, sent_at)`), `ix_messages_content_gin` (GIN on `content`),
  `ix_messages_mentioned_user_ids_gin` (GIN on `mentioned_user_ids`).
- `set_content()` writes the three derived columns together: `content`,
  `content_size_bytes`, `mentioned_user_ids`.
- Block nodes: `doc`, `paragraph`, `heading`, `blockquote`, `code_block`,
  `bullet_list`, `ordered_list`, `list_item`, `hard_break`, `horizontal_rule`;
  inline atoms `mention` / `reference` / `slash_command`; marks
  `strong`/`em`/`underline`/`strike`/`code`/`link` (+ TipTap `bold`/`italic`).
- Delivery reflects `realtime.py`: `sio.send(..., skip_sid=sender)` to
  `channel:{id}`, per-mention emits to `user:{uid}`, `@Talos` → `maybe_ai_reply`;
  HTTP and socket paths share one `store_message` service.
- Search reflects `search.py`: `content.cast(String).ilike('%q%')`, a `COUNT`
  then a `SELECT` with `LIMIT`/`OFFSET`, returning `(messages, total)`.

Figures 7–8 are labelled *future work* and correspond to forward-looking sections
of the document, not shipped code.
