import { useState, useRef, useEffect, useCallback, useMemo, useLayoutEffect } from 'react'
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
import CircularProgress from '@mui/material/CircularProgress'

import { useSelector } from 'react-redux'
import { chatService } from '../../services/chat'
import { documentService } from '../../services/documents'
import { MESSAGE_EVENTS_WS } from '../../constants/ApiRoutes'
import { ChatMessageContent, attachmentKey, attachmentLabel } from '../../components/chat/ChatMessageContent'
import { ChatComposerField } from '../../components/chat/ChatComposerField'

const TEAM_MEMBERS = [
  'Abdelrahman Abouromia',
  'Mohab Sherif',
  'Kyrollos Youssef',
  'Kyria Dawod',
  'Nourhane Tarek',
  'Abdullah Elsalmy',
  'Dr. Mervat Mikhail',
]

function getTimeString() {
  return new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function messageMatchesQuery(msg, rawQuery) {
  const s = rawQuery.trim().toLowerCase()
  if (!s) return true
  if ((msg.body || '').toLowerCase().includes(s)) return true
  if ((msg.name || '').toLowerCase().includes(s)) return true
  if (Array.isArray(msg.sources)) {
    for (const x of msg.sources) {
      if (String(x).toLowerCase().includes(s)) return true
    }
  }
  if (Array.isArray(msg.attachments)) {
    for (const a of msg.attachments) {
      const label = typeof a === 'string' ? a : (a?.filename || a?.name || '')
      if (label.toLowerCase().includes(s)) return true
    }
  }
  return false
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
  const [messages, setMessages] = useState([])
  const [snackbar, setSnackbar] = useState({ open: false, message: '' })
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [moreAnchor, setMoreAnchor] = useState(null)
  const [usersAnchor, setUsersAnchor] = useState(null)
  const [sourceDialog, setSourceDialog] = useState({ open: false, name: '' })
  const [thumbsState, setThumbsState] = useState({})
  const [streamingId, setStreamingId] = useState(null)
  const [attachments, setAttachments] = useState([])
  const [uploading, setUploading] = useState(false)
  const [workspaceName, setWorkspaceName] = useState('')
  const [chatroomName, setChatroomName] = useState('')

  const user = useSelector((state) => state.auth.user)
  const {
    chatrooms,
    activeWorkspaceId: workspaceId,
    activeChatroomId: chatroomId,
  } = useSelector((s) => s.workspace)

  const threadRef = useRef(null)
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)
  const nextIdRef = useRef(1)
  const firstSearchHitRef = useRef(null)
  const lastScrolledFirstMatchId = useRef(null)

  const displayMessages = useMemo(() => {
    if (!searchOpen) return messages
    const q = searchQuery.trim()
    if (!q) return messages
    return messages.filter((m) => messageMatchesQuery(m, q))
  }, [messages, searchQuery, searchOpen])

  useLayoutEffect(() => {
    if (!searchOpen || !searchQuery.trim()) {
      lastScrolledFirstMatchId.current = null
      return
    }
    const first = displayMessages[0]
    if (!first) {
      lastScrolledFirstMatchId.current = null
      return
    }
    if (lastScrolledFirstMatchId.current === first.id) return
    lastScrolledFirstMatchId.current = first.id
    requestAnimationFrame(() => {
      firstSearchHitRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    })
  }, [displayMessages, searchQuery, searchOpen])

  useEffect(() => {
    if (!workspaceId) return
    chatService.getWorkspace(workspaceId)
      .then((full) => setWorkspaceName(full?.name || ''))
      .catch(() => setWorkspaceName(''))
  }, [workspaceId])

  useEffect(() => {
    const cr = chatrooms.find((c) => c.id === chatroomId)
    setChatroomName(cr?.name || '')
  }, [chatrooms, chatroomId])

  useEffect(() => {
    if (!workspaceId || !chatroomId) return
    let cancelled = false
    setMessages([])
    setAttachments([])
    ;(async () => {
      try {
        const history = await chatService.getMessages(workspaceId, chatroomId)
        if (cancelled) return
        const list = Array.isArray(history) ? history : (history?.messages ?? [])
        const normAttachments = (raw) => {
          if (!raw || !Array.isArray(raw)) return []
          return raw.map((a) => (typeof a === 'string' ? a : { file_id: a.file_id, filename: a.filename || a.name || '' }))
        }
        const mapped = list.map((m) => ({
          id: nextIdRef.current++,
          serverId: m.id,
          role: m.role,
          name: m.role === 'ai' ? 'Talos' : (user?.name || 'You'),
          initials: m.role === 'user' ? (user?.name || 'U').split(' ').map(n => n[0]).join('').slice(0, 2) : undefined,
          time: m.created_at ? new Date(m.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '',
          body: m.content,
          attachments: normAttachments(m.attachments),
        }))
        setMessages(mapped)
      } catch (err) {
        console.error('Load messages failed:', err)
      }
    })()
    return () => { cancelled = true }
  }, [workspaceId, chatroomId, user])

  useEffect(() => {
    if (!workspaceId || !chatroomId) return
    const url = MESSAGE_EVENTS_WS(workspaceId, chatroomId)
    const ws = new WebSocket(url)
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        if (data.type !== 'message.created' || !data.message) return
        const m = data.message
        setMessages((prev) => {
          if (prev.some((x) => x.serverId === m.id)) return prev
          if (m.role === 'user' && m.content) {
            for (let i = prev.length - 1; i >= 0; i--) {
              const x = prev[i]
              if (x.role === 'user' && !x.serverId && x.body === m.content) {
                const next = [...prev]
                next[i] = { ...x, serverId: m.id }
                return next
              }
            }
          }
          return [
            ...prev,
            {
              id: nextIdRef.current++,
              serverId: m.id,
              role: m.role,
              name: m.role === 'ai' ? 'Talos' : (user?.name || 'You'),
              initials: m.role === 'user' ? (user?.name || 'U').split(' ').map(n => n[0]).join('').slice(0, 2) : undefined,
              time: m.created_at
                ? new Date(m.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
                : getTimeString(),
              body: m.content,
              attachments: (m.attachments || []).map((a) => (typeof a === 'string' ? a : { file_id: a.file_id, filename: a.filename || a.name })),
              sources: null,
            },
          ]
        })
      } catch (e) {
        console.error('WebSocket message error:', e)
      }
    }
    return () => {
      try {
        ws.close()
      } catch { /* closed */ }
    }
  }, [workspaceId, chatroomId, user?.name])

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


  const handleAttachClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleAttachFiles = useCallback(async (files) => {
    if (!workspaceId || !chatroomId) return
    setUploading(true)
    for (const file of Array.from(files)) {
      const tempId = `tmp-${Date.now()}-${file.name}`
      setAttachments((prev) => [...prev, { file_id: tempId, filename: file.name, status: 'uploading' }])
      try {
        const result = await documentService.upload(workspaceId, file, chatroomId)
        setAttachments((prev) =>
          prev.map((a) =>
            a.file_id === tempId
              ? { file_id: result.file_id, filename: result.filename, status: 'ready' }
              : a,
          ),
        )
      } catch (err) {
        setAttachments((prev) => prev.filter((a) => a.file_id !== tempId))
        showSnackbar(`Upload failed: ${err?.detail || file.name}`)
      }
    }
    setUploading(false)
  }, [workspaceId, chatroomId, showSnackbar])

  const handleRemoveAttachment = useCallback((fileId) => {
    setAttachments((prev) => prev.filter((a) => a.file_id !== fileId))
  }, [])

  const handleFileInputChange = useCallback((e) => {
    if (e.target.files?.length) {
      handleAttachFiles(e.target.files)
      e.target.value = ''
    }
  }, [handleAttachFiles])

  const handleSend = useCallback(() => {
    const text = input.trim()
    if ((!text && attachments.length === 0) || streamingId != null || !workspaceId || !chatroomId) return
    const readyFileIds = attachments
      .filter((a) => a.status === 'ready')
      .map((a) => a.file_id)

    const localUserMsgId = nextIdRef.current++
    const userMsg = {
      id: localUserMsgId,
      role: 'user',
      name: user?.name || 'You',
      initials: (user?.name || 'U').split(' ').map(n => n[0]).join('').slice(0, 2),
      time: getTimeString(),
      body: text,
      attachments: attachments.filter((a) => a.status === 'ready').map((a) => a.filename),
      serverId: null,
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setAttachments([])

    const aiId = nextIdRef.current++
    const aiMsg = {
      id: aiId,
      role: 'ai',
      name: 'Talos',
      time: getTimeString(),
      body: '',
      sources: null,
    }
    setMessages((prev) => [...prev, aiMsg])
    setStreamingId(aiId)

    chatService.sendMessage(
      workspaceId,
      chatroomId,
      text,
      (chunk) => {
        setMessages((prev) =>
          prev.map((m) => m.id === aiId ? { ...m, body: m.body + chunk } : m)
        )
      },
      (sources, aiMessageId) => {
        if (sources.length > 0) {
          setMessages((prev) =>
            prev.map((m) => m.id === aiId ? { ...m, sources: sources.map(s => s.filename) } : m)
          )
        }
        if (aiMessageId) {
          setMessages((prev) =>
            prev.map((m) => (m.id === aiId ? { ...m, serverId: aiMessageId } : m)),
          )
        }
        setStreamingId(null)
      },
      (error) => {
        setMessages((prev) =>
          prev.map((m) => m.id === aiId ? { ...m, body: error } : m)
        )
        setStreamingId(null)
      },
      {
        fileIds: readyFileIds.length ? readyFileIds : null,
        onMessageId: (serverId) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === localUserMsgId ? { ...m, serverId } : m)),
          )
        },
      },
    )
  }, [input, streamingId, workspaceId, chatroomId, user, attachments])

  const handleAttachToMessage = useCallback(async (msg) => {
    if (!msg.serverId || !workspaceId || !chatroomId) {
      showSnackbar('Message not saved yet')
      return
    }
    const picker = document.createElement('input')
    picker.type = 'file'
    picker.multiple = true
    picker.accept = '.pdf,.docx,.txt,.md,image/*'
    picker.onchange = async () => {
      const files = Array.from(picker.files || [])
      if (!files.length) return
      try {
        for (const file of files) {
          const up = await documentService.upload(workspaceId, file, chatroomId)
          await documentService.attachToMessage(workspaceId, chatroomId, msg.serverId, up.file_id)
          setMessages((prev) =>
            prev.map((m) => (m.id === msg.id
              ? { ...m, attachments: [...(m.attachments || []), up.filename] }
              : m)),
          )
        }
        showSnackbar(`Attached ${files.length} file(s)`)
      } catch (err) {
        showSnackbar(err?.detail || 'Attach failed')
      }
    }
    picker.click()
  }, [workspaceId, chatroomId, showSnackbar])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])


  const handleHeaderButton = useCallback((Icon, event) => {
    if (Icon === Search) {
      setSearchOpen((prev) => {
        if (prev) setSearchQuery('')
        return !prev
      })
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
    const text = msg.body
    navigator.clipboard.writeText(text).then(() => {
      showSnackbar('Copied to clipboard')
    }).catch(() => {
      showSnackbar('Copied to clipboard')
    })
  }, [showSnackbar])

  const handleRegenerate = useCallback((aiMsg) => {
    if (streamingId != null || !workspaceId || !chatroomId) return
    if (!aiMsg?.serverId || aiMsg.role !== 'ai') {
      showSnackbar('This reply is not ready to regenerate yet')
      return
    }
    const idx = messages.findIndex((m) => m.id === aiMsg.id)
    if (idx < 0) return
    let hasPrevUser = false
    for (let i = idx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        hasPrevUser = true
        break
      }
    }
    if (!hasPrevUser) {
      showSnackbar('No earlier user message to reuse')
      return
    }
    setStreamingId(aiMsg.id)
    setMessages((prev) =>
      prev.map((m) => (m.id === aiMsg.id ? { ...m, body: '', sources: null } : m)),
    )
    chatService.sendMessage(
      workspaceId,
      chatroomId,
      '',
      (chunk) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiMsg.id ? { ...m, body: m.body + chunk } : m)),
        )
      },
      (sources, aiMessageId) => {
        if (sources.length > 0) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsg.id ? { ...m, sources: sources.map((s) => s.filename) } : m,
            ),
          )
        }
        if (aiMessageId) {
          setMessages((prev) =>
            prev.map((m) => (m.id === aiMsg.id ? { ...m, serverId: aiMessageId } : m)),
          )
        }
        setStreamingId(null)
      },
      (error) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiMsg.id ? { ...m, body: error } : m)),
        )
        setStreamingId(null)
      },
      { regenerateForAiMessageId: aiMsg.serverId },
    )
  }, [streamingId, workspaceId, chatroomId, messages, showSnackbar])

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
      handleAttachClick()
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
  }, [input, showSnackbar, handleAttachClick])


  const handleSourceClick = useCallback((name) => {
    setSourceDialog({ open: true, name })
  }, [])


  const renderMessageActions = (msg) => {
    const thumbState = thumbsState[msg.id]
    const regenBusy = msg.role === 'ai' && streamingId === msg.id
    const actions = [
      { Icon: Copy, handler: () => handleCopy(msg), tooltip: 'Copy' },
      {
        Icon: RefreshCw,
        handler: () => handleRegenerate(msg),
        tooltip: 'Regenerate',
        disabled: streamingId != null,
        busy: regenBusy,
      },
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
        {actions.map(({ Icon, handler, tooltip, filled, disabled: actionDisabled, busy }) => (
          <Tooltip
            key={tooltip}
            title={busy ? 'Regenerating…' : tooltip}
            arrow
          >
            <span>
              <IconButton
                size="small"
                onClick={handler}
                disabled={actionDisabled}
                sx={{
                  width: 28,
                  height: 28,
                  color: filled ? 'primary.main' : 'text.disabled',
                  '&:hover': { color: 'text.secondary', bgcolor: 'rgba(28,27,26,0.04)' },
                }}
              >
                {busy ? (
                  <CircularProgress size={12} thickness={5} color="inherit" />
                ) : (
                  <Icon size={13} fill={filled ? 'currentColor' : 'none'} />
                )}
              </IconButton>
            </span>
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
          <span className="text-[15px] font-semibold text-ink">
            {chatroomName ? `# ${chatroomName}` : 'Talos AI'}
          </span>
          <Chip label="AI" color="primary" size="small" sx={{ height: 20, fontSize: 10 }} />
          {workspaceName && (
            <span className="text-[12px] text-ink-tertiary">· {workspaceName}</span>
          )}
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
            placeholder="Search this conversation…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setSearchOpen(false)
                setSearchQuery('')
              }
            }}
            autoFocus
            fullWidth
            sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
          />
          {searchQuery.trim() ? (
            <span className="text-xs text-ink-tertiary tabular-nums shrink-0 w-[4.5rem] text-right">
              {displayMessages.length}
              {' '}
              {displayMessages.length === 1 ? 'match' : 'matches'}
            </span>
          ) : null}
          <IconButton
            size="small"
            onClick={() => { setSearchOpen(false); setSearchQuery('') }}
            sx={{ color: 'text.secondary' }}
            title="Close search"
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

          {searchOpen && searchQuery.trim() && displayMessages.length === 0 && messages.length > 0 && (
            <p className="text-center text-sm text-ink-tertiary py-10 px-4">
              No messages match in this thread. Try different words, or check spelling.
            </p>
          )}

          {searchOpen && searchQuery.trim() && displayMessages.length === 0 && messages.length === 0 && (
            <p className="text-center text-sm text-ink-tertiary py-10 px-4">
              No messages to search yet.
            </p>
          )}

          {displayMessages.map((msg, i) => (
            <div
              key={msg.id}
              ref={i === 0 && searchOpen && searchQuery.trim() ? firstSearchHitRef : undefined}
              className="flex gap-3 mb-6 group"
            >
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

                <ChatMessageContent
                  content={msg.body || ''}
                  renderCursor={msg.role === 'ai' && streamingId != null && streamingId === msg.id}
                />

                {msg.attachments && msg.attachments.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {msg.attachments.map((a, i) => (
                      <Chip
                        key={attachmentKey(a, i)}
                        label={attachmentLabel(a)}
                        size="small"
                        icon={<FileText size={12} />}
                        sx={{ maxWidth: 240 }}
                      />
                    ))}
                  </div>
                )}

                {msg.role === 'user' && msg.serverId && (
                  <div className="mt-2">
                    <Tooltip title="Attach more files to this message" arrow>
                      <IconButton size="small" onClick={() => handleAttachToMessage(msg)}>
                        <Paperclip size={14} />
                      </IconButton>
                    </Tooltip>
                  </div>
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

      {/* Hidden file input for chat attachments */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.txt,.md,image/*"
        onChange={handleFileInputChange}
        style={{ display: 'none' }}
      />

      {/* Input */}
      <div className="border-t border-[rgba(28,27,26,0.06)] bg-surface-1">
        <div className="max-w-[680px] mx-auto px-5 py-4">
          <div className="bg-base border border-[rgba(28,27,26,0.10)] rounded-2xl p-3 px-4 flex flex-col gap-0 focus-within:border-amber focus-within:shadow-[0_0_0_3px_rgba(196,145,58,0.12)] transition-all">
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pb-2 mb-2 border-b border-[rgba(28,27,26,0.06)] -mx-1 px-1">
                {attachments.map((a) => (
                  <Chip
                    key={a.file_id}
                    label={a.filename}
                    size="small"
                    icon={
                      a.status === 'uploading'
                        ? <CircularProgress size={12} sx={{ ml: 0.5 }} />
                        : <FileText size={12} />
                    }
                    onDelete={a.status === 'ready' ? () => handleRemoveAttachment(a.file_id) : undefined}
                    sx={{ maxWidth: 240 }}
                  />
                ))}
              </div>
            )}
            <div className="flex items-end gap-3 min-w-0">
              <div className="flex-1 flex flex-col min-w-0">
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
                <ChatComposerField
                  inputRef={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Message #channel — use **markdown**, `code`, and…"
                />
              </div>
              <button
                onClick={handleSend}
                className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 transition-all ${
                  input.trim() || attachments.some((a) => a.status === 'ready')
                    ? 'bg-amber text-white shadow-sm hover:bg-amber-hover hover:shadow-md'
                    : 'bg-surface-3 text-ink-muted cursor-default'
                }`}
                disabled={(!input.trim() && !attachments.some((a) => a.status === 'ready')) || streamingId != null || uploading}
              >
                <ArrowUp size={16} strokeWidth={2.5} />
              </button>
            </div>
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
              Document preview not available yet
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
