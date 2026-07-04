import { useState, useEffect, useCallback } from 'react'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import CircularProgress from '@mui/material/CircularProgress'
import { Folder, FileText, ChevronRight, ArrowLeft } from 'lucide-react'

import { api } from '../../services/api'
import { documentService } from '../../services/documents'

const GOOGLE_NATIVE = 'application/vnd.google-apps.'

export function DriveImportDialog({ workspaceId, open, onClose, onImported }) {
  const [loading, setLoading] = useState(false)
  const [connected, setConnected] = useState(true)
  const [entries, setEntries] = useState([])
  const [stack, setStack] = useState([]) // [{ id, name }]
  const [selected, setSelected] = useState(() => new Set())
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState('')

  const folderId = stack.length ? stack[stack.length - 1].id : null

  const load = useCallback(async () => {
    if (!workspaceId) return
    setLoading(true)
    setError('')
    try {
      const list = await documentService.listDrive(workspaceId, folderId)
      setEntries(Array.isArray(list) ? list : [])
      setConnected(true)
    } catch (err) {
      if (err?.status === 409) {
        setConnected(false)
      } else {
        setError(err?.detail || 'Could not load Google Drive files.')
      }
    } finally {
      setLoading(false)
    }
  }, [workspaceId, folderId])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  useEffect(() => {
    if (!open) {
      setStack([])
      setSelected(new Set())
      setError('')
    }
  }, [open])

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const openFolder = (entry) => setStack((s) => [...s, { id: entry.id, name: entry.name }])
  const goBack = () => setStack((s) => s.slice(0, -1))

  const handleImport = async () => {
    if (!selected.size) return
    setImporting(true)
    try {
      await documentService.importDrive(workspaceId, [...selected])
      onImported?.(selected.size)
      onClose?.()
    } catch (err) {
      setError(err?.detail || 'Import failed.')
    } finally {
      setImporting(false)
    }
  }

  const connect = async () => {
    try {
      // The ticket ties the Drive connection to the CURRENT logged-in account
      // (the OAuth browser flow alone can't see our Bearer session).
      const { ticket } = await api.post('/api/auth/oauth/google/connect')
      window.location.href = `/api/auth/oauth/google?connect=${encodeURIComponent(ticket)}`
    } catch (err) {
      setError(err?.detail || 'Could not start the Google Drive connection.')
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle sx={{ fontWeight: 600, fontSize: 16 }}>Import from Google Drive</DialogTitle>
      <DialogContent dividers sx={{ minHeight: 320 }}>
        {!connected ? (
          <div className="flex flex-col items-center text-center py-10 gap-3">
            <p className="text-[14px] text-ink-secondary">
              Connect your Google Drive to import documents into this workspace.
            </p>
            <Button variant="contained" onClick={connect}>Connect Google Drive</Button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 mb-2 min-h-[28px]">
              {stack.length > 0 && (
                <button onClick={goBack} className="flex items-center text-ink-secondary hover:text-ink" type="button">
                  <ArrowLeft size={16} />
                </button>
              )}
              <div className="flex items-center gap-1 text-[13px] text-ink-tertiary truncate">
                <span>My Drive</span>
                {stack.map((f) => (
                  <span key={f.id} className="flex items-center gap-1 truncate">
                    <ChevronRight size={13} />
                    <span className="truncate max-w-[140px]">{f.name}</span>
                  </span>
                ))}
              </div>
            </div>

            {error && <p className="text-[13px] text-red-600 mb-2">{error}</p>}

            {loading ? (
              <div className="flex justify-center py-16"><CircularProgress size={26} /></div>
            ) : entries.length === 0 ? (
              <p className="text-center text-[13px] text-ink-tertiary py-16">This folder is empty.</p>
            ) : (
              <ul className="flex flex-col">
                {entries.map((e) => {
                  const isNative = (e.mime_type || '').startsWith(GOOGLE_NATIVE)
                  if (e.is_folder) {
                    return (
                      <li key={e.id}>
                        <button
                          type="button"
                          onClick={() => openFolder(e)}
                          className="w-full flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-surface-2 text-left"
                        >
                          <Folder size={18} className="text-amber shrink-0" />
                          <span className="text-[14px] text-ink truncate flex-1">{e.name}</span>
                          <ChevronRight size={16} className="text-ink-tertiary" />
                        </button>
                      </li>
                    )
                  }
                  return (
                    <li key={e.id}>
                      <label
                        className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg ${
                          isNative ? 'opacity-40 cursor-not-allowed' : 'hover:bg-surface-2 cursor-pointer'
                        }`}
                      >
                        <Checkbox
                          size="small"
                          disabled={isNative}
                          checked={selected.has(e.id)}
                          onChange={() => toggle(e.id)}
                        />
                        <FileText size={17} className="text-ink-tertiary shrink-0" />
                        <span className="text-[14px] text-ink truncate flex-1">{e.name}</span>
                        {isNative && <span className="text-[11px] text-ink-tertiary">not importable</span>}
                      </label>
                    </li>
                  )
                })}
              </ul>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} color="inherit">Cancel</Button>
        {connected && (
          <Button
            variant="contained"
            onClick={handleImport}
            disabled={!selected.size || importing}
            startIcon={importing ? <CircularProgress size={14} color="inherit" /> : null}
          >
            Import{selected.size ? ` (${selected.size})` : ''}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
