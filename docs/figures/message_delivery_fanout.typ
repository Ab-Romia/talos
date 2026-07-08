// Message delivery fan-out (src/chat/realtime.py + shared store_message service).
// Included via #figure(include "figures/message_delivery_fanout.typ", ...).
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge

#diagram(
  spacing: (34mm, 13mm),
  node-stroke: 1pt + black,
  edge-stroke: 0.8pt + black,
  mark-scale: 80%,

  node((0, 1), align(center)[*Sender* \ #text(0.82em)[web · mobile · script]], name: <sender>),

  // two transports
  node((1, 0.35), align(center)[`message` event \ #text(0.82em)[Socket.IO]], name: <sock>),
  node((1, 1.65), align(center)[POST `/messages` \ #text(0.82em)[REST]], name: <rest>),

  // shared service
  node((2, 1), align(left)[
    *`store_message()`* \
    #set text(0.82em)
    · validate (`MessageCreateSchema`) \
    · persist → `set_content()` \
    · extract `mentioned_user_ids`
  ], name: <store>),

  // fan-out targets
  node((3, 0.3), align(left)[
    *room* `channel:{id}` \
    #set text(0.82em)
    `sio.send(…, skip_sid=sender)` \
    broadcast to every subscriber \
    — sender skipped (already has it)
  ], name: <chan>),

  node((3, 1.55), align(left)[
    *room* `user:{uid}` #text(0.82em)[ · per mention] \
    #set text(0.82em)
    flag-modified copy → each \
    mentioned user's personal room
  ], name: <pers>),

  node((3, 2.5), align(left)[#text(0.86em)[`@Talos` mention → additionally `maybe_ai_reply`]],
    stroke: (dash: "dashed"), inset: 6pt, name: <ai>),

  // edges
  edge(<sender>, <sock>, "->"),
  edge(<sender>, <rest>, "->"),
  edge(<sock>, <store>, "->"),
  edge(<rest>, <store>, "->"),
  edge(<store>, <chan>, "->", label: [broadcast], label-side: left),
  edge(<store>, <pers>, "->", label: [notify mentions], label-side: right),
  edge(<pers>, <ai>, "-->"),

  // ack back to sender
  edge(<store>, <sender>, "-->", bend: 42deg, label: [ack `{ delivered_to }`], label-side: right),
)
