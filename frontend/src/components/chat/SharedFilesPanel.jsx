import { useEffect, useState } from 'react'
import Drawer from '@mui/material/Drawer'
import IconButton from '@mui/material/IconButton'
import CircularProgress from '@mui/material/CircularProgress'
import { X, FileText, Download, Image as ImageIcon, Film } from 'lucide-react'
import { chatService } from '../../services/chat'

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function fmtWhen(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
    + ' · ' + d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function kindIcon(contentType) {
  const ct = contentType || ''
  if (ct.startsWith('image/')) return <ImageIcon size={16} className="text-amber" />
  if (ct.startsWith('video/')) return <Film size={16} className="text-amber" />
  return <FileText size={16} className="text-amber" />
}

// WhatsApp-style panel: every file shared in this conversation, newest first.
export default function SharedFilesPanel({ channelId, open, onClose }) {
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !channelId) return
    let cancelled = false
    setLoading(true)
    setError('')
    chatService.getSharedFiles(channelId)
      .then((list) => { if (!cancelled) setFiles(Array.isArray(list) ? list : []) })
      .catch((err) => { if (!cancelled) setError(err?.detail || 'Could not load shared files') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [open, channelId])

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      slotProps={{ paper: { sx: { width: { xs: '100%', sm: 380 }, maxWidth: '100%' } } }}
    >
      <div className="flex flex-col h-full bg-surface-1">
        <div className="h-14 flex items-center justify-between px-4 border-b border-[rgba(28,27,26,0.08)] shrink-0">
          <span className="text-[15px] font-semibold text-ink">Shared files</span>
          <IconButton size="small" onClick={onClose} sx={{ color: 'text.secondary' }}>
            <X size={18} />
          </IconButton>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-ink-tertiary">
              <CircularProgress size={20} />
            </div>
          ) : error ? (
            <p className="text-center text-[13px] text-ink-tertiary py-12 px-6">{error}</p>
          ) : files.length === 0 ? (
            <p className="text-center text-[13px] text-ink-tertiary py-12 px-6">
              No files have been shared in this conversation yet.
            </p>
          ) : (
            <ul className="list-none py-2">
              {files.map((f) => (
                <li key={f.id} className="px-4">
                  <a
                    href={f.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-3 py-2.5 border-b border-[rgba(28,27,26,0.05)] last:border-b-0 group"
                  >
                    <span className="w-9 h-9 rounded-lg bg-amber-subtle flex items-center justify-center shrink-0">
                      {kindIcon(f.content_type)}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-ink truncate">{f.filename}</div>
                      <div className="text-[11px] text-ink-tertiary truncate">
                        {fmtSize(f.size_bytes)}
                        {f.uploader ? ` · ${f.uploaded_by_me ? 'You' : f.uploader}` : ''}
                        {f.created_at ? ` · ${fmtWhen(f.created_at)}` : ''}
                      </div>
                    </div>
                    <Download
                      size={16}
                      className="text-ink-tertiary opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                    />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Drawer>
  )
}
