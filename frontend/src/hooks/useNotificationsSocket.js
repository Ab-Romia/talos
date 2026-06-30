import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { loadUnreadCount, syncPushStatus } from '../store/notificationsSlice'

const POLL_INTERVAL_MS = 30_000

export default function useNotificationsSocket() {
  const dispatch = useDispatch()
  const isAuthenticated = useSelector((s) => s.auth.isAuthenticated)

  useEffect(() => {
    if (!isAuthenticated) return

    dispatch(loadUnreadCount())
    dispatch(syncPushStatus())

    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        dispatch(loadUnreadCount())
      }
    }
    document.addEventListener('visibilitychange', onVisible)

    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        dispatch(loadUnreadCount())
      }
    }, POLL_INTERVAL_MS)

    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [dispatch, isAuthenticated])
}
