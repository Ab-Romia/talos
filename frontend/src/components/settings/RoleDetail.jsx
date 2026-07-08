import { useState, useRef } from 'react'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import { Trash2 } from 'lucide-react'
import { permissionsService } from '../../services/permissions'
import PermissionsGrid from './PermissionsGrid'
import MemberAssignment from './MemberAssignment'
import ChannelOverrides from './ChannelOverrides'

export default function RoleDetail({
  role,
  loading,
  isBase,
  workspaceId,
  members,
  chatrooms,
  onRefresh,
  onDelete,
  onError,
}) {
  const [editingName, setEditingName] = useState(false)
  const [nameValue, setNameValue] = useState('')
  const [editingDesc, setEditingDesc] = useState(false)
  const [descValue, setDescValue] = useState('')
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const nameRef = useRef(null)

  if (loading) {
    return (
      <div className="flex justify-center items-center h-full">
        <CircularProgress size={22} />
      </div>
    )
  }

  if (!role) {
    return (
      <div className="flex items-center justify-center h-full text-ink-tertiary text-sm">
        Select a role to view details
      </div>
    )
  }

  const handleNameBlur = async () => {
    setEditingName(false)
    const trimmed = nameValue.trim()
    if (!trimmed || trimmed === role.name) return
    try {
      await permissionsService.updateRole(workspaceId, role.id, { name: trimmed })
      onRefresh()
    } catch (err) {
      onError(err?.detail || 'Failed to update role name')
    }
  }

  const handleDescBlur = async () => {
    setEditingDesc(false)
    if (descValue === (role.description || '')) return
    try {
      await permissionsService.updateRole(workspaceId, role.id, { description: descValue || '' })
      onRefresh()
    } catch (err) {
      onError(err?.detail || 'Failed to update description')
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await onDelete()
      setDeleteDialogOpen(false)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-[rgba(28,27,26,0.06)]">
        {editingName ? (
          <TextField
            inputRef={nameRef}
            value={nameValue}
            onChange={(e) => setNameValue(e.target.value)}
            onBlur={handleNameBlur}
            onKeyDown={(e) => e.key === 'Enter' && nameRef.current?.blur()}
            size="small"
            fullWidth
            autoFocus
            sx={{ mb: 1 }}
          />
        ) : (
          <h3
            className="text-[15px] font-semibold text-ink mb-1 cursor-pointer hover:text-amber transition-colors"
            tabIndex={0}
            role="button"
            onClick={() => { setNameValue(role.name); setEditingName(true) }}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setNameValue(role.name); setEditingName(true) } }}
          >
            {role.name}
          </h3>
        )}
        {editingDesc ? (
          <TextField
            value={descValue}
            onChange={(e) => setDescValue(e.target.value)}
            onBlur={handleDescBlur}
            size="small"
            fullWidth
            multiline
            rows={2}
            autoFocus
            placeholder="Add a description..."
          />
        ) : (
          <p
            className="text-[13px] text-ink-secondary cursor-pointer hover:text-ink transition-colors"
            tabIndex={0}
            role="button"
            onClick={() => { setDescValue(role.description || ''); setEditingDesc(true) }}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setDescValue(role.description || ''); setEditingDesc(true) } }}
          >
            {role.description || 'Click to add description...'}
          </p>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div>
          <h4 className="text-[13px] font-semibold text-ink mb-3">Permissions</h4>
          <PermissionsGrid
            permissions={role.permissions || []}
            workspaceId={workspaceId}
            roleId={role.id}
            onRefresh={onRefresh}
            onError={onError}
          />
        </div>

        <div>
          <h4 className="text-[13px] font-semibold text-ink mb-3">Members</h4>
          <MemberAssignment
            assignedUserIds={role.users || []}
            workspaceMembers={members}
            workspaceId={workspaceId}
            roleId={role.id}
            onRefresh={onRefresh}
            onError={onError}
          />
        </div>

        <ChannelOverrides
          roleId={role.id}
          channels={chatrooms}
          workspaceId={workspaceId}
          onError={onError}
        />
      </div>

      {/* Footer */}
      {!isBase && (
        <div className="p-3 border-t border-[rgba(28,27,26,0.06)] flex justify-end">
          <Button
            size="small"
            color="error"
            variant="text"
            startIcon={<Trash2 size={14} />}
            onClick={() => setDeleteDialogOpen(true)}
          >
            Delete role
          </Button>
        </div>
      )}

      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete role</DialogTitle>
        <DialogContent>
          <p className="text-sm text-ink-secondary">
            Are you sure you want to delete <strong>{role.name}</strong>? This will unassign the role
            from all members. This action cannot be undone.
          </p>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            disabled={deleting}
            startIcon={deleting ? <CircularProgress size={14} color="inherit" /> : null}
            onClick={handleDelete}
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  )
}
