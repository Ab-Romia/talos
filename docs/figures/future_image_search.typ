// Future multimodal (image) search branch reusing the shared retrieval index.
// Included via #figure(include "figures/future_image_search.typ", ...).
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge
#import fletcher.shapes: cylinder

#let proposed = (paint: black, dash: "dashed")

#diagram(
  spacing: (32mm, 15mm),
  node-stroke: 1pt + black,
  edge-stroke: 0.8pt + black,
  mark-scale: 80%,

  // current text lane
  node((0, 0), align(center)[*Documents* \ #text(0.82em)[PDF · DOCX · text]], name: <docs>),
  node((1, 0), align(center)[*Text embedder* \ #text(0.82em)[`all-MiniLM-L6-v2`]], name: <txt>),
  edge(<docs>, <txt>, "->", label: [chunks]),

  // proposed image lane (dashed = future)
  node((0, 1), align(center)[*Images* \ #text(0.82em)[photos · figures · scans]], stroke: proposed, name: <imgs>),
  node((1, 1), align(center)[*Image embedder* \ #text(0.82em)[CLIP-style multimodal]], stroke: proposed, name: <img>),
  edge(<imgs>, <img>, "->", stroke: proposed),

  // shared retrieval index
  node((2, 0.5), align(center)[*Retrieval index* \ #text(0.82em)[Milvus · one shared store]],
    shape: cylinder, inset: 10pt, name: <index>),
  edge(<txt>, <index>, "->", label: [vectors], label-side: left),
  edge(<img>, <index>, "->", stroke: proposed, label: [vectors], label-side: right),

  // unified query / results
  node((3, 0), align(center)[*Query* \ #text(0.82em)[text _or_ image]], name: <query>),
  node((3, 1), align(center)[*Ranked results* \ #text(0.82em)[same contract]], name: <res>),
  edge(<query>, <index>, "->", label: [embed → search], label-side: right),
  edge(<index>, <res>, "->", label: [top-k], label-side: left),

  node((1.5, 2.05), text(0.82em, fill: gray)[dashed = proposed / future work — only the embedding model changes], stroke: none),
)
