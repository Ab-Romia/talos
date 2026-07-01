import { Bell, ShieldAlert, UserCheck, Tag, Users, Settings as SettingsIcon } from 'lucide-react'

const TAG_ICON = {
  security: ShieldAlert,
  account: UserCheck,
  promotion: Tag,
  social: Users,
  system: SettingsIcon,
}

function pickIcon(tags) {
  if (!Array.isArray(tags) || tags.length === 0) return Bell
  for (const t of tags) {
    if (TAG_ICON[t]) return TAG_ICON[t]
  }
  return Bell
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const diffMs = Date.now() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `${diffH}h ago`
  const diffD = Math.floor(diffH / 24)
  if (diffD < 7) return `${diffD}d ago`
  return d.toLocaleDateString()
}

export default function NotificationItem({ notification, onClick }) {
  const Icon = pickIcon(notification.tags)
  const unread = !notification.read_at

  return (
    <button
      type="button"
      onClick={() => onClick?.(notification)}
      className={`w-full text-left flex gap-3 px-4 py-3 hover:bg-surface-3 transition-colors border-b border-[rgba(28,27,26,0.06)] ${
        unread ? 'bg-amber-subtle/30' : ''
      }`}
    >
      <div
        className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
          unread ? 'bg-amber-subtle text-amber' : 'bg-surface-3 text-ink-tertiary'
        }`}
      >
        <Icon size={16} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p
            className={`text-sm truncate ${
              unread ? 'font-semibold text-ink-primary' : 'text-ink-secondary'
            }`}
          >
            {notification.title}
          </p>
          {unread && <span className="w-2 h-2 rounded-full bg-amber shrink-0" />}
        </div>
        {notification.body && (
          <p className="text-xs text-ink-tertiary mt-0.5 line-clamp-2">
            {notification.body}
          </p>
        )}
        <p className="text-[11px] text-ink-tertiary mt-1">
          {formatTime(notification.created_at)}
        </p>
      </div>
    </button>
  )
}
