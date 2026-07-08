// Two-query search lifecycle (src/chat/search.py + router pagination).
// Included via #figure(include "figures/search_two_query_lifecycle.typ", ...).
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge

#let ll = (paint: gray, dash: "dashed")
#let sql(body) = text(0.85em, raw(body))

#diagram(
  spacing: (40mm, 11mm),
  node-stroke: 1pt + black,
  edge-stroke: 0.8pt + black,
  mark-scale: 80%,

  // participants
  node((0, 0), [*Client*], shape: rect, inset: 8pt),
  node((1, 0), [*Router*], shape: rect, inset: 8pt),
  node((2, 0), [*`search_messages`*], shape: rect, inset: 8pt),
  node((3, 0), [*Postgres*], shape: rect, inset: 8pt),

  // lifelines
  edge((0, 0), (0, 10.4), stroke: ll, marks: (none, none)),
  edge((1, 0), (1, 10.4), stroke: ll, marks: (none, none)),
  edge((2, 0), (2, 10.4), stroke: ll, marks: (none, none)),
  edge((3, 0), (3, 10.4), stroke: ll, marks: (none, none)),

  // request
  edge((0, 1.5), (1, 1.5), "->", label: align(left)[GET `/messages/search` \ `?q=report&page=2&page_size=20`], label-side: left),

  // router maps page → offset/limit
  edge((1, 2.9), (2, 2.9), "->", label: align(center)[`search(q, offset=20, limit=20)` \ #text(0.82em, fill: gray)[page → offset: (2−1)·20]]),

  // query 1: COUNT
  edge((2, 4.1), (3, 4.1), "->", label: [① #h(3pt) `COUNT(*)` · filtered set]),
  edge((3, 4.9), (2, 4.9), "->", label: [`total = 137`]),

  // query 2: SELECT page
  edge((2, 6.3), (3, 6.3), "->", label: align(center)[② #h(3pt) #sql("SELECT … WHERE …") \ #sql("ORDER BY sent_at DESC") \ #sql("LIMIT 20 OFFSET 20")]),
  edge((3, 7.6), (2, 7.6), "->", label: [20 rows]),

  // back to router
  edge((2, 8.6), (1, 8.6), "->", label: [`(messages, total)`]),

  // response envelope
  edge((1, 9.8), (0, 9.8), "->", label: align(left)[#sql("{ results:[…20], page:2, page_size:20,") \ #sql("  total:137, total_pages:7,") \ #sql("  has_next:true, has_previous:true }")], label-side: left),
)
