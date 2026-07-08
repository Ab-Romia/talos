import { useState, useEffect } from 'react'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import { chatService } from '../../services/chat'

export default function ChannelSettingsDialog({ open, channel, onClose, onUpdated }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (channel && open) {
      setName(channel.name || '')
      setDescription(channel.description || '')
      setError('')
    }
  }, [channel, open])

  const handleSave = async () => {
    if (!channel) return
    setSaving(true)
    setError('')
    try {
      const updates = []
      if (name.trim() && name.trim() !== channel.name) {
        updates.push(chatService.renameChannel(channel.id, name.trim()))
      }
      if (description !== (channel.description || '')) {
        updates.push(chatService.updateChannelDescription(channel.id, description))
      }
      await Promise.all(updates)
      onUpdated?.()
      onClose()
    } catch (err) {
      setError(err?.detail || 'Failed to update channel')
    } finally {
      setSaving(false)
    }
  }

  const hasChanges = channel && (
    (name.trim() && name.trim() !== channel.name) ||
    description !== (channel.description || '')
  )

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Channel settings</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <TextField
          autoFocus
          label="Channel name"
          fullWidth
          variant="outlined"
          value={name}
          onChange={(e) => setName(e.target.value)}
          sx={{ mb: 2, mt: 1 }}
        />
        <TextField
          label="Description"
          fullWidth
          variant="outlined"
          multiline
          minRows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          sx={{ mb: 2 }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!hasChanges || saving || !name.trim()}
          startIcon={saving ? <CircularProgress size={14} color="inherit" /> : null}
          onClick={handleSave}
        >
          Save
        </Button>
      </DialogActions>
    </Dialog>
  )
}
