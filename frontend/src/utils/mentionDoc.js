// Helpers for turning the plain-text composer value into the ProseMirror doc
// the backend stores, with `@Display Name` tokens lifted into mention nodes.

// Build inline nodes for one line of text, splitting out known mentions.
// `mentions` is [{ label, user_id }] — labels are matched as "@Label".
function inlineNodes(line, mentions) {
  if (!line) return []
  const tokens = (mentions || [])
    .filter((m) => m.label && m.user_id)
    .map((m) => ({ ...m, token: `@${m.label}` }))
    .sort((a, b) => b.token.length - a.token.length)

  const nodes = []
  let rest = line
  while (rest) {
    let hitIdx = -1
    let hit = null
    for (const t of tokens) {
      const idx = rest.indexOf(t.token)
      if (idx !== -1 && (hitIdx === -1 || idx < hitIdx)) {
        hitIdx = idx
        hit = t
      }
    }
    if (hit === null) {
      nodes.push({ type: 'text', text: rest })
      break
    }
    if (hitIdx > 0) nodes.push({ type: 'text', text: rest.slice(0, hitIdx) })
    nodes.push({ type: 'mention', attrs: { user_id: hit.user_id, label: hit.label } })
    rest = rest.slice(hitIdx + hit.token.length)
  }
  return nodes
}

// text + tracked mentions -> ProseMirror doc dict (paragraph per line).
export function buildMessageDoc(text, mentions) {
  const lines = String(text ?? '').split('\n')
  const content = lines.map((line) => {
    const inline = inlineNodes(line, mentions)
    return inline.length ? { type: 'paragraph', content: inline } : { type: 'paragraph' }
  })
  return { type: 'doc', content }
}

// Does the composer text still contain any of the tracked mention tokens?
export function activeMentions(text, mentions) {
  const t = String(text ?? '')
  return (mentions || []).filter((m) => m.label && t.includes(`@${m.label}`))
}

// Mention nodes present anywhere in a stored doc (for rendering).
export function docMentions(doc) {
  const found = []
  const walk = (node) => {
    if (!node || typeof node !== 'object') return
    if (node.type === 'mention' && node.attrs) found.push(node.attrs)
    for (const child of node.content || []) walk(child)
  }
  walk(doc)
  return found
}
