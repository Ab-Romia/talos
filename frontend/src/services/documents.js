import { api, getSessionToken } from './api'

const PROTO = 'm'

export const documentService = {
  list(workspaceId, { cursor = null, limit = 100, contentType = null } = {}) {
    const params = new URLSearchParams()
    params.set('limit', String(limit))
    if (cursor) params.set('cursor', cursor)
    if (contentType) params.set('content_type', contentType)
    return api.get(`/api/workspaces/${workspaceId}/files/${PROTO}?${params.toString()}`)
  },

  delete(workspaceId, fileId) {
    return api.delete(`/api/workspaces/${workspaceId}/files/${fileId}`)
  },

  rename(workspaceId, fileId, filename) {
    return api.patch(`/api/workspaces/${workspaceId}/files/${PROTO}/${fileId}`, { filename })
  },

  upload(workspaceId, file) {
    const formData = new FormData()
    formData.append('file', file)
    return api.upload(`/api/workspaces/${workspaceId}/documents`, formData)
  },

  async download(workspaceId, fileId, filename) {
    const res = await fetch(`/api/workspaces/${workspaceId}/documents/${fileId}`, {
      credentials: 'include',
      headers: { Authorization: `Bearer ${getSessionToken()}` },
    })
    if (!res.ok) {
      const payload = await res.json().catch(() => ({ detail: res.statusText }))
      throw { status: res.status, detail: payload.detail || 'Download failed' }
    }
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename || 'download'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  },
}
