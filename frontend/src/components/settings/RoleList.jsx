import { useState } from 'react'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import CircularProgress from '@mui/material/CircularProgress'
import Chip from '@mui/material/Chip'
import Alert from '@mui/material/Alert'
import { Plus, Shield } from 'lucide-react'

export default function RoleList({ roles, selectedRoleId, baseRoleId, onSelect, onCreate }) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [name, setName] = useState('')
  const [priority, setPriority] = useState(0)
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [createError, setCreateError] = useState('')

  const handleCloseDialog = () => {
    setDialogOpen(false)
    setName('')
    setPriority(0)
    setDescription('')
    setCreateError('')
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    setSubmitting(true)
    setCreateError('')
    try {
      await onCreate(name.trim(), priority, description.trim() || null)
      handleCloseDialog()
    } catch (err) {
      setCreateError(err?.detail || 'Failed to create role')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="w-full md:w-[250px] shrink-0 border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden flex flex-col">
      <div className="px-3 py-2 border-b border-[rgba(28,27,26,0.06)] bg-surface-1">
        <span className="text-[11px] font-semibold text-ink-tertiary uppercase tracking-[0.06em]">
          Roles
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {roles.map((role) => (
          <button
            key={role.id}
            onClick={() => onSelect(role.id)}
            className={`w-full text-left px-3 py-2.5 flex items-center gap-2 transition-colors border-b border-[rgba(28,27,26,0.04)] ${
              role.id === selectedRoleId
                ? 'bg-amber-subtle text-amber'
                : 'hover:bg-surface-2 text-ink'
            }`}
          >
            <Shield size={14} className="shrink-0 opacity-50" />
            <span className="text-[13px] font-medium truncate flex-1">{role.name}</span>
            {role.id === baseRoleId && (
              <Chip
                label="Base"
                size="small"
                sx={{ height: 18, fontSize: 10, fontWeight: 600 }}
              />
            )}
          </button>
        ))}
      </div>

      <div className="p-2 border-t border-[rgba(28,27,26,0.06)]">
        <Button
          fullWidth
          size="small"
          variant="text"
          startIcon={<Plus size={14} />}
          onClick={() => setDialogOpen(true)}
          sx={{ justifyContent: 'flex-start', textTransform: 'none', fontSize: 13 }}
        >
          Create role
        </Button>
      </div>

      <Dialog open={dialogOpen} onClose={handleCloseDialog} maxWidth="xs" fullWidth>
        <DialogTitle>Create role</DialogTitle>
        <DialogContent>
          {createError && <Alert severity="error" sx={{ mb: 2 }}>{createError}</Alert>}
          <TextField
            autoFocus
            label="Role name"
            fullWidth
            value={name}
            onChange={(e) => setName(e.target.value)}
            sx={{ mt: 1, mb: 2 }}
          />
          <TextField
            label="Priority"
            type="number"
            fullWidth
            value={priority}
            onChange={(e) => setPriority(parseInt(e.target.value, 10) || 0)}
            helperText="Higher priority roles take precedence"
            sx={{ mb: 2 }}
          />
          <TextField
            label="Description (optional)"
            fullWidth
            multiline
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!name.trim() || submitting}
            startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : null}
            onClick={handleCreate}
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  )
}
