import { useState, useRef, useCallback, useEffect } from 'react'
import { useSelector } from 'react-redux'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import TextField from '@mui/material/TextField'
import InputAdornment from '@mui/material/InputAdornment'
import IconButton from '@mui/material/IconButton'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import Snackbar from '@mui/material/Snackbar'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableContainer from '@mui/material/TableContainer'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import { Plus, Search, Upload, Grid3X3, List, FileText, Filter, RefreshCw, Download } from 'lucide-react'
import CircularProgress from '@mui/material/CircularProgress'
import { documentService } from '../../services/documents'

const typeColors = { PDF: '#C4462A', DOCX: '#2E6FC4', TXT: '#6B6966', MD: '#3D8C5C' }
const statusMap = {
  indexed: 'success',
  processing: 'warning',
  queued: 'default',
  error: 'error',
}
const statusLabel = (s) =>
  ({ indexed: 'Indexed', processing: 'Processing', queued: 'Queued', error: 'Failed' }[s] || s)

function mapFileRow(f) {
  const ps = f.processing_status
  if (ps === 'indexed') return { status: 'indexed', chunks: f.chunk_count, errorText: null }
  if (ps === 'failed') return { status: 'error', chunks: f.chunk_count, errorText: f.processing_error || 'Processing failed' }
  if (ps === 'processing') return { status: 'processing', chunks: f.chunk_count, errorText: null }
  return { status: 'queued', chunks: f.chunk_count, errorText: null }
}

const filterOptions = ['All types', 'PDF', 'DOCX', 'TXT', 'MD']

function getFileExtension(fileName) {
  const ext = fileName.split('.').pop().toUpperCase()
  if (['PDF', 'DOCX', 'TXT', 'MD'].includes(ext)) return ext
  return 'TXT'
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function DocumentsPage() {
  const [view, setView] = useState('grid')
  const [docs, setDocs] = useState([])
  const [searchQuery, setSearchQuery] = useState('')
  const [filterType, setFilterType] = useState('All types')
  const [filterAnchorEl, setFilterAnchorEl] = useState(null)
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [snackbar, setSnackbar] = useState({ open: false, message: '' })
  const [retryingId, setRetryingId] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)
  const loadGenRef = useRef(0)
  const lastWorkspaceIdRef = useRef(null)

  const { activeWorkspaceId: workspaceId } = useSelector((s) => s.workspace)

  const resolveThumbnail = useCallback(async (wsId, f) => {
    if (!f?.content_type?.startsWith?.('image/')) return null
    try {
      const r = await documentService.getThumbnailUrl(wsId, f.id)
      return r?.thumbnail_url ?? null
    } catch {
      return null
    }
  }, [])

  const loadDocuments = useCallback(async () => {
    if (!workspaceId) {
      setDocs([])
      lastWorkspaceIdRef.current = null
      return
    }
    if (lastWorkspaceIdRef.current !== workspaceId) {
      setDocs([])
      lastWorkspaceIdRef.current = workspaceId
    }
    const gen = ++loadGenRef.current
    try {
      const result = await documentService.list(workspaceId, { limit: 100 })
      if (loadGenRef.current !== gen) return
      const files = result?.files || []
      const rows = []
      for (const f of files) {
        try {
          const m = mapFileRow(f)
          let thumb = null
          try {
            thumb = await resolveThumbnail(workspaceId, f)
          } catch {
            thumb = null
          }
          if (loadGenRef.current !== gen) return
          rows.push({
            id: f.id,
            name: f.original_filename,
            contentType: f.content_type,
            type: getFileExtension(f.original_filename),
            size: formatFileSize(f.size_bytes ?? 0),
            chunks: m.chunks,
            status: m.status,
            errorText: m.errorText,
            thumbnail: thumb,
          })
        } catch (e) {
          console.error('Document row build failed', e, f)
        }
      }
      if (loadGenRef.current !== gen) return
      setDocs(rows)
    } catch (err) {
      if (loadGenRef.current === gen) {
        console.error('Documents load failed:', err)
      }
    }
  }, [workspaceId, resolveThumbnail])

  useEffect(() => {
    void loadDocuments()
  }, [loadDocuments])

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'visible' && workspaceId) void loadDocuments()
    }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [workspaceId, loadDocuments])

  const pollProcessing = useCallback((wsId, fileId, displayName) => {
    let pollsWhileQueued = 0
    const poll = setInterval(async () => {
      try {
        const status = await documentService.getStatus(wsId, fileId)
        if (status.processing_status === 'indexed' || status.processing_status === 'failed') {
          clearInterval(poll)
          const isIndexed = status.processing_status === 'indexed'
          const mapped = mapFileRow({
            processing_status: status.processing_status,
            chunk_count: status.chunk_count,
            processing_error: status.processing_error,
          })
          let thumbnail = null
          if (isIndexed) {
            try {
              const meta = await documentService.getMetadata(wsId, fileId)
              thumbnail = await resolveThumbnail(wsId, meta)
            } catch { /* thumbnails are best-effort */ }
          }
          setDocs((prev) =>
            prev.map((d) =>
              d.id === fileId
                ? {
                    ...d,
                    status: mapped.status,
                    chunks: status.chunk_count,
                    errorText: mapped.errorText,
                    thumbnail: thumbnail ?? d.thumbnail,
                  }
                : d,
            ),
          )
          setSnackbar({
            open: true,
            message: isIndexed
              ? `${displayName} indexed successfully`
              : (mapped.errorText || `${displayName} failed to process`),
          })
          return
        }
        if (status.processing_status === 'uploaded') {
          pollsWhileQueued += 1
          if (pollsWhileQueued === 30) {
            setSnackbar({
              open: true,
              message:
                'Still waiting for the indexer. In a second terminal, run: uv run arq processing.worker.WorkerSettings (project root, same venv and Redis as the API).',
            })
            pollsWhileQueued = 31
          }
        } else {
          pollsWhileQueued = 0
        }
        {
          const row = mapFileRow({
            processing_status: status.processing_status,
            chunk_count: status.chunk_count,
            processing_error: status.processing_error,
          })
          setDocs((prev) =>
            prev.map((d) => (d.id === fileId ? { ...d, ...row, chunks: row.chunks } : d)),
          )
        }
      } catch { clearInterval(poll) }
    }, 3000)
    return poll
  }, [])

  const handleFiles = useCallback(async (files) => {
    if (!workspaceId) return
    setSnackbar({ open: true, message: `Uploading ${files.length} file(s)...` })

    for (const file of Array.from(files)) {
      try {
        const result = await documentService.upload(workspaceId, file)
        const doc = {
          id: result.file_id,
          name: result.filename,
          contentType: result.content_type,
          type: getFileExtension(result.filename),
          size: formatFileSize(result.size_bytes),
          chunks: null,
          status: 'queued',
          errorText: null,
          thumbnail: null,
        }
        setDocs((prev) => [...prev, doc])
        pollProcessing(workspaceId, result.file_id, file.name)
      } catch (err) {
        setSnackbar({ open: true, message: `Failed to upload ${file.name}: ${err.detail || 'unknown error'}` })
      }
    }
    void loadDocuments()
  }, [workspaceId, pollProcessing, loadDocuments])

  const handleRetry = useCallback(async (docId) => {
    if (!workspaceId || retryingId) return
    const d = docs.find((x) => x.id === docId)
    setRetryingId(docId)
    try {
      await documentService.retry(workspaceId, docId)
      setDocs((prev) => prev.map((x) => (x.id === docId ? { ...x, status: 'queued', errorText: null, chunks: null } : x)))
      if (selectedDoc?.id === docId) {
        setSelectedDoc((s) => (s ? { ...s, status: 'queued', errorText: null, chunks: null } : s))
      }
      setSnackbar({ open: true, message: `Re-queued ${d?.name ?? 'file'}` })
      pollProcessing(workspaceId, docId, d?.name ?? 'file')
    } catch (err) {
      setSnackbar({ open: true, message: err.detail || 'Could not retry processing' })
    } finally {
      setRetryingId(null)
    }
  }, [workspaceId, docs, pollProcessing, retryingId, selectedDoc?.id])

  const handleDownload = useCallback(async (docId) => {
    if (!workspaceId) return
    try {
      const r = await documentService.getDownloadUrl(workspaceId, docId)
      if (r?.download_url) window.open(r.download_url, '_blank', 'noopener')
    } catch (err) {
      setSnackbar({ open: true, message: err.detail || 'Could not start download' })
    }
  }, [workspaceId])

  const handleFileInput = (e) => {
    if (e.target.files?.length) {
      handleFiles(e.target.files)
      e.target.value = ''
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer.files?.length) {
      handleFiles(e.dataTransfer.files)
    }
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    setDragOver(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setDragOver(false)
  }

  const handleDeleteDoc = async (docId) => {
    if (!workspaceId) return
    const docName = docs.find((d) => d.id === docId)?.name
    try {
      await documentService.delete(workspaceId, docId)
      setDocs((prev) => prev.filter((d) => d.id !== docId))
      setSelectedDoc(null)
      setSnackbar({ open: true, message: `${docName} deleted` })
    } catch (err) {
      setSnackbar({ open: true, message: `Failed to delete ${docName}` })
    }
  }

  const filteredDocs = docs.filter((doc) => {
    const matchesSearch = doc.name.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesType = filterType === 'All types' || doc.type === filterType
    return matchesSearch && matchesType
  })

  return (
    <>
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.txt,.md"
        onChange={handleFileInput}
        style={{ display: 'none' }}
      />

      {/* Header */}
      <header className="h-14 bg-base border-b border-[rgba(28,27,26,0.10)] flex items-center justify-between px-6 shrink-0">
        <h1 className="text-lg font-semibold text-ink tracking-tight">Documents</h1>
        <Button
          variant="contained"
          startIcon={<Plus size={16} />}
          size="medium"
          onClick={() => fileInputRef.current?.click()}
        >
          Upload documents
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {/* Drop zone */}
        <div
          className={`border-2 border-dashed rounded-xl bg-surface-2 p-10 flex flex-col items-center justify-center text-center mb-8 cursor-pointer transition-colors ${
            dragOver
              ? 'border-amber bg-amber-subtle'
              : 'border-[rgba(28,27,26,0.10)] hover:border-amber hover:bg-amber-subtle'
          }`}
          onClick={() => fileInputRef.current?.click()}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragEnter={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <Upload size={48} className="text-ink-tertiary mb-4" />
          <p className="text-[15px] text-ink-secondary mb-1">
            Drag files here or <span className="text-amber font-medium">browse</span>
          </p>
          <p className="text-[13px] text-ink-tertiary">Supports PDF, DOCX, TXT, MD — up to 50MB</p>
        </div>

        {/* Toolbar */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <TextField
              size="small"
              placeholder="Search documents..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start"><Search size={14} /></InputAdornment>
                  ),
                },
              }}
              sx={{ width: 260, '& .MuiOutlinedInput-root': { height: 32, fontSize: 13 } }}
            />
            <Button
              variant="outlined"
              size="small"
              startIcon={<Filter size={14} />}
              sx={{ height: 32, fontSize: 13 }}
              onClick={(e) => setFilterAnchorEl(e.currentTarget)}
            >
              {filterType}
            </Button>
            <Menu
              anchorEl={filterAnchorEl}
              open={Boolean(filterAnchorEl)}
              onClose={() => setFilterAnchorEl(null)}
            >
              {filterOptions.map((option) => (
                <MenuItem
                  key={option}
                  selected={option === filterType}
                  onClick={() => {
                    setFilterType(option)
                    setFilterAnchorEl(null)
                  }}
                >
                  {option}
                </MenuItem>
              ))}
            </Menu>
          </div>
          <div className="flex border border-[rgba(28,27,26,0.10)] rounded-md overflow-hidden">
            <IconButton
              size="small"
              onClick={() => setView('grid')}
              sx={{ borderRadius: 0, width: 32, height: 32, bgcolor: view === 'grid' ? 'action.hover' : 'background.paper' }}
            >
              <Grid3X3 size={16} />
            </IconButton>
            <IconButton
              size="small"
              onClick={() => setView('list')}
              sx={{ borderRadius: 0, width: 32, height: 32, bgcolor: view === 'list' ? 'action.hover' : 'background.paper' }}
            >
              <List size={16} />
            </IconButton>
          </div>
        </div>

        {/* Document Grid View */}
        {view === 'grid' && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4">
            {filteredDocs.map((doc) => (
              <div
                key={doc.id}
                onClick={() => setSelectedDoc(doc)}
                className="border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden cursor-pointer hover:shadow-md hover:border-[rgba(28,27,26,0.10)] transition-all"
              >
                <div className="h-[140px] bg-surface-2 flex items-center justify-center overflow-hidden">
                  {doc.thumbnail ? (
                    <img src={doc.thumbnail} alt={doc.name} className="w-full h-full object-cover" />
                  ) : (
                    <FileText size={40} style={{ color: typeColors[doc.type] || '#6B6966' }} />
                  )}
                </div>
                <div className="p-4">
                  <p className="text-sm font-medium text-ink truncate mb-1">{doc.name}</p>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-ink-tertiary">
                      {doc.type} · {doc.size}{doc.chunks ? ` · ${doc.chunks} chunks` : ''}
                    </span>
                    <div className="flex items-center gap-1">
                      {(doc.status === 'error' || doc.status === 'queued') && (
                        <IconButton
                          size="small"
                          onClick={(e) => { e.stopPropagation(); handleRetry(doc.id) }}
                          title="Re-queue for indexing"
                          disabled={retryingId != null}
                          sx={{ width: 24, height: 24 }}
                        >
                          {retryingId === doc.id
                            ? <CircularProgress size={12} color="inherit" />
                            : <RefreshCw size={13} />}
                        </IconButton>
                      )}
                      <Chip
                        label={statusLabel(doc.status)}
                        color={statusMap[doc.status]}
                        size="small"
                        sx={{ height: 20, fontSize: 11 }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Document List View */}
        {view === 'list' && (
          <TableContainer sx={{ border: '1px solid rgba(28,27,26,0.06)', borderRadius: 2 }}>
            <Table size="small">
              <TableHead>
                <TableRow sx={{ '& th': { fontWeight: 600, fontSize: 12, color: 'text.secondary' } }}>
                  <TableCell>Name</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Size</TableCell>
                  <TableCell>Chunks</TableCell>
                  <TableCell>Status</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredDocs.map((doc) => (
                  <TableRow
                    key={doc.id}
                    hover
                    onClick={() => setSelectedDoc(doc)}
                    sx={{ cursor: 'pointer', '&:last-child td': { borderBottom: 0 } }}
                  >
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <FileText size={16} style={{ color: typeColors[doc.type] || '#6B6966', flexShrink: 0 }} />
                        <span className="text-sm font-medium text-ink truncate">{doc.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-xs text-ink-tertiary">{doc.type}</span>
                    </TableCell>
                    <TableCell>
                      <span className="text-xs text-ink-tertiary">{doc.size}</span>
                    </TableCell>
                    <TableCell>
                      <span className="text-xs text-ink-tertiary">{doc.chunks ?? '—'}</span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Chip
                          label={statusLabel(doc.status)}
                          color={statusMap[doc.status]}
                          size="small"
                          sx={{ height: 20, fontSize: 11 }}
                        />
                        {(doc.status === 'error' || doc.status === 'queued') && (
                          <IconButton
                            size="small"
                            onClick={(e) => { e.stopPropagation(); handleRetry(doc.id) }}
                            title="Re-queue for indexing"
                            disabled={retryingId != null}
                            sx={{ width: 24, height: 24 }}
                          >
                            {retryingId === doc.id
                              ? <CircularProgress size={12} color="inherit" />
                              : <RefreshCw size={13} />}
                          </IconButton>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {/* Empty state */}
        {filteredDocs.length === 0 && (
          <div className="text-center py-16 text-ink-tertiary text-sm">
            No documents found.
          </div>
        )}
      </div>

      {/* Document Detail Dialog */}
      <Dialog
        open={Boolean(selectedDoc)}
        onClose={() => setSelectedDoc(null)}
        maxWidth="xs"
        fullWidth
      >
        {selectedDoc && (
          <>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <FileText size={20} style={{ color: typeColors[selectedDoc.type] || '#6B6966' }} />
              <span className="truncate">{selectedDoc.name}</span>
            </DialogTitle>
            <DialogContent dividers>
              <div className="space-y-3 py-1">
                <div className="flex justify-between text-sm">
                  <span className="text-ink-tertiary">Type</span>
                  <span className="font-medium text-ink">{selectedDoc.type}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-ink-tertiary">Size</span>
                  <span className="font-medium text-ink">{selectedDoc.size}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-ink-tertiary">Chunks</span>
                  <span className="font-medium text-ink">{selectedDoc.chunks ?? '—'}</span>
                </div>
                <div className="flex justify-between text-sm items-center">
                  <span className="text-ink-tertiary">Status</span>
                  <Chip
                    label={statusLabel(selectedDoc.status)}
                    color={statusMap[selectedDoc.status]}
                    size="small"
                    sx={{ height: 20, fontSize: 11 }}
                  />
                </div>
                {selectedDoc.status === 'queued' && (
                  <p className="text-xs text-ink-tertiary leading-relaxed mt-1">
                    Should switch to <strong>Processing</strong> shortly. If not, use <strong>Re-queue</strong> or check server logs.
                  </p>
                )}
                {selectedDoc.status === 'processing' && (
                  <p className="text-xs text-ink-tertiary leading-relaxed mt-1">
                    Indexing in progress (extracting text, embedding, writing to the vector store).
                  </p>
                )}
                {selectedDoc.status === 'error' && selectedDoc.errorText && (
                  <p className="text-xs text-error mt-1 font-mono whitespace-pre-wrap break-words">
                    {selectedDoc.errorText}
                  </p>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button
                color="error"
                onClick={() => handleDeleteDoc(selectedDoc.id)}
              >
                Delete
              </Button>
              {(selectedDoc.status === 'error' || selectedDoc.status === 'queued') && (
                <Button
                  color="primary"
                  startIcon={
                    retryingId === selectedDoc.id
                      ? <CircularProgress size={14} color="inherit" />
                      : <RefreshCw size={14} />
                  }
                  onClick={() => handleRetry(selectedDoc.id)}
                  disabled={retryingId != null}
                >
                  {retryingId === selectedDoc.id ? 'Re-queuing…' : 'Re-queue'}
                </Button>
              )}
              <Button
                startIcon={<Download size={14} />}
                onClick={() => handleDownload(selectedDoc.id)}
              >
                Download
              </Button>
              <Button onClick={() => setSelectedDoc(null)}>Close</Button>
            </DialogActions>
          </>
        )}
      </Dialog>

      {/* Snackbar notifications */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={3000}
        onClose={() => setSnackbar({ open: false, message: '' })}
        message={snackbar.message}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      />
    </>
  )
}
