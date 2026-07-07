// Future scaled AI-serving architecture (cache + autoscaled inference + sharded vector DB).
// Included via #figure(include "figures/future_scaled_ai_serving.typ", ...).
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge
#import fletcher.shapes: cylinder

#diagram(
  spacing: (30mm, 13mm),
  node-stroke: 1pt + black,
  edge-stroke: 0.8pt + black,
  mark-scale: 80%,

  node((0, 0.5), align(center)[*Clients* \ #text(0.82em)[at scale]], name: <cli>),
  node((1, 0.5), align(center)[*Load balancer*], name: <lb>),
  edge(<cli>, <lb>, "->"),

  // API tier
  node((2, 0), align(center)[API instance], name: <a1>),
  node((2, 1), align(center)[API instance], name: <a2>),
  edge(<lb>, <a1>, "->"),
  edge(<lb>, <a2>, "->"),

  // cache in front of inference
  node((3, -0.35), align(center)[*Cache layer* \ #text(0.82em)[response / semantic] \ #text(0.82em, fill: gray)[hit → skip inference]], name: <cache>),

  // inference pool
  node((3, 1.05), align(center)[
    *Inference service* \
    #set text(0.82em)
    LLM replica · GPU \
    LLM replica · GPU \
    #text(fill: gray)[distributed / autoscaled]
  ], name: <inf>),

  edge(<a1>, <cache>, "->", label: [query], label-side: left),
  edge(<a2>, <cache>, "->"),
  edge(<cache>, <inf>, "->", label: [miss], label-side: right),

  // sharded vector DB
  node((4, 0.5), align(center)[*Vector DB* \ #text(0.82em)[sharded] \ #text(0.8em)[shard 1 · 2 · 3 · …]],
    shape: cylinder, inset: 11pt, name: <vdb>),
  edge(<inf>, <vdb>, "->", label: [retrieve], label-side: right),
)
