import { api } from './api'

export const documentService = {
  async upload(workspaceId, file, chatroomId = null) {
    const formData = new FormData()
    formData.append('file', file)
    const params = chatroomId ? `?chatroom_id=${chatroomId}` : ''
    const res = await fetch(`/api/workspaces/${workspaceId}/files${params}`, {
      method: 'POST',
      credentials: 'include',
      body: formData,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw err
    }
    return res.json()
  },

  list(workspaceId, { cursor = null, limit = 20, chatroomId = null, contentType = null } = {}) {
    const params = new URLSearchParams()
    params.set('limit', String(limit))
    if (cursor) params.set('cursor', cursor)
    if (chatroomId) params.set('chatroom_id', chatroomId)
    if (contentType) params.set('content_type', contentType)
    return api.get(`/api/workspaces/${workspaceId}/files?${params.toString()}`)
  },

  getMetadata(workspaceId, fileId) {
    return api.get(`/api/workspaces/${workspaceId}/files/${fileId}`)
  },

  getStatus(workspaceId, fileId) {
    return api.get(`/api/workspaces/${workspaceId}/files/${fileId}/status`)
  },

  getDownloadUrl(workspaceId, fileId) {
    return api.get(`/api/workspaces/${workspaceId}/files/${fileId}/download`)
  },

  getThumbnailUrl(workspaceId, fileId) {
    return api.get(`/api/workspaces/${workspaceId}/files/${fileId}/thumbnail`)
  },

  retry(workspaceId, fileId) {
    return api.post(`/api/workspaces/${workspaceId}/files/${fileId}/retry`)
  },

  delete(workspaceId, fileId) {
    return api.delete(`/api/workspaces/${workspaceId}/files/${fileId}`)
  },

  attachToMessage(workspaceId, chatroomId, messageId, fileId) {
    return api.post(
      `/api/workspaces/${workspaceId}/chatrooms/${chatroomId}/messages/${messageId}/files?file_id=${fileId}`,
    )
  },
}
