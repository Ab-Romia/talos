import { api } from './api'

export const aiSettingsService = {
  getConfig() {
    return api.get('/api/ai/config')
  },

  patchConfig(partial) {
    return api.patch('/api/ai/config', partial)
  },
}
