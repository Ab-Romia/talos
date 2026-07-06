import { api } from './api'

export const authService = {
  login(username, password) {
    return api.postForm('/api/auth/password/', { username, password })
  },

  // Step 1: request email verification. The backend only needs the email here;
  // it emails a link to /signup/complete?token=... (logged to app stdout in dev).
  signup(email) {
    return api.postForm('/api/auth/signup', { email })
  },

  // Step 2: finish signup using the token from the verification link.
  completeSignup({ email_token, username, name, password }) {
    return api.postAllowRedirect('/api/auth/signup/complete', {
      email_token,
      username,
      name,
      auth_info: [{ auth_type: 'password', password }],
    })
  },

  logout() {
    return api.post('/api/auth/logout')
  },

  me() {
    return api.get('/api/auth/me')
  },

  sudo(password) {
    return api.post('/api/auth/sudo', {
      auth_info: { auth_type: 'password', password },
    })
  },

  changePassword(newPassword) {
    return api.putQuery('/api/auth/password/change', { new_password: newPassword })
  },

  forgotPassword(email) {
    return api.postForm('/api/auth/password/forgot', { email })
  },

  resetPassword(resetToken, newPassword) {
    return api.putForm('/api/auth/password/reset', { reset_token: resetToken, reset_password: newPassword })
  },

  deleteAccount() {
    return api.delete('/api/auth/me')
  },

  listSessions() {
    return api.get('/api/auth/sessions')
  },

  getSession(sessionId) {
    return api.get(`/api/auth/sessions/${sessionId}`)
  },

  revokeSession(sessionId) {
    return api.delete(`/api/auth/session/${sessionId}`)
  },

  revokeAllSessions() {
    return api.delete('/api/auth/sessions')
  },

  totpCreate() {
    return api.post('/api/auth/totp/create')
  },

  totpRegister({ otp, jwt_totp_claims }) {
    return api.postForm('/api/auth/totp', { otp, jwt_totp_claims })
  },

  totpVerify(totp) {
    return api.postForm('/api/auth/totp/verify', { totp })
  },

  totpDelete() {
    return api.delete('/api/auth/totp')
  },

  passkeyRegistrationChallenge() {
    return api.post('/api/auth/passkey/register/challenge')
  },

  passkeyRegister({ jwt_challenge, credential, name }) {
    return api.postForm('/api/auth/passkey/register', {
      jwt_challenge,
      credential,
      name,
    })
  },

  passkeyAuthChallenge() {
    return api.post('/api/auth/passkey/challenge')
  },

  passkeyVerify({ jwt_challenge, credential }) {
    return api.postForm('/api/auth/passkey/verify', {
      jwt_challenge,
      credential,
    })
  },

  oauthHandoff(token) {
    return api.post('/api/auth/oauth/handoff', { token })
  },

  googleLogin() {
    window.location.href = '/api/auth/oauth/google'
  },

  githubLogin() {
    window.location.href = '/api/auth/oauth/github'
  },

  // → { google: bool, github: bool } — which providers the current account links.
  getConnections() {
    return api.get('/api/auth/oauth/connections')
  },

  // Link a provider to the CURRENT account (vs. sign-in). Mints a connect ticket
  // then hands off to the OAuth flow, returning to `/settings?connected=<p>`.
  async connectProvider(provider) {
    const { ticket } = await api.post(`/api/auth/oauth/${provider}/connect?origin=settings`)
    window.location.href = `/api/auth/oauth/${provider}?connect=${encodeURIComponent(ticket)}`
  },
}
