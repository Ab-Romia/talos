import { io } from 'socket.io-client'
import { getSessionToken } from './api'

// Shared Socket.IO connection to the backend team-chat realtime layer.
// The backend authenticates the handshake via `auth.token` (Bearer session token)
// and, on connect, auto-joins the socket into every `channel:{id}` room the user
// can access. We therefore keep ONE app-wide socket and let feature code attach
// its own event listeners (and clean them up) without tearing down the socket.
let socket = null
let socketToken = null

export function getSocket() {
  const token = getSessionToken()
  if (!token) return null

  // Re-create the socket if the auth token changed (e.g. re-login).
  if (socket && socketToken !== token) {
    disconnectSocket()
  }

  if (!socket) {
    socketToken = token
    socket = io({
      // same-origin; Vite proxies /socket.io -> backend :8000
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      auth: { token },
      autoConnect: true,
      reconnection: true,
    })
  }
  return socket
}

// Re-run the handshake so the backend re-computes room membership (rooms are
// only joined at connect time) — used after workspace/channel/DM/permission
// changes. This deliberately does NOT tear the socket down: manual
// disconnect()+connect() preserves every registered listener, so chat,
// notification and sync handlers keep working across the reconnect.
export function reconnectSocket() {
  const s = getSocket()
  if (!s) return null
  try {
    s.disconnect()
    s.connect()
  } catch {
    /* socket gone */
  }
  return s
}

export function disconnectSocket() {
  if (socket) {
    try {
      socket.removeAllListeners()
      socket.disconnect()
    } catch {
      /* already closed */
    }
  }
  socket = null
  socketToken = null
}

// Convenience: subscribe to the default `message` broadcast. Returns an
// unsubscribe function. `handler` receives the raw payload from the server.
export function onChatMessage(handler) {
  const s = getSocket()
  if (!s) return () => {}
  s.on('message', handler)
  return () => {
    try {
      s.off('message', handler)
    } catch {
      /* socket gone */
    }
  }
}

export function onNotification(handler) {
  const s = getSocket()
  if (!s) return () => {}
  const events = ['notification', 'notification.created', 'notification:new']
  events.forEach((evt) => s.on(evt, handler))
  return () => {
    try {
      events.forEach((evt) => s.off(evt, handler))
    } catch {
      /* socket gone */
    }
  }
}

export function onAiTyping(handler) {
  const s = getSocket()
  if (!s) return () => {}
  s.on('ai_typing', handler)
  return () => {
    try {
      s.off('ai_typing', handler)
    } catch {
      /* socket gone */
    }
  }
}

// Live token stream for an in-channel AI reply. Payload variants:
//   { channel_id, stream_id, status: 'start', sender_id }
//   { channel_id, stream_id, delta: '<chunk>' }
//   { channel_id, stream_id, status: 'end', message? , error? }
export function onAiStream(handler) {
  const s = getSocket()
  if (!s) return () => {}
  s.on('ai_stream', handler)
  return () => {
    try {
      s.off('ai_stream', handler)
    } catch {
      /* socket gone */
    }
  }
}

// Workspace-level realtime sync: membership, channel-list, DM and permission
// changes made by other users. Payload: { resource, workspace_id, action?, name? }.
export function onWorkspaceSync(handler) {
  const s = getSocket()
  if (!s) return () => {}
  s.on('workspace_sync', handler)
  return () => {
    try {
      s.off('workspace_sync', handler)
    } catch {
      /* socket gone */
    }
  }
}
