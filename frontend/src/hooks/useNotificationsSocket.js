import { useEffect, useRef } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import {
  loadUnreadCount,
  syncPushStatus,
  receivedRealtime,
} from '../store/notificationsSlice'
import { onNotification, getSocket, onChatMessage } from '../services/socket'
import { docText } from '../utils/prosemirrorText'

const POLL_INTERVAL_MS = 30_000

export default function useNotificationsSocket() {
  const dispatch = useDispatch()
  const isAuthenticated = useSelector((s) => s.auth.isAuthenticated)
  const userId = useSelector((s) => s.auth.user?.id)
  const pollTimerRef = useRef(null)

  useEffect(() => {
    if (!isAuthenticated) return

    dispatch(loadUnreadCount())
    dispatch(syncPushStatus())

    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }

    const offNotif = onNotification((payload) => {
      if (!payload) return
      if (payload.id && payload.title) {
        dispatch(receivedRealtime(payload))
      } else {
        dispatch(loadUnreadCount())
      }
    })

    const offMsg = onChatMessage((raw) => {
      let m = raw
      if (m && typeof m.message === 'string') {
        try { m = JSON.parse(m.message) } catch { return }
      }
      if (!m || !m.sender_id || m.sender_id === userId) return

      dispatch(loadUnreadCount())

      if ('Notification' in window && Notification.permission === 'granted') {
        try {
          new Notification(m.channel_name ? `#${m.channel_name}` : 'New message', {
            body: docText(m.content).slice(0, 200),
            icon: '/favicon.svg',
            tag: m.id || `msg-${Date.now()}`,
          })
        } catch (err) {
          console.error('[notif] OS notification error:', err)
        }
      }
    })

    const socket = getSocket()

    const startPolling = () => {
      if (pollTimerRef.current) return
      pollTimerRef.current = setInterval(() => {
        if (document.visibilityState === 'visible') {
          dispatch(loadUnreadCount())
        }
      }, POLL_INTERVAL_MS)
    }

    const stopPolling = () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }

    const handleConnect = () => stopPolling()
    const handleDisconnect = () => startPolling()
    const handleConnectError = () => startPolling()

    if (socket) {
      socket.on('connect', handleConnect)
      socket.on('disconnect', handleDisconnect)
      socket.on('connect_error', handleConnectError)
      if (!socket.connected) startPolling()
    } else {
      startPolling()
    }

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        dispatch(loadUnreadCount())
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      offNotif()
      offMsg()
      if (socket) {
        socket.off('connect', handleConnect)
        socket.off('disconnect', handleDisconnect)
        socket.off('connect_error', handleConnectError)
      }
      document.removeEventListener('visibilitychange', handleVisibility)
      stopPolling()
    }
  }, [dispatch, isAuthenticated, userId])
}
