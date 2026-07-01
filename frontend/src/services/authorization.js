import { api } from './api'

export const authorizationService = {
  summary() {
    return api.get('/api/authorization/summary')
  },

  platformRoles() {
    return api.get('/api/authorization/platform-roles')
  },

  platformPermissions() {
    return api.get('/api/authorization/platform-permissions')
  },
}
