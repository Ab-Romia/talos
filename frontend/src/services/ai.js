import { getSessionToken } from './api'

// Streams a RAG answer from the workspace AI endpoint. The backend responds with
// a plain-text token stream (answer followed by a "Sources:" trailer). `onChunk`
// is called with each decoded piece as it arrives.
export async function streamAiQuery(workspaceId, { question, history = [], fileIds = null }, onChunk, signal) {
  const token = getSessionToken()
  const res = await fetch(`/api/workspaces/${workspaceId}/ai/query`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token && { Authorization: `Bearer ${token}` }),
    },
    body: JSON.stringify({
      question,
      history: history.map((m) => ({ role: m.role, content: m.content })),
      file_ids: fileIds,
    }),
    signal,
  })

  if (!res.ok || !res.body) {
    let detail = res.statusText
    try {
      const payload = await res.json()
      detail = payload.detail || detail
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new Error(typeof detail === 'string' ? detail : 'The assistant request failed.')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    const text = decoder.decode(value, { stream: true })
    if (text) onChunk(text)
  }
}
