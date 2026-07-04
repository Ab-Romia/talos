import { useEffect } from 'react'
import { useDispatch } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { loadUnreadCount, markRead } from '../store/notificationsSlice'

export default function useNotificationClickHandler() {
  const dispatch = useDispatch()
  const navigate = useNavigate()

  useEffect(() => {
    if (!('serviceWorker' in navigator)) return

    const handler = (event) => {
      const msg = event.data
      if (!msg || msg.type !== 'notification-click') return

      const data = msg.data || {}
      if (data.id) dispatch(markRead(data.id))
      dispatch(loadUnreadCount())
      if (data.url) navigate(data.url)
    }

    navigator.serviceWorker.addEventListener('message', handler)
    return () => {
      navigator.serviceWorker.removeEventListener('message', handler)
    }
  }, [dispatch, navigate])
}
