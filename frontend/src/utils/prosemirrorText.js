// Plain text of a message content value.
// The backend stores chat message content as a ProseMirror JSON doc
// (rich-msg contract); older/assistant paths may still deliver strings.
// Mirrors src/rag/message_text.py doc_text on the backend.

function nodeText(node) {
  if (node == null || typeof node !== 'object') return ''
  const t = node.type
  if (t === 'text') return node.text || ''
  if (t === 'mention') {
    const label = node.attrs?.label || ''
    return label ? `@${label}` : ''
  }
  if (t === 'reference') return node.attrs?.label || ''
  if (t === 'slash_command') {
    const command = node.attrs?.command || ''
    return command ? `/${command}` : ''
  }
  const children = node.content || []
  const sep = t === 'doc' ? '\n' : ''
  return children.map(nodeText).join(sep)
}

export function docText(content) {
  if (content == null) return ''
  if (typeof content === 'string') return content
  if (typeof content === 'object') return nodeText(content)
  return String(content)
}
