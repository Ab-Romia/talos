import { useState, useRef, useEffect, useCallback } from 'react'
import Avatar from '@mui/material/Avatar'
import IconButton from '@mui/material/IconButton'
import Chip from '@mui/material/Chip'
import Tooltip from '@mui/material/Tooltip'
import Snackbar from '@mui/material/Snackbar'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import Popover from '@mui/material/Popover'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemAvatar from '@mui/material/ListItemAvatar'
import ListItemText from '@mui/material/ListItemText'
import {
  Search, Pin, Users, MoreHorizontal, Paperclip, Bold, Code, ArrowUp,
  Copy, RefreshCw, ThumbsUp, ThumbsDown, FileText, X,
} from 'lucide-react'

const TEAM_MEMBERS = [
  'Abdelrahman Abouromia',
  'Mohab Sherif',
  'Kyrollos Youssef',
  'Kyria Dawod',
  'Nourhane Tarek',
  'Abdullah Elsalmy',
  'Dr. Mervat Mikhail',
]

const initialMessages = [
  {
    id: 1, role: 'ai', name: 'Talos', time: '2:01 PM',
    body: "Hello! I'm your AI research assistant. I have access to all documents in this workspace. Ask me anything about your uploaded research.",
  },
  {
    id: 2, role: 'user', name: 'Abdelrahman Mashaal', initials: 'AM', time: '2:04 PM',
    body: 'What are the main findings from the RAG evaluation paper?',
  },
  {
    id: 3, role: 'ai', name: 'Talos', time: '2:04 PM',
    body: 'RICH',
    sources: ['RAG_Evaluation_2024.pdf', 'Reranking_Methods.pdf', 'Chunking_Strategies.docx'],
  },
]

function getTimeString() {
  return new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function CitationMarker({ number }) {
  return (
    <Tooltip title={`Source ${number}`} arrow>
      <span className="inline-flex items-center justify-center w-[18px] h-[18px] rounded bg-amber-subtle text-amber text-[11px] font-semibold font-mono cursor-pointer align-text-top mx-0.5 hover:bg-amber hover:text-white transition-colors">
        {number}
      </span>
    </Tooltip>
  )
}

function SourceChip({ name, onClick }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 bg-surface-1 border border-[rgba(28,27,26,0.08)] rounded-lg px-2.5 py-1.5 hover:border-[rgba(28,27,26,0.16)] hover:shadow-sm transition-all"
    >
      <FileText size={13} className="text-ink-tertiary" />
      <span className="text-[12px] font-medium text-ink-secondary whitespace-nowrap">{name}</span>
    </button>
  )
}

export default function ChatPage() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState(initialMessages)
  const [snackbar, setSnackbar] = useState({ open: false, message: '' })
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [moreAnchor, setMoreAnchor] = useState(null)
  const [usersAnchor, setUsersAnchor] = useState(null)
  const [sourceDialog, setSourceDialog] = useState({ open: false, name: '' })
  const [thumbsState, setThumbsState] = useState({})

  const threadRef = useRef(null)
  const textareaRef = useRef(null)
  const nextIdRef = useRef(4)

  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [messages])

  const showSnackbar = useCallback((message) => {
    setSnackbar({ open: true, message })
  }, [])

  const closeSnackbar = useCallback(() => {
    setSnackbar((prev) => ({ ...prev, open: false }))
  }, [])


  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text) return

    const userMsg = {
      id: nextIdRef.current++,
      role: 'user',
      name: 'Abdelrahman Mashaal',
      initials: 'AM',
      time: getTimeString(),
      body: text,
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')

    setTimeout(() => {
      const preview = text.length > 30 ? text.slice(0, 30) + '...' : text
      const aiMsg = {
        id: nextIdRef.current++,
        role: 'ai',
        name: 'Talos',
        time: getTimeString(),
        body: `I'm analyzing your query about "${preview}" This feature will be connected to the RAG pipeline soon.`,
      }
      setMessages((prev) => [...prev, aiMsg])
    }, 1000)
  }, [input])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])


  const handleHeaderButton = useCallback((Icon, event) => {
    if (Icon === Search) {
      setSearchOpen((prev) => !prev)
    } else if (Icon === Pin) {
      showSnackbar('No pinned messages yet')
    } else if (Icon === Users) {
      setUsersAnchor(event.currentTarget)
    } else if (Icon === MoreHorizontal) {
      setMoreAnchor(event.currentTarget)
    }
  }, [showSnackbar])


  const handleMoreAction = useCallback((action) => {
    setMoreAnchor(null)
    showSnackbar(action)
  }, [showSnackbar])


  const handleCopy = useCallback((msg) => {
    const text = msg.body === 'RICH'
      ? 'Based on the uploaded evaluation paper, the main findings are: 1. Hybrid retrieval outperforms single-method approaches. 2. Cross-encoder reranking is critical for precision. 3. Chunk size significantly affects answer quality.'
      : msg.body
    navigator.clipboard.writeText(text).then(() => {
      showSnackbar('Copied to clipboard')
    }).catch(() => {
      showSnackbar('Copied to clipboard')
    })
  }, [showSnackbar])

  const handleRegenerate = useCallback(() => {
    showSnackbar('Regenerating response...')
  }, [showSnackbar])

  const handleThumb = useCallback((msgId, direction) => {
    setThumbsState((prev) => {
      const current = prev[msgId]

      const newDirection = current === direction ? null : direction
      return { ...prev, [msgId]: newDirection }
    })
    showSnackbar('Feedback recorded')
  }, [showSnackbar])


  const handleToolbar = useCallback((Icon) => {
    if (Icon === Paperclip) {
      showSnackbar('File upload coming soon')
      return
    }

    const textarea = textareaRef.current
    if (!textarea) return

    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const selected = input.substring(start, end)

    let newText, cursorPos
    if (Icon === Bold) {
      if (selected) {
        newText = input.substring(0, start) + `**${selected}**` + input.substring(end)
        cursorPos = end + 4
      } else {
        newText = input.substring(0, start) + '****' + input.substring(end)
        cursorPos = start + 2
      }
    } else if (Icon === Code) {
      if (selected) {
        newText = input.substring(0, start) + '`' + selected + '`' + input.substring(end)
        cursorPos = end + 2
      } else {
        newText = input.substring(0, start) + '``' + input.substring(end)
        cursorPos = start + 1
      }
    }

    if (newText !== undefined) {
      setInput(newText)

      setTimeout(() => {
        textarea.focus()
        textarea.setSelectionRange(cursorPos, cursorPos)
      }, 0)
    }
  }, [input, showSnackbar])


  const handleSourceClick = useCallback((name) => {
    setSourceDialog({ open: true, name })
  }, [])


  const renderMessageActions = (msg) => {
    const thumbState = thumbsState[msg.id]
    const actions = [
      { Icon: Copy, handler: () => handleCopy(msg), tooltip: 'Copy' },
      { Icon: RefreshCw, handler: handleRegenerate, tooltip: 'Regenerate' },
      {
        Icon: ThumbsUp,
        handler: () => handleThumb(msg.id, 'up'),
        tooltip: 'Helpful',
        filled: thumbState === 'up',
      },
      {
        Icon: ThumbsDown,
        handler: () => handleThumb(msg.id, 'down'),
        tooltip: 'Not helpful',
        filled: thumbState === 'down',
      },
    ]
    return (
      <div className="flex gap-0.5 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
        {actions.map(({ Icon, handler, tooltip, filled }) => (
          <Tooltip key={tooltip} title={tooltip} arrow>
            <IconButton
              size="small"
              onClick={handler}
              sx={{
                width: 28,
                height: 28,
                color: filled ? 'primary.main' : 'text.disabled',
                '&:hover': { color: 'text.secondary', bgcolor: 'rgba(28,27,26,0.04)' },
              }}
            >
              <Icon size={13} fill={filled ? 'currentColor' : 'none'} />
            </IconButton>
          </Tooltip>
        ))}
      </div>
    )
  }


  const headerIcons = [Search, Pin, Users, MoreHorizontal]


  const toolbarIcons = [Paperclip, Bold, Code]

  return (
    <div className="flex flex-col h-full bg-base">
      {/* Header */}
      <header className="h-14 bg-surface-1 border-b border-[rgba(28,27,26,0.08)] flex items-center justify-between px-5 shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="w-2 h-2 bg-success rounded-full" />
          <span className="text-[15px] font-semibold text-ink">Talos AI</span>
          <Chip label="AI" color="primary" size="small" sx={{ height: 20, fontSize: 10 }} />
        </div>
        <div className="flex items-center gap-0.5">
          {headerIcons.map((Icon, i) => (
            <IconButton
              key={i}
              size="small"
              onClick={(e) => handleHeaderButton(Icon, e)}
              sx={{ color: 'text.secondary', '&:hover': { bgcolor: 'rgba(28,27,26,0.04)' } }}
            >
              <Icon size={16} />
            </IconButton>
          ))}
        </div>
      </header>

      {/* Search bar */}
      {searchOpen && (
        <div className="bg-surface-1 border-b border-[rgba(28,27,26,0.08)] px-5 py-2 flex items-center gap-2 shrink-0">
          <TextField
            size="small"
            placeholder="Search messages..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            autoFocus
            fullWidth
            sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
          />
          <IconButton
            size="small"
            onClick={() => { setSearchOpen(false); setSearchQuery('') }}
            sx={{ color: 'text.secondary' }}
          >
            <X size={16} />
          </IconButton>
        </div>
      )}

      {/* Thread */}
      <div ref={threadRef} className="flex-1 overflow-y-auto">
        <div className="max-w-[680px] mx-auto px-5 py-6">
          {/* Date divider */}
          <div className="flex items-center gap-4 mb-6">
            <span className="flex-1 h-px bg-[rgba(28,27,26,0.06)]" />
            <span className="text-[11px] font-medium text-ink-tertiary uppercase tracking-wider">Today</span>
            <span className="flex-1 h-px bg-[rgba(28,27,26,0.06)]" />
          </div>

          {messages.map((msg) => (
            <div key={msg.id} className="flex gap-3 mb-6 group">
              <div className="pt-0.5">
                {msg.role === 'ai' ? (
                  <Avatar sx={{ width: 34, height: 34, bgcolor: 'primary.light', color: 'primary.main', fontSize: 14, fontWeight: 700, border: '1.5px solid', borderColor: 'rgba(196,145,58,0.3)', flexShrink: 0 }}>T</Avatar>
                ) : (
                  <Avatar sx={{ width: 34, height: 34, bgcolor: '#EEEDEA', color: 'text.secondary', fontSize: 13, fontWeight: 600, flexShrink: 0 }}>{msg.initials}</Avatar>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[13px] font-semibold text-ink">{msg.name}</span>
                  {msg.role === 'ai' && <Chip label="AI" color="primary" size="small" sx={{ height: 17, fontSize: 9, fontWeight: 700 }} />}
                  <span className="text-[12px] text-ink-muted">{msg.time}</span>
                </div>

                {msg.body === 'RICH' ? (
                  <div className="text-[14px] text-ink leading-relaxed">
                    <p className="mb-3">Based on the uploaded evaluation paper, the main findings are:</p>
                    <p className="mb-3">
                      <strong>1. Hybrid retrieval outperforms single-method approaches.</strong>{' '}
                      Combining dense embeddings with BM25 sparse retrieval improved recall by 23% compared to dense-only retrieval <CitationMarker number={1} />.
                      The fusion strategy used reciprocal rank fusion (RRF) for score combination.
                    </p>
                    <p className="mb-3">
                      <strong>2. Cross-encoder reranking is critical for precision.</strong>{' '}
                      Adding a reranking step after initial retrieval improved the precision@10 metric by 31% <CitationMarker number={2} />,
                      though it adds ~200ms of latency per query.
                    </p>
                    <p>
                      <strong>3. Chunk size significantly affects answer quality.</strong>{' '}
                      The paper found that 512-token chunks with 50-token overlap produced the best balance of context and specificity{' '}
                      <CitationMarker number={1} /> <CitationMarker number={3} />.
                    </p>
                  </div>
                ) : (
                  <p className="text-[14px] text-ink leading-relaxed">{msg.body}</p>
                )}

                {msg.sources && (
                  <div className="mt-4 pt-3 border-t border-[rgba(28,27,26,0.06)]">
                    <span className="text-[10px] font-bold text-ink-tertiary uppercase tracking-[0.08em] mb-2 block">Sources</span>
                    <div className="flex gap-1.5 flex-wrap">
                      {msg.sources.map((s) => (
                        <SourceChip key={s} name={s} onClick={() => handleSourceClick(s)} />
                      ))}
                    </div>
                  </div>
                )}

                {msg.role === 'ai' && renderMessageActions(msg)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-[rgba(28,27,26,0.06)] bg-surface-1">
        <div className="max-w-[680px] mx-auto px-5 py-4">
          <div className="bg-base border border-[rgba(28,27,26,0.10)] rounded-2xl p-3 px-4 flex items-end gap-3 focus-within:border-amber focus-within:shadow-[0_0_0_3px_rgba(196,145,58,0.12)] transition-all">
            <div className="flex-1 flex flex-col">
              <div className="flex items-center gap-1 pb-2 mb-2 border-b border-[rgba(28,27,26,0.06)]">
                {toolbarIcons.map((Icon, i) => (
                  <IconButton
                    key={i}
                    size="small"
                    onClick={() => handleToolbar(Icon)}
                    sx={{ width: 28, height: 28, color: 'text.disabled', '&:hover': { color: 'text.secondary' } }}
                  >
                    <Icon size={15} />
                  </IconButton>
                ))}
              </div>
              <textarea
                ref={textareaRef}
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Message Talos..."
                className="bg-transparent border-none text-[14px] text-ink outline-none resize-none min-h-[24px] max-h-[200px] leading-relaxed placeholder:text-ink-muted"
              />
            </div>
            <button
              onClick={handleSend}
              className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 transition-all ${
                input.trim()
                  ? 'bg-amber text-white shadow-sm hover:bg-amber-hover hover:shadow-md'
                  : 'bg-surface-3 text-ink-muted cursor-default'
              }`}
              disabled={!input.trim()}
            >
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </div>

      {/* Users Popover */}
      <Popover
        open={Boolean(usersAnchor)}
        anchorEl={usersAnchor}
        onClose={() => setUsersAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { mt: 1, borderRadius: 2, minWidth: 240 } } }}
      >
        <Typography sx={{ px: 2, pt: 1.5, pb: 0.5, fontSize: 13, fontWeight: 600, color: 'text.secondary' }}>
          Workspace Members
        </Typography>
        <List dense sx={{ py: 0.5 }}>
          {TEAM_MEMBERS.map((name) => (
            <ListItem key={name} sx={{ py: 0.5 }}>
              <ListItemAvatar sx={{ minWidth: 36 }}>
                <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: '#EEEDEA', color: 'text.secondary' }}>
                  {name.split(' ').map((n) => n[0]).join('').slice(0, 2)}
                </Avatar>
              </ListItemAvatar>
              <ListItemText
                primary={name}
                primaryTypographyProps={{ fontSize: 13 }}
              />
            </ListItem>
          ))}
        </List>
      </Popover>

      {/* More Menu */}
      <Menu
        anchorEl={moreAnchor}
        open={Boolean(moreAnchor)}
        onClose={() => setMoreAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { mt: 1, borderRadius: 2, minWidth: 200 } } }}
      >
        <MenuItem onClick={() => handleMoreAction('View channel details')} sx={{ fontSize: 13 }}>
          View channel details
        </MenuItem>
        <MenuItem onClick={() => handleMoreAction('Notifications muted')} sx={{ fontSize: 13 }}>
          Mute notifications
        </MenuItem>
        <MenuItem onClick={() => handleMoreAction('History cleared')} sx={{ fontSize: 13, color: 'error.main' }}>
          Clear history
        </MenuItem>
      </Menu>

      {/* Source Preview Dialog */}
      <Dialog
        open={sourceDialog.open}
        onClose={() => setSourceDialog({ open: false, name: '' })}
        maxWidth="sm"
        fullWidth
        PaperProps={{ sx: { borderRadius: 3 } }}
      >
        <DialogTitle sx={{ fontSize: 16, fontWeight: 600 }}>
          {sourceDialog.name}
        </DialogTitle>
        <DialogContent>
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <FileText size={48} className="text-ink-muted mb-4" />
            <Typography variant="body2" color="text.secondary">
              Preview not available in demo mode
            </Typography>
          </div>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button
            onClick={() => setSourceDialog({ open: false, name: '' })}
            variant="outlined"
            size="small"
            sx={{ borderRadius: 2, textTransform: 'none' }}
          >
            Close
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={2500}
        onClose={closeSnackbar}
        message={snackbar.message}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        ContentProps={{ sx: { borderRadius: 2, fontSize: 13 } }}
      />
    </div>
  )
}
