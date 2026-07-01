import { useEffect, useRef } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import {
  loadUnreadCount,
  syncPushStatus,
  receivedRealtime,
} from '../store/notificationsSlice'
import { connectSocket, disconnectSocket } from '../services/realtimeSocket'

const POLL_INTERVAL_MS = 30_000
const NOTIFICATION_EVENTS = [
  'notification',
  'notification.created',
  'notification:new',
]

export default function useNotificationsSocket() {
  const dispatch = useDispatch()
  const isAuthenticated = useSelector((s) => s.auth.isAuthenticated)
  const pollTimerRef = useRef(null)

  useEffect(() => {
    if (!isAuthenticated) return

    dispatch(loadUnreadCount())
    dispatch(syncPushStatus())

    const socket = connectSocket()

    const handleIncoming = (payload) => {
      if (!payload) return
      if (payload.id && payload.title) {
        dispatch(receivedRealtime(payload))
      } else {
        dispatch(loadUnreadCount())
      }
    }

    NOTIFICATION_EVENTS.forEach((evt) => socket.on(evt, handleIncoming))

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

    socket.on('connect', handleConnect)
    socket.on('disconnect', handleDisconnect)
    socket.on('connect_error', handleConnectError)

    if (!socket.connected) startPolling()

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        dispatch(loadUnreadCount())
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      NOTIFICATION_EVENTS.forEach((evt) => socket.off(evt, handleIncoming))
      socket.off('connect', handleConnect)
      socket.off('disconnect', handleDisconnect)
      socket.off('connect_error', handleConnectError)
      document.removeEventListener('visibilitychange', handleVisibility)
      stopPolling()
      disconnectSocket()
    }
  }, [dispatch, isAuthenticated])
}
