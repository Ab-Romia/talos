import { api } from './api'

export const authService = {
  login(username, password) {
    return api.postForm('/api/auth/password/', { username, password })
  },

  signup({ username, primary_email, password, name }) {
    return api.postForm('/api/auth/signup', { username, primary_email, password, name })
  },

  logout() {
    return api.post('/api/auth/logout')
  },

  me() {
    return api.get('/api/auth/me')
  },

  googleLogin() {
    window.location.href = '/api/auth/oauth/google'
  },

  githubLogin() {
    window.location.href = '/api/auth/oauth/github'
  },
}
