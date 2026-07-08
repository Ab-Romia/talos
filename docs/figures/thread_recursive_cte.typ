// Recursive-CTE thread assembly (get_thread design over reply_to_id self-FK).
// Included via #figure(include "figures/thread_recursive_cte.typ", ...).
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge

#let sql-src = "WITH RECURSIVE thread AS (
    SELECT * FROM messages WHERE id = :root_id       -- anchor (base case)
  UNION ALL
    SELECT m.* FROM messages m
    JOIN thread t ON m.reply_to_id = t.id            -- recurse on the self-FK
)  SELECT * FROM thread;"

#let ftbl = table(
  columns: 2,
  inset: (x: 8pt, y: 3pt),
  align: left,
  stroke: 0.5pt + luma(60%),
  table.header([`id`], [`reply_to_id`]),
  `M1`, `NULL`,
  `M2`, `M1`,
  `M3`, `M1`,
  `M4`, `M2`,
)

#let ptree = "M1
├─ M2
│    └─ M4
└─ M3"

#diagram(
  spacing: (16mm, 12mm),
  node-stroke: 1pt + black,
  edge-stroke: 0.8pt + black,
  node-inset: 7pt,
  mark-scale: 80%,

  // recursive CTE source, spanning the top
  node((3.15, -1.6), raw(sql-src, block: true), stroke: 1pt + black, inset: 9pt, name: <sql>),

  // stage headers
  node((0, 0), [*① Anchor*], stroke: none),
  node((2.3, 0), [*② Union passes*], stroke: none),
  node((4.4, 0), [*③ Flat result*], stroke: none),
  node((6.3, 0), [*④ Python tree — O(n)*], stroke: none),

  // ① anchor
  node((0, 1.3), [`M1` \ #text(0.8em)[root]], shape: rect, name: <a>),

  // ② union tree
  node((2.3, 0.9), `M1`, name: <u1>),
  node((1.95, 1.6), `M2`, name: <u2>),
  node((2.65, 1.6), `M3`, name: <u3>),
  node((1.95, 2.3), `M4`, name: <u4>),
  edge(<u1>, <u2>, marks: (none, none)),
  edge(<u1>, <u3>, marks: (none, none)),
  edge(<u2>, <u4>, marks: (none, none)),

  // ③ flat result
  node((4.4, 1.4), ftbl, stroke: none, inset: 0pt, name: <f>),

  // ④ python tree
  node((6.3, 1.4), align(left, raw(ptree, block: true)), shape: rect, name: <p>),

  // pipeline arrows
  edge(<a>, <u1>, "->", label: [seed root], label-side: right),
  edge(<u3>, <f>, "->", label: [collect rows], label-side: right),
  edge(<f>, <p>, "->", label: [index by `id`, \ wire `children`], label-side: right),
)
