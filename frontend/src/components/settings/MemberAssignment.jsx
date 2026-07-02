import { useState } from 'react'
import Avatar from '@mui/material/Avatar'
import Autocomplete from '@mui/material/Autocomplete'
import TextField from '@mui/material/TextField'
import IconButton from '@mui/material/IconButton'
import CircularProgress from '@mui/material/CircularProgress'
import { X } from 'lucide-react'
import { permissionsService } from '../../services/permissions'

function initialsOf(name) {
  return (name || '?')
    .split(' ')
    .map((n) => n[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export default function MemberAssignment({
  assignedUserIds = [],
  workspaceMembers = [],
  workspaceId,
  roleId,
  onRefresh,
  onError,
}) {
  const [saving, setSaving] = useState(false)

  const assigned = workspaceMembers.filter((m) => assignedUserIds.includes(m.id))
  const available = workspaceMembers.filter((m) => !assignedUserIds.includes(m.id))

  const handleAdd = async (member) => {
    if (!member) return
    setSaving(true)
    try {
      await permissionsService.setRoleMembers(workspaceId, roleId, [...assignedUserIds, member.id])
      onRefresh()
    } catch (err) {
      onError(err?.detail || 'Failed to add member')
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async (memberId) => {
    setSaving(true)
    try {
      await permissionsService.setRoleMembers(
        workspaceId,
        roleId,
        assignedUserIds.filter((id) => id !== memberId),
      )
      onRefresh()
    } catch (err) {
      onError(err?.detail || 'Failed to remove member')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      {assigned.length > 0 && (
        <div className="space-y-1 mb-3">
          {assigned.map((m) => (
            <div key={m.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-surface-2 group">
              <Avatar sx={{ width: 24, height: 24, fontSize: 10, fontWeight: 600 }}>
                {initialsOf(m.name || m.username)}
              </Avatar>
              <span className="text-[13px] text-ink flex-1 truncate">{m.name || m.username}</span>
              <IconButton
                size="small"
                onClick={() => handleRemove(m.id)}
                disabled={saving}
                sx={{ opacity: 0, '.group:hover &': { opacity: 1 }, transition: 'opacity 0.15s' }}
              >
                <X size={14} />
              </IconButton>
            </div>
          ))}
        </div>
      )}

      <Autocomplete
        options={available}
        getOptionLabel={(m) => m.name || m.username || ''}
        onChange={(_, value) => handleAdd(value)}
        value={null}
        disabled={saving}
        renderInput={(params) => (
          <TextField
            {...params}
            placeholder="Add member..."
            size="small"
            slotProps={{
              input: {
                ...params.InputProps,
                endAdornment: (
                  <>
                    {saving && <CircularProgress size={16} />}
                    {params.InputProps.endAdornment}
                  </>
                ),
              },
            }}
          />
        )}
        renderOption={(props, option) => (
          <li {...props} key={option.id}>
            <div className="flex items-center gap-2">
              <Avatar sx={{ width: 20, height: 20, fontSize: 9 }}>
                {initialsOf(option.name || option.username)}
              </Avatar>
              <span className="text-sm">{option.name || option.username}</span>
            </div>
          </li>
        )}
        size="small"
        blurOnSelect
        clearOnBlur
      />
    </div>
  )
}
