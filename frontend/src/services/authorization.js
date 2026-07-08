import { api } from './api'

// Access/permissions for the current user within a workspace.
//   GET /api/workspaces/{id}/my_permissions -> { workspace_id, is_owner, permissions:[str] }
export const authorizationService = {
  myPermissions(workspaceId) {
    return api.get(`/api/workspaces/${workspaceId}/my_permissions`)
  },
}
