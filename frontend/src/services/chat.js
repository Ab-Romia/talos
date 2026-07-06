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

  createWorkspace(name, { channels, members } = {}) {
    // → { id, name, owner_id, channels:[{id,name}], skipped_members:[...] }
    //   (server provisions base role, permissions, membership + channels;
    //    channels/members are optional — server falls back to defaults).
    const body = { name }
    if (channels?.length) body.channels = channels
    if (members?.length) body.members = members
    return api.post('/api/workspaces', body)
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

  getMessage(channelId, messageId) {
    return api.get(`/api/channels/${channelId}/messages/${messageId}`)
  },

  searchMessages(channelId, { text, authorId, startDate, endDate, page = 1, pageSize = 20 } = {}) {
    const q = new URLSearchParams()
    if (text) q.set('text', text)
    if (authorId) q.set('author_id', authorId)
    if (startDate) q.set('start_date', startDate)
    if (endDate) q.set('end_date', endDate)
    q.set('page', String(page))
    q.set('page_size', String(pageSize))
    return api.get(`/api/channels/${channelId}/messages/search?${q.toString()}`)
  },

  getMyPermissions(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/my_permissions`)
  },

  listChannels(workspaceId, { skip = 0, limit = 50 } = {}) {
    const q = new URLSearchParams({ skip: String(skip), limit: String(limit) })
    return api.get(`/api/workspaces/${workspaceId}/channels?${q.toString()}`)
  },

  deleteChannel(workspaceId, channelId) {
    return api.delete(`/api/workspaces/${workspaceId}/channels/${channelId}`)
  },

  getChannelSettings(channelId) {
    return api.get(`/api/channels/${channelId}/settings`)
  },

  renameChannel(channelId, name) {
    return api.putForm(`/api/channels/${channelId}/settings/name`, { name })
  },

  updateChannelDescription(channelId, description) {
    return api.putForm(`/api/channels/${channelId}/settings/description`, { description: description || '' })
  },


  getWorkspaceSettings(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/settings`)
  },

  renameWorkspace(workspaceId, name) {
    return api.putForm(`/api/workspaces/${workspaceId}/settings/name`, { name })
  },

  updateWorkspaceDescription(workspaceId, description) {
    return api.putForm(`/api/workspaces/${workspaceId}/settings/description`, { description: description || '' })
  },

  updateWorkspaceIcon(workspaceId, iconId) {
    return api.putForm(`/api/workspaces/${workspaceId}/settings/icon`, { icon_id: iconId || '' })
  },

  leaveWorkspace(workspaceId) {
    return api.post(`/api/workspaces/${workspaceId}/settings/leave`)
  },

  deleteWorkspace(workspaceId) {
    return api.delete(`/api/workspaces/${workspaceId}/settings`)
  },

  searchUsers(query) {
    return api.get(`/api/auth/users/search?q=${encodeURIComponent(query)}`)
  },
}
