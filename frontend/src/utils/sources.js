// Collapse duplicate "Sources:" blocks in an AI answer. The authoritative
// citation list is appended last; if the model also wrote its own (despite the
// prompt), keep the answer body + only the final block.
export function dedupeSources(text) {
  if (!text) return text
  const parts = text.split(/\n+\s*Sources:\s*/i)
  if (parts.length <= 2) return text
  const body = parts[0].replace(/\s+$/, '')
  const last = parts[parts.length - 1].trim()
  return `${body}\n\nSources:\n${last}`
}
