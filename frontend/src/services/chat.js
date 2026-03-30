import { api } from './api'

export const chatService = {
  getWorkspaces() {
    return api.get('/api/workspaces')
  },

  createWorkspace(name) {
    return api.post('/api/workspaces', { name })
  },

  getChatrooms(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/chatrooms`)
  },

  createChatroom(workspaceId, name) {
    return api.post(`/api/workspaces/${workspaceId}/chatrooms`, { name })
  },

  getMessages(workspaceId, chatroomId, limit = 50) {
    return api.get(`/api/workspaces/${workspaceId}/chatrooms/${chatroomId}/messages?limit=${limit}`)
  },

  async sendMessage(workspaceId, chatroomId, content, onChunk, onDone, onError) {
    const res = await fetch(`/api/workspaces/${workspaceId}/chatrooms/${chatroomId}/messages`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      onError?.(err.detail || 'Failed to send message')
      return
    }

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
            onDone?.(event.sources || [])
          } else if (event.type === 'error') {
            onError?.(event.content)
          }
        } catch {
          // ignore parse errors
        }
      }
    }
  },
}
