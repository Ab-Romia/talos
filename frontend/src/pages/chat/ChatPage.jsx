import { useState, useRef, useEffect, useCallback, useMemo, useLayoutEffect } from 'react'
import Avatar from '@mui/material/Avatar'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import Snackbar from '@mui/material/Snackbar'
import Popover from '@mui/material/Popover'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemAvatar from '@mui/material/ListItemAvatar'
import ListItemText from '@mui/material/ListItemText'
import {
  Search, Users, Bold, Code, ArrowUp, X,
} from 'lucide-react'

import { useSelector } from 'react-redux'
import { chatService } from '../../services/chat'
import { onChatMessage, getSocket } from '../../services/socket'
import { ChatMessageContent } from '../../components/chat/ChatMessageContent'
import { ChatComposerField } from '../../components/chat/ChatComposerField'

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function nowTime() {
  return new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function initialsOf(name) {
  return (name || 'M')
    .split(' ')
    .map((n) => n[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

function messageMatchesQuery(msg, rawQuery) {
  const s = rawQuery.trim().toLowerCase()
  if (!s) return true
  if ((msg.body || '').toLowerCase().includes(s)) return true
  return false
}

export default function ChatPage() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const [snackbar, setSnackbar] = useState({ open: false, message: '' })
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [usersAnchor, setUsersAnchor] = useState(null)
  const [members, setMembers] = useState([])
  const [onlineIds, setOnlineIds] = useState(() => new Set())
  const [membersLoading, setMembersLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [chatroomName, setChatroomName] = useState('')

  const user = useSelector((state) => state.auth.user)
  const {
    workspaces,
    chatrooms,
    activeWorkspaceId: workspaceId,
    activeChatroomId: chatroomId,
  } = useSelector((s) => s.workspace)

  const workspaceName = useMemo(
    () => workspaces.find((w) => w.id === workspaceId)?.name || '',
    [workspaces, workspaceId],
  )

  const threadRef = useRef(null)
  const textareaRef = useRef(null)
  const nextIdRef = useRef(1)
  const firstSearchHitRef = useRef(null)
  const lastScrolledFirstMatchId = useRef(null)

  const membersMap = useMemo(() => {
    const map = new Map()
    for (const m of members) map.set(String(m.id), m.name || m.username)
    return map
  }, [members])

  const displayName = useCallback(
    (senderId) => {
      if (senderId && senderId === user?.id) return user?.name || user?.username || 'You'
      return membersMap.get(String(senderId)) || 'Member'
    },
    [user, membersMap],
  )

  // MessageSchema dict -> UI message.
  const toUiMessage = useCallback(
    (m) => ({
      id: nextIdRef.current++,
      serverId: m.id,
      senderId: m.sender_id,
      role: m.role,
      mine: m.sender_id === user?.id,
      time: fmtTime(m.sent_at),
      body: m.content,
    }),
    [user],
  )

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
    const cr = chatrooms.find((c) => c.id === chatroomId)
    setChatroomName(cr?.name || '')
  }, [chatrooms, chatroomId])

  // Load message history when the active channel changes.
  useEffect(() => {
    if (!chatroomId) {
      setMessages([])
      return
    }
    let cancelled = false
    setMessages([])
    ;(async () => {
      try {
        const history = await chatService.getMessages(chatroomId)
        if (cancelled) return
        const list = Array.isArray(history) ? history : (history?.messages ?? [])
        // Backend returns newest-first; show chronologically.
        const mapped = [...list].reverse().map(toUiMessage)
        setMessages(mapped)
      } catch (err) {
        if (!cancelled) console.error('Load messages failed:', err)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [chatroomId, toUiMessage])

  // Realtime: subscribe to broadcast `message` events for the active channel.
  useEffect(() => {
    if (!chatroomId) return
    getSocket() // ensure the shared socket is connected
    const off = onChatMessage((payload) => {
      // Backend broadcasts the serialized MessageSchema dict. (A legacy path may
      // wrap it as {message: "<json>"} — tolerate both.)
      let m = payload
      if (m && typeof m.message === 'string') {
        try {
          m = JSON.parse(m.message)
        } catch {
          return
        }
      }
      if (!m || m.channel_id !== chatroomId) return

      setMessages((prev) => {
        if (prev.some((x) => x.serverId === m.id)) return prev
        // Adopt our own optimistic message (echoed back to the sender).
        if (m.sender_id === user?.id) {
          for (let i = prev.length - 1; i >= 0; i--) {
            const x = prev[i]
            if (x.mine && !x.serverId && x.body === m.content) {
              const next = [...prev]
              next[i] = { ...x, serverId: m.id, time: fmtTime(m.sent_at) }
              return next
            }
          }
        }
        return [...prev, toUiMessage(m)]
      })
    })
    return off
  }, [chatroomId, user, toUiMessage])

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

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || sending || !chatroomId) return

    const localKey = nextIdRef.current++
    const optimistic = {
      id: localKey,
      serverId: null,
      senderId: user?.id,
      role: 'user',
      mine: true,
      time: nowTime(),
      body: text,
    }
    setMessages((prev) => [...prev, optimistic])
    setInput('')
    setSending(true)
    try {
      const res = await chatService.sendMessage(chatroomId, text)
      // Attach the real server id (if the socket echo didn't already adopt it).
      if (res?.id) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === localKey && !m.serverId
              ? { ...m, serverId: res.id, time: fmtTime(res.sent_at) || m.time }
              : m,
          ),
        )
      }
    } catch (err) {
      // Roll back the optimistic message and restore the draft.
      setMessages((prev) => prev.filter((m) => m.id !== localKey))
      setInput(text)
      showSnackbar(err?.detail || 'Failed to send message')
    } finally {
      setSending(false)
    }
  }, [input, sending, chatroomId, user, showSnackbar])

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  const loadMembers = useCallback(async () => {
    if (!workspaceId) return
    setMembersLoading(true)
    try {
      const list = await chatService.getMembers(workspaceId)
      setMembers(Array.isArray(list) ? list : [])
    } catch (err) {
      setMembers([])
      showSnackbar(err?.detail || 'Could not load members')
    } finally {
      setMembersLoading(false)
    }
    if (chatroomId) {
      try {
        const res = await chatService.getOnline(chatroomId)
        setOnlineIds(new Set((res?.online_users || []).map(String)))
      } catch {
        setOnlineIds(new Set())
      }
    }
  }, [workspaceId, chatroomId, showSnackbar])

  // Load members eagerly so display names are available for messages.
  useEffect(() => { loadMembers() }, [loadMembers])

  const handleHeaderButton = useCallback(
    (Icon, event) => {
      if (Icon === Search) {
        setSearchOpen((prev) => {
          if (prev) setSearchQuery('')
          return !prev
        })
      } else if (Icon === Users) {
        setUsersAnchor(event.currentTarget)
        loadMembers()
      }
    },
    [loadMembers],
  )

  const handleToolbar = useCallback(
    (Icon) => {
      const textarea = textareaRef.current
      if (!textarea) return

      const start = textarea.selectionStart
      const end = textarea.selectionEnd
      const selected = input.substring(start, end)

      let newText
      let cursorPos
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
    },
    [input],
  )

  const headerIcons = [Search, Users]
  const toolbarIcons = [Bold, Code]

  return (
    <div className="flex flex-col h-full bg-base">
      {/* Header */}
      <header className="h-14 bg-surface-1 border-b border-[rgba(28,27,26,0.08)] flex items-center justify-between px-5 shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="w-2 h-2 bg-success rounded-full" />
          <span className="text-[15px] font-semibold text-ink">
            {chatroomName ? `# ${chatroomName}` : 'Select a channel'}
          </span>
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
            onClick={() => {
              setSearchOpen(false)
              setSearchQuery('')
            }}
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

          {!chatroomId && (
            <p className="text-center text-sm text-ink-tertiary py-10 px-4">
              No channel selected yet.
            </p>
          )}

          {chatroomId && messages.length === 0 && !(searchOpen && searchQuery.trim()) && (
            <p className="text-center text-sm text-ink-tertiary py-10 px-4">
              No messages yet — say hello 👋
            </p>
          )}

          {searchOpen && searchQuery.trim() && displayMessages.length === 0 && messages.length > 0 && (
            <p className="text-center text-sm text-ink-tertiary py-10 px-4">
              No messages match in this thread. Try different words, or check spelling.
            </p>
          )}

          {displayMessages.map((msg, i) => {
            if (msg.role === 'system') {
              return (
                <div
                  key={msg.id}
                  ref={i === 0 && searchOpen && searchQuery.trim() ? firstSearchHitRef : undefined}
                  className="flex justify-center mb-4"
                >
                  <span className="text-[12px] text-ink-tertiary italic">{msg.body}</span>
                </div>
              )
            }
            return (
              <div
                key={msg.id}
                ref={i === 0 && searchOpen && searchQuery.trim() ? firstSearchHitRef : undefined}
                className="flex gap-3 mb-6 group"
              >
                <div className="pt-0.5">
                  <Avatar
                    sx={{
                      width: 34,
                      height: 34,
                      bgcolor: msg.mine ? 'primary.light' : '#EEEDEA',
                      color: msg.mine ? 'primary.main' : 'text.secondary',
                      fontSize: 13,
                      fontWeight: 600,
                      flexShrink: 0,
                    }}
                  >
                    {initialsOf(displayName(msg.senderId))}
                  </Avatar>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[13px] font-semibold text-ink">{displayName(msg.senderId)}</span>
                    <span className="text-[12px] text-ink-muted">{msg.time}</span>
                  </div>
                  <ChatMessageContent content={msg.body || ''} renderCursor={false} />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-[rgba(28,27,26,0.06)] bg-surface-1">
        <div className="max-w-[680px] mx-auto px-5 py-4">
          <div className="bg-base border border-[rgba(28,27,26,0.10)] rounded-2xl p-3 px-4 flex flex-col gap-0 focus-within:border-amber focus-within:shadow-[0_0_0_3px_rgba(196,145,58,0.12)] transition-all">
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
                  placeholder={chatroomName ? `Message #${chatroomName}` : 'Message…'}
                />
              </div>
              <button
                onClick={handleSend}
                className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 transition-all ${
                  input.trim() && chatroomId
                    ? 'bg-amber text-white shadow-sm hover:bg-amber-hover hover:shadow-md'
                    : 'bg-surface-3 text-ink-muted cursor-default'
                }`}
                disabled={!input.trim() || !chatroomId || sending}
              >
                <ArrowUp size={16} strokeWidth={2.5} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Members Popover */}
      <Popover
        open={Boolean(usersAnchor)}
        anchorEl={usersAnchor}
        onClose={() => setUsersAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { mt: 1, borderRadius: 2, minWidth: 240 } } }}
      >
        <Typography sx={{ px: 2, pt: 1.5, pb: 0.5, fontSize: 13, fontWeight: 600, color: 'text.secondary' }}>
          Workspace Members{members.length ? ` · ${members.length}` : ''}
        </Typography>
        {membersLoading && members.length === 0 ? (
          <Typography sx={{ px: 2, py: 1.5, fontSize: 13, color: 'text.disabled' }}>Loading…</Typography>
        ) : members.length === 0 ? (
          <Typography sx={{ px: 2, py: 1.5, fontSize: 13, color: 'text.disabled' }}>No members yet.</Typography>
        ) : (
          <List dense sx={{ py: 0.5 }}>
            {members.map((m) => {
              const online = onlineIds.has(String(m.id))
              return (
                <ListItem key={m.id} sx={{ py: 0.5, gap: 1 }}>
                  <ListItemAvatar sx={{ minWidth: 40 }}>
                    <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: '#EEEDEA', color: 'text.secondary' }}>
                      {initialsOf(m.name)}
                    </Avatar>
                  </ListItemAvatar>
                  <ListItemText
                    primary={
                      <span className="flex items-center gap-1.5">
                        <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${online ? 'bg-success' : 'bg-gray-300'}`} />
                        {m.name}
                      </span>
                    }
                    secondary={m.is_owner ? 'Owner' : (online ? 'Online' : 'Offline')}
                    primaryTypographyProps={{ fontSize: 13, component: 'div' }}
                    secondaryTypographyProps={{ fontSize: 11 }}
                  />
                </ListItem>
              )
            })}
          </List>
        )}
      </Popover>

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
