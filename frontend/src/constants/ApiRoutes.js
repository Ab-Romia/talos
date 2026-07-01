// Core auth
export const AUTH_LOGIN = '/api/auth/password/'
export const AUTH_SIGNUP = '/api/auth/signup'
export const AUTH_LOGOUT = '/api/auth/logout'
export const AUTH_ME = '/api/auth/me'
export const AUTH_SUDO = '/api/auth/sudo'
export const AUTH_CHANGE_PASSWORD = '/api/auth/password/change'

// Sessions
export const AUTH_SESSIONS = '/api/auth/sessions'
export const AUTH_SESSION_DETAIL = (id) => `/api/auth/sessions/${id}`
export const AUTH_SESSION_BY_ID = (id) => `/api/auth/session/${id}`

// TOTP
export const AUTH_TOTP_CREATE = '/api/auth/totp/create'
export const AUTH_TOTP_REGISTER = '/api/auth/totp'
export const AUTH_TOTP_VERIFY = '/api/auth/totp/verify'
export const AUTH_TOTP_DELETE = '/api/auth/totp'

// Passkeys
export const AUTH_PASSKEY_REG_CHALLENGE = '/api/auth/passkey/register/challenge'
export const AUTH_PASSKEY_REGISTER = '/api/auth/passkey/register'
export const AUTH_PASSKEY_CHALLENGE = '/api/auth/passkey/challenge'
export const AUTH_PASSKEY_VERIFY = '/api/auth/passkey/verify'

// OAuth
export const AUTH_OAUTH_HANDOFF = '/api/auth/oauth/handoff'
export const AUTH_GOOGLE_LOGIN = '/api/auth/oauth/google'
export const AUTH_GITHUB_LOGIN = '/api/auth/oauth/github'

// Workspaces / chat
export const WORKSPACES = '/api/workspaces'
export const WORKSPACE_BY_ID = (id) => `/api/workspaces/${id}`
export const CHATROOMS = (wsId) => `/api/workspaces/${wsId}/chatrooms`
export const MESSAGES = (wsId, crId) =>
  `/api/workspaces/${wsId}/chatrooms/${crId}/messages`
export const MESSAGE_EVENTS_WS = (wsId, crId) => {
  const p = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${p}://${window.location.host}/api/workspaces/${wsId}/chatrooms/${crId}/events`
}

// AI + authorization
export const AI_CONFIG = '/api/ai/config'
export const AUTHZ_SUMMARY = '/api/authorization/summary'
export const AUTHZ_PLATFORM_ROLES = '/api/authorization/platform-roles'
export const AUTHZ_PLATFORM_PERMISSIONS = '/api/authorization/platform-permissions'

// Notifications
export const NOTIFICATIONS = '/api/notifications/'
export const NOTIFICATIONS_READ = (id) => `/api/notifications/${id}/read`
export const NOTIFICATIONS_READ_ALL = '/api/notifications/read-all'
export const NOTIFICATIONS_UNREAD_COUNT = '/api/notifications/unread-count'
export const NOTIFICATIONS_VAPID_KEY = '/api/notifications/vapid-public-key'
export const NOTIFICATIONS_SUBSCRIPTION = '/api/notifications/subscription'

// Files
export const FILES = (wsId) => `/api/workspaces/${wsId}/files`
export const FILE_BY_ID = (wsId, fId) => `/api/workspaces/${wsId}/files/${fId}`
export const FILE_DOWNLOAD = (wsId, fId) => `${FILE_BY_ID(wsId, fId)}/download`
export const FILE_THUMBNAIL = (wsId, fId) => `${FILE_BY_ID(wsId, fId)}/thumbnail`
export const FILE_STATUS = (wsId, fId) => `${FILE_BY_ID(wsId, fId)}/status`
export const FILE_RETRY = (wsId, fId) => `${FILE_BY_ID(wsId, fId)}/retry`
export const MESSAGE_ATTACH_FILE = (wsId, crId, mId) =>
  `/api/workspaces/${wsId}/chatrooms/${crId}/messages/${mId}/files`
