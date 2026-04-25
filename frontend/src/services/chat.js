import { api } from './api'

export const chatService = {
  getWorkspaces() {
    return api.get('/api/workspaces')
  },

  createWorkspace(name) {
    return api.post('/api/workspaces', { name })
  },

  getWorkspace(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}`)
  },

  getChatrooms(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/chatrooms`)
  },

  createChatroom(workspaceId, name) {
    return api.post(`/api/workspaces/${workspaceId}/chatrooms`, { name })
  },

  getMessages(workspaceId, chatroomId, options = {}) {
    const { limit = 50, offset = 0, beforeId, afterId } = options
    const q = new URLSearchParams()
    q.set('limit', String(limit))
    q.set('offset', String(offset))
    if (beforeId) q.set('before_id', beforeId)
    if (afterId) q.set('after_id', afterId)
    return api.get(
      `/api/workspaces/${workspaceId}/chatrooms/${chatroomId}/messages?${q.toString()}`,
    )
  },

  async sendMessage(workspaceId, chatroomId, content, onChunk, onDone, onError, options = {}) {
    const { fileIds = null, onMessageId = null, regenerateForAiMessageId = null } = options
    const body = { content: content ?? '' }
    if (fileIds && fileIds.length) body.file_ids = fileIds
    if (regenerateForAiMessageId) {
      body.regenerate_for_ai_message_id = regenerateForAiMessageId
    }

    const res = await fetch(`/api/workspaces/${workspaceId}/chatrooms/${chatroomId}/messages`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      onError?.(err.detail || 'Failed to send message')
      return
    }

    const userMessageId = res.headers.get('X-User-Message-Id')
    if (userMessageId) onMessageId?.(userMessageId)

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const event = JSON.parse(line.slice(6))
          if (event.type === 'chunk') {
            onChunk?.(event.content)
          } else if (event.type === 'done') {
            onDone?.(event.sources || [], event.ai_message_id)
          } else if (event.type === 'error') {
            onError?.(event.content)
          }
        } catch {}
      }
    }
  },
}
