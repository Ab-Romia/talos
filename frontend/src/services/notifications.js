import { api } from './api'
import {
  NOTIFICATIONS,
  NOTIFICATIONS_READ,
  NOTIFICATIONS_READ_ALL,
  NOTIFICATIONS_UNREAD_COUNT,
  NOTIFICATIONS_UNREAD_BY_CHANNEL,
  NOTIFICATIONS_CHANNEL_READ,
  NOTIFICATIONS_VAPID_KEY,
  NOTIFICATIONS_SUBSCRIPTION,
  NOTIFICATIONS_PREFERENCES,
} from '../constants/ApiRoutes'

export const notificationsService = {
  list({ limit = 20, offset = 0, unreadOnly = false, afterId = null } = {}) {
    const q = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
      unread_only: String(unreadOnly),
    })
    if (afterId) q.set('after_notification_id', afterId)
    return api.get(`${NOTIFICATIONS}?${q.toString()}`)
  },

  unreadCount() {
    return api.get(NOTIFICATIONS_UNREAD_COUNT)
  },

  unreadByChannel() {
    return api.get(NOTIFICATIONS_UNREAD_BY_CHANNEL)
  },

  markChannelRead(channelId) {
    return api.post(NOTIFICATIONS_CHANNEL_READ(channelId))
  },

  getPreferences() {
    return api.get(NOTIFICATIONS_PREFERENCES)
  },

  updatePreferences(prefs) {
    return api.put(NOTIFICATIONS_PREFERENCES, prefs)
  },

  markRead(notificationId) {
    return api.post(NOTIFICATIONS_READ(notificationId))
  },

  markAllRead() {
    return api.post(NOTIFICATIONS_READ_ALL)
  },

  vapidPublicKey() {
    return api.get(NOTIFICATIONS_VAPID_KEY)
  },

  listSubscriptions() {
    return api.get(NOTIFICATIONS_SUBSCRIPTION)
  },

  subscribe({ endpoint, keys, encodings, expiration_time }) {
    return api.post(NOTIFICATIONS_SUBSCRIPTION, {
      endpoint,
      keys,
      encodings,
      expiration_time,
    })
  },

  unsubscribe(endpoint) {
    return fetch(NOTIFICATIONS_SUBSCRIPTION, {
      method: 'DELETE',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(endpoint),
    }).then((res) => {
      if (!res.ok) {
        return res
          .json()
          .catch(() => ({ detail: res.statusText }))
          .then((err) => Promise.reject({ status: res.status, ...err }))
      }
      if (res.status === 204 || res.headers.get('content-length') === '0') {
        return null
      }
      return res.json()
    })
  },
}

export function isPushSupported() {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

export function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const output = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) {
    output[i] = raw.charCodeAt(i)
  }
  return output
}

async function getServiceWorkerRegistration() {
  const existing = await navigator.serviceWorker.getRegistration('/')
  if (existing) return existing
  return navigator.serviceWorker.register('/sw.js')
}

export async function enableWebPush() {
  if (!isPushSupported()) {
    throw new Error('Web Push is not supported in this browser')
  }

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new Error('Notification permission denied')
  }

  const registration = await getServiceWorkerRegistration()
  await navigator.serviceWorker.ready

  const { vapid_public_key: vapidKey } = await notificationsService.vapidPublicKey()
  if (!vapidKey) {
    throw new Error('Server VAPID key not configured')
  }

  let subscription = await registration.pushManager.getSubscription()
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidKey),
    })
  }

  const json = subscription.toJSON()
  await notificationsService.subscribe({
    endpoint: json.endpoint,
    keys: json.keys,
    expiration_time: json.expirationTime
      ? new Date(json.expirationTime).toISOString()
      : null,
  })

  return json.endpoint
}

export async function disableWebPush() {
  if (!isPushSupported()) return null

  const registration = await navigator.serviceWorker.getRegistration('/')
  if (!registration) return null

  const subscription = await registration.pushManager.getSubscription()
  if (!subscription) return null

  const { endpoint } = subscription
  try {
    await notificationsService.unsubscribe(endpoint)
  } catch (err) {
    if (err?.status !== 404) throw err
  }
  await subscription.unsubscribe()
  return endpoint
}

export async function getCurrentPushEndpoint() {
  if (!isPushSupported()) return null
  const registration = await navigator.serviceWorker.getRegistration('/')
  if (!registration) return null
  const subscription = await registration.pushManager.getSubscription()
  return subscription?.endpoint ?? null
}
