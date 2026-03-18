import { api } from './api'

export const authService = {
  login(username, password) {
    return api.postForm('/auth/password/', { username, password })
  },

  signup({ username, primary_email, password, name }) {
    return api.post('/auth/signup', { username, primary_email, password, name })
  },

  logout() {
    return api.post('/auth/logout')
  },

  refresh() {
    return api.post('/auth/refresh')
  },

  googleLogin() {
    window.location.href = '/auth/google/login'
  },

  githubLogin() {
    window.location.href = '/auth/github'
  },
}
