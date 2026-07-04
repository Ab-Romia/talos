import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import Popover from '@mui/material/Popover'
import CircularProgress from '@mui/material/CircularProgress'
import { CheckCheck, BellOff, AlertCircle, RefreshCw } from 'lucide-react'
import {
  loadNotifications,
  markRead,
  markAllRead,
  clearNotificationsError,
} from '../../store/notificationsSlice'
import { setActiveChatroom } from '../../store/workspaceSlice'
import NotificationItem from '../notifications/NotificationItem'

export default function NotificationsDropdown({ anchorEl, open, onClose }) {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { items, unreadCount, loading, error } = useSelector((s) => s.notifications)

  useEffect(() => {
    if (open) dispatch(loadNotifications({ limit: 20 }))
  }, [open, dispatch])

  const handleRetry = () => {
    dispatch(clearNotificationsError())
    dispatch(loadNotifications({ limit: 20 }))
  }

  const handleItemClick = (n) => {
    if (!n.is_read) dispatch(markRead(n.id))
    onClose?.()
    if (n.data?.channel_id) {
      dispatch(setActiveChatroom(n.data.channel_id))
      const msgParam = n.data.message_id ? `?msg=${n.data.message_id}` : ''
      navigate(`/chat${msgParam}`)
    } else if (n.data?.url) {
      navigate(n.data.url)
    }
  }

  const handleMarkAll = () => {
    if (unreadCount > 0) dispatch(markAllRead())
  }

  return (
    <Popover
      anchorEl={anchorEl}
      open={open}
      onClose={onClose}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      slotProps={{
        paper: {
          className:
            'mt-2 w-[380px] max-h-[480px] flex flex-col bg-surface-2 border border-[rgba(28,27,26,0.08)] rounded-lg shadow-lg overflow-hidden',
        },
      }}
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-[rgba(28,27,26,0.08)]">
        <h3 className="text-sm font-semibold text-ink-primary">Notifications</h3>
        <button
          type="button"
          onClick={handleMarkAll}
          disabled={unreadCount === 0}
          className="flex items-center gap-1 text-xs text-ink-secondary hover:text-ink-primary disabled:opacity-40 disabled:cursor-default"
        >
          <CheckCheck size={14} />
          Mark all read
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {error && items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 px-4 text-center">
            <AlertCircle size={28} className="text-red-500 mb-2" />
            <p className="text-sm text-ink-primary mb-1">Couldn't load notifications</p>
            <p className="text-xs text-ink-tertiary mb-3">{error}</p>
            <button
              type="button"
              onClick={handleRetry}
              className="flex items-center gap-1.5 text-xs text-ink-secondary hover:text-ink-primary border border-[rgba(28,27,26,0.12)] rounded px-3 py-1.5"
            >
              <RefreshCw size={12} />
              Try again
            </button>
          </div>
        ) : loading && items.length === 0 ? (
          <div className="flex items-center justify-center py-12">
            <CircularProgress size={20} />
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-ink-tertiary">
            <BellOff size={28} className="mb-2" />
            <p className="text-sm">No notifications yet</p>
          </div>
        ) : (
          items.map((n) => (
            <NotificationItem
              key={n.id}
              notification={n}
              onClick={handleItemClick}
            />
          ))
        )}
      </div>
    </Popover>
  )
}
