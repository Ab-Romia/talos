import { useState, useRef, useCallback, useEffect } from 'react'
import { useSelector } from 'react-redux'
import { useSearchParams } from 'react-router-dom'
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
import { Plus, Search, Upload, Grid3X3, List, FileText, Filter, Download, Cloud } from 'lucide-react'
import { documentService } from '../../services/documents'
import { DriveImportDialog } from '../../components/documents/DriveImportDialog'
import { usePermissions } from '../../contexts/PermissionsContext'
import SidebarToggle from '../../components/layout/SidebarToggle'

const typeColors = { PDF: '#C4462A', DOCX: '#2E6FC4', TXT: '#6B6966', MD: '#3D8C5C' }

// Backend FileStatus: pending | uploaded | processed | indexed | processing_failed
const statusMap = { ready: 'success', pending: 'default', failed: 'error' }
const statusLabel = (s) => ({ ready: 'Ready', pending: 'Pending', failed: 'Failed' }[s] || s)
function mapStatus(fileStatus) {
  if (fileStatus === 'processing_failed') return 'failed'
  if (fileStatus === 'pending') return 'pending'
  return 'ready' // uploaded / processed / indexed → available
}

const filterOptions = ['All types', 'PDF', 'DOCX', 'TXT', 'MD']

function getFileExtension(fileName) {
  const ext = (fileName || '').split('.').pop().toUpperCase()
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
  const [dragOver, setDragOver] = useState(false)
  const [driveOpen, setDriveOpen] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const fileInputRef = useRef(null)

  // Coming back from the Google consent screen — reopen the Drive picker.
  useEffect(() => {
    if (!searchParams.get('drive_connected')) return
    setDriveOpen(true)
    const next = new URLSearchParams(searchParams)
    next.delete('drive_connected')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])
  const loadGenRef = useRef(0)
  const lastWorkspaceIdRef = useRef(null)

  const { activeWorkspaceId: workspaceId } = useSelector((s) => s.workspace)
  const { hasPerm, permissionsLoaded } = usePermissions()
  const canRead = hasPerm('files', 'read')
  const canCreate = hasPerm('files', 'create')

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
      const rows = files.map((f) => ({
        id: f.id,
        name: f.original_filename,
        contentType: f.content_type,
        type: getFileExtension(f.original_filename),
        size: formatFileSize(f.size_bytes ?? 0),
        status: mapStatus(f.status),
        rawStatus: f.status,
      }))
      setDocs(rows)
    } catch (err) {
      if (loadGenRef.current === gen) {
        console.error('Documents load failed:', err)
        setSnackbar({ open: true, message: err?.detail || 'Failed to load documents' })
      }
    }
  }, [workspaceId])

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

  const handleFiles = useCallback(async (files) => {
    // Fall back to the persisted id if the store hasn't hydrated yet — a
    // stale tab (e.g. after the backend restarted) can have a null store
    // value while localStorage still holds the active workspace.
    const wsId = workspaceId || localStorage.getItem('talos:activeWorkspaceId')
    if (!wsId) {
      setSnackbar({ open: true, message: 'No workspace selected — refresh the page or pick a workspace, then retry.' })
      return
    }
    setSnackbar({ open: true, message: `Uploading ${files.length} file(s)…` })
    let ok = 0
    for (const file of Array.from(files)) {
      try {
        await documentService.upload(wsId, file)
        ok += 1
      } catch (err) {
        setSnackbar({ open: true, message: err?.detail || `Failed to upload ${file.name}` })
      }
    }
    if (ok) {
      setSnackbar({ open: true, message: `Uploaded ${ok} file(s)` })
      void loadDocuments()
    }
  }, [workspaceId, loadDocuments])

  const handleDownload = useCallback(async (docId, name) => {
    if (!workspaceId) return
    try {
      await documentService.download(workspaceId, docId, name)
    } catch (err) {
      setSnackbar({ open: true, message: err?.detail || 'Could not download file' })
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
      setSnackbar({ open: true, message: err?.detail || `Failed to delete ${docName}` })
    }
  }

  const filteredDocs = docs.filter((doc) => {
    const matchesSearch = doc.name.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesType = filterType === 'All types' || doc.type === filterType
    return matchesSearch && matchesType
  })

  if (permissionsLoaded && !canRead) {
    return (
      <div className="flex flex-col h-full bg-base">
        <header className="h-14 bg-base border-b border-[rgba(28,27,26,0.10)] flex items-center gap-2 px-3 sm:px-6 shrink-0">
          <SidebarToggle />
          <h1 className="text-lg font-semibold text-ink tracking-tight">Documents</h1>
        </header>
        <p className="text-center text-sm text-ink-tertiary py-10 px-4">
          You don't have permission to view documents in this workspace.
        </p>
      </div>
    )
  }

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
      <header className="min-h-14 bg-base border-b border-[rgba(28,27,26,0.10)] flex items-center justify-between gap-2 px-3 sm:px-6 py-2 shrink-0 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <SidebarToggle />
          <h1 className="text-lg font-semibold text-ink tracking-tight">Documents</h1>
        </div>
        {canCreate && (
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant="outlined"
            startIcon={<Cloud size={16} />}
            size="medium"
            onClick={() => setDriveOpen(true)}
          >
            <span className="hidden sm:inline">Import from Drive</span>
            <span className="sm:hidden">Import</span>
          </Button>
          <Button
            variant="contained"
            startIcon={<Plus size={16} />}
            size="medium"
            onClick={() => fileInputRef.current?.click()}
          >
            <span className="hidden sm:inline">Upload documents</span>
            <span className="sm:hidden">Upload</span>
          </Button>
        </div>
        )}
      </header>

      <DriveImportDialog
        workspaceId={workspaceId}
        open={driveOpen}
        onClose={() => setDriveOpen(false)}
        onImported={(n) => {
          setSnackbar({ open: true, message: `Importing ${n} file(s) from Google Drive…` })
          void loadDocuments()
        }}
      />

      <div className="flex-1 overflow-y-auto p-3 sm:p-6">
        {/* Drop zone */}
        {canCreate && (
        <div
          className={`border-2 border-dashed rounded-xl bg-surface-2 p-6 sm:p-10 flex flex-col items-center justify-center text-center mb-8 cursor-pointer transition-colors ${
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
        )}

        {/* Toolbar */}
        <div className="flex items-center justify-between flex-wrap gap-3 mb-5">
          <div className="flex items-center gap-3 flex-wrap flex-1 min-w-0">
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
              sx={{ width: { xs: '100%', sm: 260 }, '& .MuiOutlinedInput-root': { height: 32, fontSize: 13 } }}
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
                  <FileText size={40} style={{ color: typeColors[doc.type] || '#6B6966' }} />
                </div>
                <div className="p-4">
                  <p className="text-sm font-medium text-ink truncate mb-1">{doc.name}</p>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-ink-tertiary">
                      {doc.type} · {doc.size}
                    </span>
                    <Chip
                      label={statusLabel(doc.status)}
                      color={statusMap[doc.status]}
                      size="small"
                      sx={{ height: 20, fontSize: 11 }}
                    />
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
                      <Chip
                        label={statusLabel(doc.status)}
                        color={statusMap[doc.status]}
                        size="small"
                        sx={{ height: 20, fontSize: 11 }}
                      />
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
                <div className="flex justify-between text-sm items-center">
                  <span className="text-ink-tertiary">Status</span>
                  <Chip
                    label={statusLabel(selectedDoc.status)}
                    color={statusMap[selectedDoc.status]}
                    size="small"
                    sx={{ height: 20, fontSize: 11 }}
                  />
                </div>
              </div>
            </DialogContent>
            <DialogActions>
              <Button
                color="error"
                onClick={() => handleDeleteDoc(selectedDoc.id)}
              >
                Delete
              </Button>
              <Button
                startIcon={<Download size={14} />}
                onClick={() => handleDownload(selectedDoc.id, selectedDoc.name)}
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
