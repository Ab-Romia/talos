// ProseMirror node hierarchy for chat_schema (src/chat/schema.py).
// Included via #figure(include "figures/prosemirror_node_hierarchy.typ", ...).
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge

#diagram(
  spacing: (13mm, 15mm),
  node-stroke: 1pt + black,
  node-inset: 8pt,
  edge-stroke: 0.8pt + black,
  mark-scale: 80%,

  node((1, 0), `doc`, name: <doc>),

  node((1, 1), align(center)[
    *block nodes* \
    #set text(0.8em)
    `paragraph` · `heading` · `blockquote` \
    `code_block` · `bullet_list` · `ordered_list` \
    `list_item` · `hard_break` · `horizontal_rule`
  ], name: <block>),

  node((1, 2), align(center)[
    *inline group* \
    #set text(0.8em)
    `text` · `image`
  ], name: <inline>),

  node((0, 3), `mention`, name: <m>),
  node((1, 3), `reference`, name: <r>),
  node((2, 3), `slash_command`, name: <s>),

  node((1, 3.85), text(0.78em)[`atom: true` — inline leaves, no children],
    stroke: none, inset: 3pt),

  node((2.7, 1.5), align(left)[
    *mark set* \
    #set text(0.8em)
    `strong` / `bold` \
    `em` / `italic` \
    `underline` · `strike` \
    `code` · `link`
  ], stroke: (paint: black, dash: "dashed"), name: <marks>),

  edge(<doc>, <block>, "->", label: `block+`, label-side: right),
  edge(<block>, <inline>, "->", label: `inline*`, label-side: right),
  edge(<inline>, <m>, "->"),
  edge(<inline>, <r>, "->"),
  edge(<inline>, <s>, "->"),
  edge(<inline>, <marks>, "-->", label: [applied to \ inline content], label-side: left),
)
