import { api } from './api'

// Team-chat REST client against the main backend.
//   GET  /api/workspaces                      -> [{id, name, owner_id, channels:[{id,name}]}]
//   GET  /api/channels/{id}/messages          -> [MessageSchema, ...] (newest first)
//   POST /api/channels/{id}/messages {text}   -> {id, sent_at}
// Realtime delivery of new messages is handled separately over Socket.IO
// (see services/socket.js); the backend broadcasts the full MessageSchema dict
// on the default `message` event to everyone in the channel room.
export const chatService = {
  getWorkspaces() {
    return api.get('/api/workspaces')
  },

  createWorkspace(name) {
    // → { id, name, owner_id, channels:[{id,name}] } (server provisions base role,
    //    permissions, membership + default channels).
    return api.post('/api/workspaces', { name })
  },

  createChannel(workspaceId, name) {
    return api.post(`/api/workspaces/${workspaceId}/channels`, { name })
  },

  getMessages(channelId, options = {}) {
    const { limit = 50, offset = 0 } = options
    const q = new URLSearchParams()
    q.set('limit', String(limit))
    q.set('offset', String(offset))
    return api.get(`/api/channels/${channelId}/messages?${q.toString()}`)
  },

  sendMessage(channelId, text) {
    return api.post(`/api/channels/${channelId}/messages`, { text })
  },

  getOnline(channelId) {
    return api.get(`/api/channels/${channelId}/online`)
  },

  getMembers(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/members`)
  },

  addMember(workspaceId, identifier) {
    return api.post(`/api/workspaces/${workspaceId}/members`, { identifier })
  },

  removeMember(workspaceId, memberId) {
    return api.delete(`/api/workspaces/${workspaceId}/members/${memberId}`)
  },

  getMyPermissions(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/my_permissions`)
  },
}
