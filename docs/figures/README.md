# Documentation figures

Vector figures for the **Talos — Documentation** (Typst). Regenerate with:

```bash
python docs/figures/gen_message_figures.py
```

Both are self-contained SVGs (no external fonts/markers — arrowheads are drawn
as explicit triangles so they render identically in Typst/resvg, browsers, and
Inkscape). Text uses a serif + mono font stack that resolves to Typst's bundled
*New Computer Modern* / *DejaVu Sans Mono*, matching the document body.

| File | Replaces the placeholder |
|------|--------------------------|
| `message_orm_layout.svg` | `#figure-todo("Message ORM column layout: derived columns and GIN indexes")` |
| `prosemirror_node_hierarchy.svg` | `#figure-todo("Node hierarchy: doc → block nodes → inline group → mention/reference/slash_command atoms, with mark set")` |

## Including them in the Typst source

Copy this `figures/` folder next to your `.typ` source (or adjust the path),
then replace each `#figure-todo(...)` with:

```typst
#figure(
  image("figures/message_orm_layout.svg", width: 100%),
  caption: [Message ORM column layout: derived columns and GIN indexes.],
)
```

```typst
#figure(
  image("figures/prosemirror_node_hierarchy.svg", width: 100%),
  caption: [ProseMirror node hierarchy: `doc` → block nodes → inline group →
    the `mention` / `reference` / `slash_command` atoms, with the mark set.],
)
```

## Accuracy notes (figures follow the code, not just the prose)

Both figures were built from `src/chat/model.py` and `src/chat/schema.py`:

- The self-referential FK column is **`reply_to_id`** (the prose calls it
  `parent_id`); it is `ON DELETE SET NULL`, as documented.
- `messages` has three indexes — `ix_messages_content_gin` (GIN on `content`),
  `ix_messages_mentioned_user_ids_gin` (GIN on `mentioned_user_ids`), and
  `ix_messages_channel_sent_at` (B-tree on `(channel_id, sent_at)`).
- The derived columns written together by `set_content()` are `content`,
  `content_size_bytes`, and `mentioned_user_ids`.
- Schema marks include the TipTap aliases (`bold`, `italic`, `underline`,
  `strike`) alongside the canonical `strong` / `em` / `code` / `link`.
