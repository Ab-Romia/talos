import { api } from './api'

export const permissionsService = {
  getRoles(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/roles`)
  },

  getRole(workspaceId, roleId) {
    return api.get(`/api/workspaces/${workspaceId}/roles/${roleId}`)
  },

  createRole(workspaceId, { name, priority, description }) {
    const data = { name, priority }
    if (description != null) data.description = description
    return api.postForm(`/api/workspaces/${workspaceId}/roles`, data)
  },

  updateRole(workspaceId, roleId, fields) {
    return api.putForm(`/api/workspaces/${workspaceId}/roles/${roleId}`, fields)
  },

  deleteRole(workspaceId, roleId) {
    return api.delete(`/api/workspaces/${workspaceId}/roles/${roleId}`)
  },

  setRolePermissions(workspaceId, roleId, permissions) {
    return api.put(
      `/api/workspaces/${workspaceId}/roles/${roleId}/permissions`,
      permissions,
    )
  },

  setRoleMembers(workspaceId, roleId, memberIds) {
    return api.putForm(
      `/api/workspaces/${workspaceId}/roles/${roleId}/members`,
      { member_ids: memberIds },
    )
  },

  getChannelOverrides(channelId) {
    return api.get(`/api/channels/${channelId}/roles`)
  },

  getChannelOverride(channelId, roleId) {
    return api.get(`/api/channels/${channelId}/roles/${roleId}`)
  },

  createChannelOverride(channelId, roleId) {
    return api.post(`/api/channels/${channelId}/roles/${roleId}`)
  },

  updateChannelOverride(channelId, roleId, { allow, deny }) {
    return api.putForm(`/api/channels/${channelId}/roles/${roleId}`, {
      allow_permissions: allow,
      deny_permissions: deny,
    })
  },

  deleteChannelOverride(channelId, roleId) {
    return api.delete(`/api/channels/${channelId}/roles/${roleId}`)
  },

  myPermissions(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/my_permissions`)
  },

  myChannelPermissions(channelId) {
    return api.get(`/api/channels/${channelId}/my_permissions`)
  },
}
