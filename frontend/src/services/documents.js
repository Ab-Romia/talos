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

  list(workspaceId, cursor = null, limit = 20) {
    let url = `/api/workspaces/${workspaceId}/files?limit=${limit}`
    if (cursor) url += `&cursor=${cursor}`
    return api.get(url)
  },

  getStatus(workspaceId, fileId) {
    return api.get(`/api/workspaces/${workspaceId}/files/${fileId}/status`)
  },

  delete(workspaceId, fileId) {
    return api.delete(`/api/workspaces/${workspaceId}/files/${fileId}`)
  },

  getDownloadUrl(workspaceId, fileId) {
    return api.get(`/api/workspaces/${workspaceId}/files/${fileId}/download`)
  },
}
