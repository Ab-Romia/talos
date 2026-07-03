import { useState } from 'react'
import Switch from '@mui/material/Switch'
import CircularProgress from '@mui/material/CircularProgress'
import { permissionsService } from '../../services/permissions'

const PERMISSION_GROUPS = [
  {
    label: 'Workspace',
    permissions: [
      { resource: 'workspace', action: 'view', label: 'View workspace' },
      { resource: 'workspace.role', action: 'view', label: 'View roles' },
    ],
  },
  {
    label: 'Channels',
    permissions: [
      { resource: 'channel', action: 'view', label: 'View channels' },
      { resource: 'channel.message', action: 'send', label: 'Send messages' },
      { resource: 'channel.member', action: 'view_presence', label: 'View member presence' },
    ],
  },
  {
    label: 'Files',
    permissions: [
      { resource: 'files', action: 'read', label: 'Read files' },
      { resource: 'files', action: 'write', label: 'Write files' },
      { resource: 'files', action: 'create', label: 'Create files' },
    ],
  },
]

export default function PermissionsGrid({ permissions = [], workspaceId, roleId, onRefresh, onError }) {
  const [savingKey, setSavingKey] = useState(null)

  const isEnabled = (resource, action) =>
    permissions.some((p) => p.resource === resource && p.action === action)

  const handleToggle = async (resource, action) => {
    const key = `${resource}:${action}`
    setSavingKey(key)
    try {
      let updated
      if (isEnabled(resource, action)) {
        updated = permissions.filter((p) => !(p.resource === resource && p.action === action))
      } else {
        updated = [...permissions, { resource, action, scope: 0 }]
      }
      await permissionsService.setRolePermissions(workspaceId, roleId, updated)
      onRefresh()
    } catch (err) {
      onError(err?.detail || 'Failed to update permissions')
    } finally {
      setSavingKey(null)
    }
  }

  return (
    <div>
      {PERMISSION_GROUPS.map((group) => (
        <div key={group.label} className="mb-4">
          <p className="text-[11px] font-semibold text-ink-tertiary uppercase tracking-[0.06em] mb-1 px-1">
            {group.label}
          </p>
          <div className="border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden">
            {group.permissions.map((perm, i) => {
              const key = `${perm.resource}:${perm.action}`
              const enabled = isEnabled(perm.resource, perm.action)
              const saving = savingKey === key
              return (
                <div
                  key={key}
                  className={`flex items-center justify-between px-3 py-2 ${
                    i < group.permissions.length - 1 ? 'border-b border-[rgba(28,27,26,0.06)]' : ''
                  }`}
                >
                  <span className="text-[13px] text-ink">{perm.label}</span>
                  {saving ? (
                    <CircularProgress size={18} />
                  ) : (
                    <Switch
                      size="small"
                      checked={enabled}
                      onChange={() => handleToggle(perm.resource, perm.action)}
                    />
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
