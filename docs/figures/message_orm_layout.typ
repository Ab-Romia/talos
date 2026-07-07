// messages ORM column layout — derived columns + indexes (src/chat/model.py).
// Included via #figure(include "figures/message_orm_layout.typ", ...).
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge

#let tbl = table(
  columns: (auto, auto, auto),
  inset: (x: 8pt, y: 4pt),
  align: (left, left, left),
  stroke: 0.5pt + luma(60%),
  table.header(
    table.cell(colspan: 3, fill: luma(92%))[*`messages`*],
    [*column*], [*type*], [*key / notes*],
  ),
  `id`,                 `uuid`,        [PK],
  `channel_id`,         `uuid`,        [FK → `channels` · CASCADE],
  `sender_id`,          `uuid`,        [FK → `users` · SET NULL],
  `content`,            `jsonb`,       [◆ `set_content()` · GIN],
  `mentioned_user_ids`, `uuid[]`,      [◆ `set_content()` · GIN],
  `content_size_bytes`, `int`,         [◆ `set_content()`],
  `reply_to_id`,        `uuid`,        [self-FK → `messages` · SET NULL],
  `role`,               `enum`,        [user / assistant / system],
  `sent_at`,            `timestamptz`, [`now()`],
  `indexed_at`,         `timestamptz`, [null until embedded],
  `edited_at`,          `timestamptz`, [null unless edited],
  `is_deleted`,         `bool`,        [soft delete],
)

#diagram(
  spacing: (26mm, 7mm),
  node-stroke: 1pt + black,
  edge-stroke: 0.8pt + black,
  mark-scale: 80%,

  node((1, 0), tbl, stroke: none, inset: 0pt, name: <t>),

  // writer of the three derived columns
  node((0, -0.15), align(center)[
    `set_content(doc)` \
    #text(0.8em)[writes the three ◆ columns \ atomically from one doc]
  ], name: <sc>),
  edge(<sc>, <t>, "-->", label: [derives], label-side: left),

  // indexes
  node((2, -0.55), align(left)[
    *`ix_messages_channel_sent_at`* \
    #text(0.82em)[B-tree · `(channel_id, sent_at)`]
  ], name: <i1>),
  node((2, 0), align(left)[
    *`ix_messages_content_gin`* \
    #text(0.82em)[GIN · `content`]
  ], name: <i2>),
  node((2, 0.55), align(left)[
    *`ix_messages_mentioned_user_ids_gin`* \
    #text(0.82em)[GIN · `mentioned_user_ids`]
  ], name: <i3>),
  edge(<i1>, <t>, "->"),
  edge(<i2>, <t>, "->"),
  edge(<i3>, <t>, "->"),
)
