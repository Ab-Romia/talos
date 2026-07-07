// JSONB document tree vs the serialized string that ILIKE scans (src/chat/search.py).
// Included via #figure(include "figures/search_jsonb_vs_ilike.typ", ...).
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge

#let sct(body) = text(fill: luma(48%))[#raw(body)]      // structural tokens
#let cnt(body) = text(fill: black, weight: "bold")[#raw(body)] // user-visible text
#let uid(body) = text(style: "italic")[#raw(body)]      // uuid attr

#let serialized = box(width: 74mm)[
  #set text(0.82em)
  #sct("…\"content\":[{\"type\":\"text\",\"text\":")#cnt("\"Hey \"")#sct("},") \
  #sct("{\"type\":\"mention\",\"attrs\":{\"user_id\":")#uid("\"019f…\"") \
  #sct(",\"label\":")#cnt("\"Kyria\"")#sct("}},{\"type\":\"text\",") \
  #sct("\"text\":")#cnt("\", see the report\"")#sct("}]…")
]

#diagram(
  spacing: (15mm, 12mm),
  node-stroke: 1pt + black,
  edge-stroke: 0.8pt + black,
  node-inset: 7pt,
  mark-scale: 80%,

  // panel headers
  node((0.15, -0.75), [*`content`* — JSONB document tree], stroke: none),
  node((3.2, -0.75), [*`content::text`* — what `ILIKE '%q%'` scans], stroke: none),

  // left: JSONB tree
  node((0.15, 0), `doc`, name: <doc>),
  node((0.15, 1), `paragraph`, name: <para>),
  node((-0.7, 2), align(center)[`text` \ #text(0.8em)[“Hey ”]], shape: rect, name: <t1>),
  node((0.2, 2), align(center)[`mention` \ #text(0.8em)[“Kyria”]], name: <men>),
  node((1.15, 2), align(center)[`text` \ #text(0.8em)[“, see the report”]], name: <t2>),
  edge(<doc>, <para>, marks: (none, none)),
  edge(<para>, <t1>, marks: (none, none)),
  edge(<para>, <men>, marks: (none, none)),
  edge(<para>, <t2>, marks: (none, none)),

  // right: serialized string
  node((3.2, 1), serialized, name: <str>),
  edge(<para>, <str>, "->", label: [cast `::text`], label-side: left),

  // legend
  node((3.2, 2.15), align(left)[
    #set text(0.8em)
    #text(fill: luma(48%))[▪] structural (node types · keys · attrs) \
    #text(weight: "bold")[▪] user-visible text · #emph[▪] UUID (`user_id`)
  ], stroke: none),

  // callouts
  node((0.15, 3.3), align(left)[
    *False positives* \
    #set text(0.83em)
    querying `text` / `paragraph` / `mention` matches the \
    structural node-type tokens → hits every message; a \
    UUID fragment matches `user_id`, never typed text.
  ], name: <fp>),
  node((3.2, 3.3), align(left)[
    *False negatives* \
    #set text(0.83em)
    user text is split across sibling nodes, so a phrase \
    spanning a mention isn't contiguous: searching \
    “Kyria,” fails — “Kyria” is a label, “,” starts \
    the next `text` node.
  ], name: <fn>),
)
