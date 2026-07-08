import { api } from './api'

// Scoped AI-config endpoints (rag/settings_router.py). GET returns
// { effective, overrides, provenance }; PATCH takes a partial override
// (null clears a field back to the inherited value).
export const aiSettingsService = {
  getWorkspaceConfig(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/ai/config`)
  },

  patchWorkspaceConfig(workspaceId, partial) {
    return api.patch(`/api/workspaces/${workspaceId}/ai/config`, partial)
  },

  getChannelConfig(channelId) {
    return api.get(`/api/channels/${channelId}/ai/config`)
  },

  patchChannelConfig(channelId, partial) {
    return api.patch(`/api/channels/${channelId}/ai/config`, partial)
  },
}
