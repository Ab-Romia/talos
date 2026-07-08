import { useEffect, useRef } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import {
  loadUnreadCount,
  syncPushStatus,
  receivedRealtime,
} from '../store/notificationsSlice'
import { markChannelUnread, loadDms, setActiveChatroom, loadUnreadByChannel } from '../store/workspaceSlice'
import { onNotification, getSocket, onChatMessage } from '../services/socket'
import { docText } from '../utils/prosemirrorText'
import * as R from '../constants/Routes'

const POLL_INTERVAL_MS = 30_000

export default function useNotificationsSocket() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const isAuthenticated = useSelector((s) => s.auth.isAuthenticated)
  const userId = useSelector((s) => s.auth.user?.id)
  const pollTimerRef = useRef(null)

  // Latest chat state, read by the (once-registered) message handler without
  // re-subscribing on every workspace/channel switch.
  const activeChatroomId = useSelector((s) => s.workspace.activeChatroomId)
  const activeWorkspaceId = useSelector((s) => s.workspace.activeWorkspaceId)
  const chatrooms = useSelector((s) => s.workspace.chatrooms)
  const dms = useSelector((s) => s.workspace.dms)
  const stateRef = useRef({})
  stateRef.current = { activeChatroomId, activeWorkspaceId, chatrooms, dms, userId }

  useEffect(() => {
    if (!isAuthenticated) return

    dispatch(loadUnreadCount())
    dispatch(loadUnreadByChannel())
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
      const { activeChatroomId: activeCr, activeWorkspaceId: wsId, chatrooms: chans, dms: convos, userId: me } = stateRef.current
      // Never notify about our OWN message. Compare as strings (ids can differ in
      // shape between the socket payload and the auth store) and, until we know
      // who we are, suppress rather than risk a self-notification.
      if (!m || !m.sender_id) return
      if (!me || String(m.sender_id) === String(me)) return

      dispatch(loadUnreadCount())

      // A message in a conversation that isn't currently open: bump its unread
      // badge, and if it's a DM/group we don't know yet (a peer just started it),
      // refresh the conversation list so it shows up in the sidebar.
      if (m.channel_id && m.channel_id !== activeCr) {
        const known = chans.some((c) => c.id === m.channel_id) || convos.some((d) => d.id === m.channel_id)
        if (!known && wsId) dispatch(loadDms(wsId))
        dispatch(markChannelUnread(m.channel_id))
      }

      if ('Notification' in window && Notification.permission === 'granted') {
        try {
          const chName = chans.find((c) => c.id === m.channel_id)?.name
          const notif = new Notification(chName ? `#${chName}` : 'New message', {
            body: docText(m.content).slice(0, 200),
            icon: '/favicon.svg',
            tag: m.id || `msg-${Date.now()}`,
          })
          notif.onclick = () => {
            window.focus()
            if (m.channel_id) {
              dispatch(setActiveChatroom(m.channel_id))
              navigate(R.CHAT_PAGE)
            }
          }
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
          dispatch(loadUnreadByChannel())
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
  }, [dispatch, isAuthenticated, userId, navigate])
}
