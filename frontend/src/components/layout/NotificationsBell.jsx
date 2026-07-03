import { useRef, useState } from 'react'
import { useSelector } from 'react-redux'
import IconButton from '@mui/material/IconButton'
import Badge from '@mui/material/Badge'
import Tooltip from '@mui/material/Tooltip'
import { Bell } from 'lucide-react'
import NotificationsDropdown from './NotificationsDropdown'

export default function NotificationsBell() {
  const anchorRef = useRef(null)
  const [open, setOpen] = useState(false)
  const unreadCount = useSelector((s) => s.notifications.unreadCount)

  return (
    <>
      <Tooltip title="Notifications">
        <IconButton
          ref={anchorRef}
          onClick={() => setOpen((v) => !v)}
          size="small"
          className="text-ink-secondary hover:text-ink-primary"
        >
          <Badge
            badgeContent={unreadCount}
            max={99}
            color="warning"
            overlap="circular"
            sx={{
              '& .MuiBadge-badge': {
                fontSize: 8,
                height: 14,
                minWidth: 14,
                padding: '0 3px',
              },
            }}
          >
            <Bell size={18} />
          </Badge>
        </IconButton>
      </Tooltip>
      <NotificationsDropdown
        anchorEl={anchorRef.current}
        open={open}
        onClose={() => setOpen(false)}
      />
    </>
  )
}
