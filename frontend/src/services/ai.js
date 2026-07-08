import { api, getSessionToken } from './api'

// The current user's saved AI conversations in a workspace (newest first).
export function getAiConversations(workspaceId) {
  return api.get(`/api/workspaces/${workspaceId}/ai/conversations`)
}

// Messages of one saved conversation.
export function getAiConversationMessages(workspaceId, conversationId) {
  return api.get(`/api/workspaces/${workspaceId}/ai/conversations/${conversationId}/messages`)
}

export function deleteAiConversation(workspaceId, conversationId) {
  return api.delete(`/api/workspaces/${workspaceId}/ai/conversations/${conversationId}`)
}

// The assistant's user identity, so the mention picker can offer @Talos AI.
export function getBotIdentity(workspaceId) {
  return api.get(`/api/workspaces/${workspaceId}/ai/bot`)
}

// Streams a RAG answer from the workspace AI endpoint. The backend responds with
// a plain-text token stream (answer followed by a "Sources:" trailer). `onChunk`
// is called with each decoded piece as it arrives. Returns the conversation id
// the answer was saved under (the caller's id, or one the server minted).
export async function streamAiQuery(
  workspaceId,
  { question, history = [], fileIds = null, conversationId = null },
  onChunk,
  signal,
) {
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
      conversation_id: conversationId,
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

  const serverConversationId = res.headers.get('X-Conversation-Id') || conversationId

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    const text = decoder.decode(value, { stream: true })
    if (text) onChunk(text)
  }

  return serverConversationId
}
