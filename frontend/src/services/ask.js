import { getSessionToken } from './api'

// The /ask endpoint streams the answer; with debug=true it appends
// "__ASK_DEBUG__" + the full RagTrace JSON after the answer text.
const DEBUG_MARKER = '__ASK_DEBUG__'

export const askService = {
  /**
   * Ask the channel AI with the full RAG trace enabled.
   * Returns { answer, trace } — trace is the parsed RagTrace object.
   * The exchange is persisted server-side like any other /ask call.
   */
  async askWithDebug(channelId, question) {
    const res = await fetch(`/api/channels/${channelId}/ask`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getSessionToken()}`,
      },
      body: JSON.stringify({ question, debug: true }),
    })
    if (!res.ok) {
      const payload = await res.json().catch(() => ({ detail: res.statusText }))
      throw { status: res.status, detail: payload.detail || 'Ask failed' }
    }
    const raw = await res.text()
    const idx = raw.indexOf(DEBUG_MARKER)
    if (idx === -1) return { answer: raw.trim(), trace: null }
    const answer = raw.slice(0, idx).trim()
    let trace = null
    try {
      trace = JSON.parse(raw.slice(idx + DEBUG_MARKER.length))
    } catch {
      trace = null
    }
    return { answer, trace }
  },
}
