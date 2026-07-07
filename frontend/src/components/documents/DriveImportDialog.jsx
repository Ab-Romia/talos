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

function formatSize(bytes) {
  const n = Number(bytes)
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

const isNativeEntry = (e) => (e.mime_type || '').startsWith(GOOGLE_NATIVE)

export function DriveImportDialog({ workspaceId, open, onClose, onImported }) {
  const [loading, setLoading] = useState(false)
  const [connected, setConnected] = useState(true)
  const [entries, setEntries] = useState([])
  const [stack, setStack] = useState([]) // [{ id, name }]
  const [selected, setSelected] = useState(() => new Set())
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState('')

  const folderId = stack.length ? stack[stack.length - 1].id : null

  // Files in the current folder that can actually be imported (Google-native
  // docs like Sheets/Slides can't be).
  const importable = entries.filter((e) => !e.is_folder && !isNativeEntry(e))
  const allSelected = importable.length > 0 && importable.every((e) => selected.has(e.id))

  const toggleSelectAll = () => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (allSelected) importable.forEach((e) => next.delete(e.id))
      else importable.forEach((e) => next.add(e.id))
      return next
    })
  }

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

            {!loading && importable.length > 0 && (
              <div className="flex items-center justify-between px-2 pb-1 mb-1 border-b border-[rgba(28,27,26,0.06)]">
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <Checkbox
                    size="small"
                    checked={allSelected}
                    indeterminate={!allSelected && importable.some((e) => selected.has(e.id))}
                    onChange={toggleSelectAll}
                    sx={{ p: 0.5 }}
                  />
                  <span className="text-[12px] text-ink-secondary">
                    Select all in this folder ({importable.length})
                  </span>
                </label>
                {selected.size > 0 && (
                  <span className="text-[12px] text-amber font-medium">{selected.size} selected</span>
                )}
              </div>
            )}

            {loading ? (
              <div className="flex justify-center py-16"><CircularProgress size={26} /></div>
            ) : entries.length === 0 ? (
              <p className="text-center text-[13px] text-ink-tertiary py-16">This folder is empty.</p>
            ) : (
              <ul className="flex flex-col">
                {entries.map((e) => {
                  const isNative = isNativeEntry(e)
                  const meta = [formatDate(e.modified), formatSize(e.size)].filter(Boolean).join(' · ')
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
                          {formatDate(e.modified) && (
                            <span className="text-[11px] text-ink-tertiary shrink-0">{formatDate(e.modified)}</span>
                          )}
                          <ChevronRight size={16} className="text-ink-tertiary shrink-0" />
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
                        <span className="text-[14px] text-ink truncate flex-1 min-w-0">{e.name}</span>
                        {isNative ? (
                          <span className="text-[11px] text-ink-tertiary shrink-0">not importable</span>
                        ) : (
                          meta && <span className="text-[11px] text-ink-tertiary shrink-0 tabular-nums">{meta}</span>
                        )}
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
