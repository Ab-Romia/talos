# Documentation figures

Vector figures for the **Talos — Documentation** (Typst). They replace the eight
`#figure-todo(...)` placeholders in the document (the amber *"TODO Figure: …"*
boxes). Regenerate everything with:

```bash
python docs/figures/gen_message_figures.py   # figures 1–2
python docs/figures/gen_more_figures.py       # figures 3–8 (imports the toolkit from the first)
```

Every figure is a self-contained SVG — no external fonts and no `<marker>`
elements (arrowheads are drawn as explicit triangles) so they render identically
in Typst/resvg, browsers, and Inkscape. Text uses a serif + mono font stack that
resolves to Typst's bundled *New Computer Modern* / *DejaVu Sans Mono*, matching
the document body.

| # | File | Replaces the placeholder |
|---|------|--------------------------|
| 1 | `message_orm_layout.svg` | `Message ORM column layout: derived columns and GIN indexes` |
| 2 | `prosemirror_node_hierarchy.svg` | `Node hierarchy: doc → block nodes → inline group → mention/reference/slash_command atoms, with mark set` |
| 3 | `thread_recursive_cte.svg` | `Recursive CTE expansion for 3-level thread: anchor → union passes → flat result → Python tree assembly` |
| 4 | `message_delivery_fanout.svg` | `Message delivery fan-out: sender → store_message → channel room broadcast (skip sender) → per-mentioned-user personal room emit` |
| 5 | `search_jsonb_vs_ilike.svg` | `JSONB document tree for a single message next to the serialized string used by the ILIKE cast (structural vs content)` |
| 6 | `search_two_query_lifecycle.svg` | `Two-query lifecycle of a search request: router offset/limit → service COUNT then SELECT → router reassembles the paginated envelope` |
| 7 | `future_image_search.svg` | `Current text-based search pipeline alongside the proposed image-embedding branch feeding the same retrieval index` |
| 8 | `future_scaled_ai_serving.svg` | `Proposed scaled AI-serving architecture: caching layer in front of the inference service + sharded/distributed vector database` |

## Including them in the Typst source

Copy this `figures/` folder next to your `.typ` source (or adjust the path),
then replace each `#figure-todo(...)` with the matching block below.

```typst
#figure(
  image("figures/message_orm_layout.svg", width: 100%),
  caption: [Message ORM column layout: derived columns and GIN indexes.],
)

#figure(
  image("figures/prosemirror_node_hierarchy.svg", width: 100%),
  caption: [ProseMirror node hierarchy: `doc` → block nodes → inline group →
    the `mention` / `reference` / `slash_command` atoms, with the mark set.],
)

#figure(
  image("figures/thread_recursive_cte.svg", width: 100%),
  caption: [`get_thread()` assembles a reply tree with one recursive CTE: an
    anchor row, `UNION ALL` passes that recurse on the `reply_to_id` self-FK, a
    flat result set, then an $O(n)$ Python pass into a nested tree.],
)

#figure(
  image("figures/message_delivery_fanout.svg", width: 100%),
  caption: [Message delivery fan-out: both transports converge on
    `store_message`, then one `message` event broadcasts to the channel room
    (sender skipped) and to each mentioned user's personal room.],
)

#figure(
  image("figures/search_jsonb_vs_ilike.svg", width: 100%),
  caption: [The JSONB document tree of a message versus the serialized string an
    `ILIKE '%q%'` cast scans — the source of structural false positives and
    fragmented-text false negatives.],
)

#figure(
  image("figures/search_two_query_lifecycle.svg", width: 100%),
  caption: [Two-query search lifecycle: the router maps `page`/`page_size` to
    `offset`/`limit`, `search_messages` issues `COUNT` then `SELECT`, and the
    router reassembles the paginated response envelope.],
)

#figure(
  image("figures/future_image_search.svg", width: 100%),
  caption: [Proposed multimodal branch: an image embedder maps into the same
    vector space and shares the text pipeline's retrieval index and query
    contract — only the embedding model changes. (Future work.)],
)

#figure(
  image("figures/future_scaled_ai_serving.svg", width: 100%),
  caption: [Proposed scaling path: a cache layer fronts a distributed, autoscaled
    inference pool while the vector store is sharded across nodes. (Future work.)],
)
```

## Accuracy notes (figures follow the code, not just the prose)

The figures were built from `src/chat/*` (`model.py`, `schema.py`, `service.py`,
`realtime.py`, `search.py`) and follow the implementation where it diverges from
the prose:

- The self-referential FK column is **`reply_to_id`** (the prose calls it
  `parent_id`); it is `ON DELETE SET NULL`, as documented.
- `messages` has three indexes — `ix_messages_content_gin` (GIN on `content`),
  `ix_messages_mentioned_user_ids_gin` (GIN on `mentioned_user_ids`), and
  `ix_messages_channel_sent_at` (B-tree on `(channel_id, sent_at)`).
- The derived columns written together by `set_content()` are `content`,
  `content_size_bytes`, and `mentioned_user_ids`.
- Schema marks include the TipTap aliases (`bold`, `italic`, `underline`,
  `strike`) alongside the canonical `strong` / `em` / `code` / `link`.
- Delivery fan-out reflects `realtime.py`: `sio.send(..., skip_sid=sender)` to
  `channel:{id}`, then per-mention emits to `user:{uid}`, with `@Talos` mentions
  additionally triggering `maybe_ai_reply`; both HTTP and socket paths share the
  single `store_message` service.
- Search reflects `search.py`: `content.cast(String).ilike('%q%')`, a `COUNT`
  followed by a `SELECT` with `LIMIT`/`OFFSET`, returning `(messages, total)`.

Figures 7–8 are labelled *future work* and correspond to forward-looking sections
of the document, not to shipped code.
