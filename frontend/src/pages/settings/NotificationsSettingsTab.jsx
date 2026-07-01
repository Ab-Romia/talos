import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import Switch from '@mui/material/Switch'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import Chip from '@mui/material/Chip'
import { Bell, BellOff, ShieldAlert } from 'lucide-react'
import {
  enablePush,
  disablePush,
  syncPushStatus,
  clearPushError,
} from '../../store/notificationsSlice'

function permissionLabel(permission) {
  if (permission === 'granted') return { label: 'Allowed', color: 'success' }
  if (permission === 'denied') return { label: 'Blocked', color: 'error' }
  return { label: 'Not requested', color: 'default' }
}

export default function NotificationsSettingsTab() {
  const dispatch = useDispatch()
  const {
    pushSupported,
    pushPermission,
    pushEndpoint,
    pushLoading,
    pushError,
  } = useSelector((s) => s.notifications)

  useEffect(() => {
    dispatch(syncPushStatus())
  }, [dispatch])

  const enabled = Boolean(pushEndpoint)
  const blocked = pushPermission === 'denied'
  const perm = permissionLabel(pushPermission)

  const handleToggle = () => {
    if (pushLoading) return
    if (enabled) {
      dispatch(disablePush())
    } else {
      dispatch(enablePush())
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink-primary">Notifications</h2>
        <p className="text-sm text-ink-tertiary mt-1">
          Choose how Talos notifies you about activity in your workspaces.
        </p>
      </div>

      {!pushSupported && (
        <Alert severity="info" icon={<ShieldAlert size={18} />}>
          Browser push isn't supported in this browser. You'll still see in-app
          notifications via the bell.
        </Alert>
      )}

      {pushError && (
        <Alert
          severity="error"
          onClose={() => dispatch(clearPushError())}
        >
          {pushError}
        </Alert>
      )}

      <div className="rounded-lg border border-[rgba(28,27,26,0.08)] bg-surface-2 p-4">
        <div className="flex items-start gap-3">
          <div
            className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center ${
              enabled ? 'bg-amber-subtle text-amber' : 'bg-surface-3 text-ink-tertiary'
            }`}
          >
            {enabled ? <Bell size={18} /> : <BellOff size={18} />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium text-ink-primary">
                Browser push notifications
              </p>
              <Chip
                size="small"
                label={perm.label}
                color={perm.color}
                variant="outlined"
              />
            </div>
            <p className="text-xs text-ink-tertiary mt-1">
              Get system toasts for new mentions, alerts, and reminders even when
              the tab isn't focused.
            </p>
            {enabled && pushEndpoint && (
              <p className="text-[11px] text-ink-tertiary mt-2 truncate font-mono">
                {pushEndpoint}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {pushLoading && <CircularProgress size={16} />}
            <Switch
              checked={enabled}
              onChange={handleToggle}
              disabled={!pushSupported || pushLoading || blocked}
            />
          </div>
        </div>

        {blocked && (
          <div className="mt-3 pt-3 border-t border-[rgba(28,27,26,0.06)]">
            <p className="text-xs text-ink-tertiary">
              You blocked notifications for this site. Open your browser's site
              settings to allow them, then toggle this on.
            </p>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-dashed border-[rgba(28,27,26,0.12)] bg-surface-2 p-4">
        <p className="text-sm font-medium text-ink-primary">Email notifications</p>
        <p className="text-xs text-ink-tertiary mt-1">
          Coming soon. Per-channel preferences will appear here once the backend
          supports them.
        </p>
      </div>
    </div>
  )
}
