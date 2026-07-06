import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
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
  Search, Users, Bold, Code, ArrowUp, X, Sparkles, Bug, Reply, Paperclip, FileText,
} from 'lucide-react'

import { useSelector, useDispatch as useReduxDispatch } from 'react-redux'
import { markChannelUnread, loadDms } from '../../store/workspaceSlice'
import { usePermissions } from '../../contexts/PermissionsContext'
import { chatService } from '../../services/chat'
import { getBotIdentity } from '../../services/ai'
import { onChatMessage, onAiTyping, getSocket } from '../../services/socket'
import { RagTracePanel } from '../../components/chat/RagTracePanel'
import { askService } from '../../services/ask'
import { AiTypingIndicator } from '../../components/chat/AiTypingIndicator'
import { ChatComposerField } from '../../components/chat/ChatComposerField'
import { MentionPicker } from '../../components/chat/MentionPicker'
import { RichMessageBody } from '../../components/chat/RichMessageBody'
import { AttachmentView } from '../../components/chat/AttachmentView'
import { docText } from '../../utils/prosemirrorText'
import { buildMessageDoc, activeMentions } from '../../utils/mentionDoc'

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
  const reduxDispatch = useReduxDispatch()
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
  const [aiThinking, setAiThinking] = useState(false)
  const [debugTrace, setDebugTrace] = useState(false)
  const [bot, setBot] = useState(null)
  const [mentionQuery, setMentionQuery] = useState(null) // { start, query } while typing @…
  const [mentionIndex, setMentionIndex] = useState(0)
  const [replyTo, setReplyTo] = useState(null) // { serverId, uiId, name, snippet }
  const [pendingAttachments, setPendingAttachments] = useState([]) // uploaded, not yet sent
  const [uploadingCount, setUploadingCount] = useState(0)
  const trackedMentionsRef = useRef([]) // [{ label, user_id }] inserted via the picker
  const attachInputRef = useRef(null)

  const user = useSelector((state) => state.auth.user)
  const {
    workspaces,
    chatrooms,
    dms,
    activeWorkspaceId: workspaceId,
    activeChatroomId: chatroomId,
  } = useSelector((s) => s.workspace)

  const activeDm = useMemo(
    () => dms.find((d) => d.id === chatroomId) || null,
    [dms, chatroomId],
  )

  const { hasChannelPerm, channelPermsLoaded } = usePermissions()
  const canSend = hasChannelPerm('channel.message', 'send')
  const canViewPresence = hasChannelPerm('channel.member', 'view_presence')

  const workspaceName = useMemo(
    () => workspaces.find((w) => w.id === workspaceId)?.name || '',
    [workspaces, workspaceId],
  )

  const threadRef = useRef(null)
  const textareaRef = useRef(null)
  const nextIdRef = useRef(1)
  const membersMapRef = useRef(new Map())
  const aiThinkingTimer = useRef(null)
  const firstSearchHitRef = useRef(null)
  const lastScrolledFirstMatchId = useRef(null)

  const membersMap = useMemo(() => {
    const map = new Map()
    for (const m of members) map.set(String(m.id), m.name || m.username)
    membersMapRef.current = map
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
    (m) => {
      const isAI = m.role === 'assistant'
      const name = isAI ? 'Talos AI' : displayName(m.sender_id)
      return {
        id: nextIdRef.current++,
        serverId: m.id,
        senderId: m.sender_id,
        role: m.role,
        isAI,
        mine: m.sender_id === user?.id,
        name,
        initials: initialsOf(name),
        time: fmtTime(m.sent_at),
        body: docText(m.content),
        content: m.content,
        replyToId: m.reply_to_id || null,
        attachments: m.attachments || [],
      }
    },
    [displayName, user],
  )

  // Bot identity for the mention picker (@Talos AI triggers the assistant).
  useEffect(() => {
    if (!workspaceId) { setBot(null); return }
    let cancelled = false
    getBotIdentity(workspaceId)
      .then((b) => { if (!cancelled && b?.user_id) setBot(b) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [workspaceId])

  const mentionCandidates = useMemo(() => {
    if (!mentionQuery) return []
    const q = mentionQuery.query.toLowerCase()
    const pool = [
      ...(bot ? [{ user_id: bot.user_id, label: bot.name || 'Talos AI', isBot: true }] : []),
      ...members
        .filter((m) => String(m.id) !== String(user?.id))
        .map((m) => ({ user_id: String(m.id), label: m.name || m.username, isBot: false })),
    ]
    return pool.filter((c) => c.label && c.label.toLowerCase().includes(q)).slice(0, 8)
  }, [mentionQuery, bot, members, user])

  const searchResults = useMemo(() => {
    if (!searchOpen) return []
    const q = searchQuery.trim()
    if (!q) return []
    return messages.filter((m) => messageMatchesQuery(m, q))
  }, [messages, searchQuery, searchOpen])

  const highlightedMessageId = useRef(null)

  const scrollToMessage = useCallback((msgId) => {
    highlightedMessageId.current = msgId
    const el = document.querySelector(`[data-msg-id="${msgId}"]`)
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      el.classList.add('search-highlight')
      setTimeout(() => el.classList.remove('search-highlight'), 2000)
    }
  }, [])

  useEffect(() => {
    const cr = chatrooms.find((c) => c.id === chatroomId)
    if (cr) {
      setChatroomName(cr.name || '')
      return
    }
    const dm = dms.find((d) => d.id === chatroomId)
    setChatroomName(dm ? (dm.peer?.name || 'Direct message') : '')
  }, [chatrooms, dms, chatroomId])

  // Clear messages when switching channels.
  useEffect(() => {
    setMessages([])
  }, [chatroomId])

  useEffect(() => {
    if (!chatroomId) return
    let cancelled = false
    ;(async () => {
      try {
        const history = await chatService.getMessages(chatroomId)
        if (cancelled) return
        const list = Array.isArray(history) ? history : (history?.messages ?? [])
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
    const off = onChatMessage((payload) => {
      let m = payload
      if (m && typeof m.message === 'string') {
        try {
          m = JSON.parse(m.message)
        } catch {
          return
        }
      }
      if (!m) return

      // Track unread + OS notification for messages from others in different channels
      if (m.sender_id && m.sender_id !== user?.id && m.channel_id !== chatroomId) {
        // A message in a conversation we don't know yet = a peer just opened a
        // DM with us; refresh the DM list so it appears in the sidebar.
        if (
          !chatrooms.some((c) => c.id === m.channel_id) &&
          !dms.some((d) => d.id === m.channel_id) &&
          workspaceId
        ) {
          reduxDispatch(loadDms(workspaceId))
        }
        reduxDispatch(markChannelUnread(m.channel_id))
        if ('Notification' in window && Notification.permission === 'granted') {
          try {
            const senderName = membersMapRef.current.get(String(m.sender_id)) || 'Someone'
            const chName = chatrooms.find((c) => c.id === m.channel_id)?.name
            new Notification(chName ? `${senderName} in #${chName}` : senderName, {
              body: docText(m.content).slice(0, 200),
              icon: '/favicon.svg',
              tag: m.id || `msg-${Date.now()}`,
            })
          } catch { /* ignore */ }
        }
      }

      if (m.channel_id !== chatroomId) return

      // The assistant's reply has landed — retire any "thinking" indicator
      // even if the stop signal was dropped.
      if (m.role === 'assistant') setAiThinking(false)

      setMessages((prev) => {
        if (prev.some((x) => x.serverId === m.id)) return prev
        if (m.sender_id === user?.id) {
          for (let i = prev.length - 1; i >= 0; i--) {
            const x = prev[i]
            if (x.mine && !x.serverId && x.body === docText(m.content)) {
              const next = [...prev]
              next[i] = { ...x, serverId: m.id, time: fmtTime(m.sent_at) }
              return next
            }
          }
        }
        return [...prev, toUiMessage(m)]
      })
    })
    return () => off()
  }, [chatroomId, user, toUiMessage, chatrooms, dms, workspaceId, reduxDispatch])

  // Realtime: show a live "Talos is thinking…" indicator between the trigger
  // message and the assistant's reply. Ephemeral — reset on channel switch and
  // guarded by a safety timeout so a dropped stop signal can't pin it forever.
  useEffect(() => {
    setAiThinking(false)
    if (aiThinkingTimer.current) {
      clearTimeout(aiThinkingTimer.current)
      aiThinkingTimer.current = null
    }
    if (!chatroomId) return
    getSocket()
    const off = onAiTyping((payload) => {
      if (!payload || payload.channel_id !== chatroomId) return
      if (payload.status === 'start') {
        setAiThinking(true)
        if (aiThinkingTimer.current) clearTimeout(aiThinkingTimer.current)
        aiThinkingTimer.current = setTimeout(() => setAiThinking(false), 90000)
      } else {
        setAiThinking(false)
        if (aiThinkingTimer.current) {
          clearTimeout(aiThinkingTimer.current)
          aiThinkingTimer.current = null
        }
      }
    })
    return () => {
      off()
      if (aiThinkingTimer.current) {
        clearTimeout(aiThinkingTimer.current)
        aiThinkingTimer.current = null
      }
    }
  }, [chatroomId])

  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [messages, aiThinking])

  const showSnackbar = useCallback((message) => {
    setSnackbar({ open: true, message })
  }, [])

  const closeSnackbar = useCallback(() => {
    setSnackbar((prev) => ({ ...prev, open: false }))
  }, [])

  // Track an in-progress "@query" at the caret so the picker can open.
  const detectMention = useCallback((text, caret) => {
    const upto = text.slice(0, caret)
    const at = upto.lastIndexOf('@')
    if (at === -1) { setMentionQuery(null); return }
    if (at > 0 && /[\w@]/.test(upto[at - 1])) { setMentionQuery(null); return }
    const query = upto.slice(at + 1)
    if (query.length > 30 || query.includes('\n')) { setMentionQuery(null); return }
    setMentionQuery({ start: at, query })
    setMentionIndex(0)
  }, [])

  const handleInputChange = useCallback((e) => {
    const text = e.target.value
    setInput(text)
    detectMention(text, e.target.selectionStart ?? text.length)
  }, [detectMention])

  const pickMention = useCallback((candidate) => {
    if (!mentionQuery) return
    const token = `@${candidate.label} `
    const caret = textareaRef.current?.selectionStart ?? input.length
    const next = input.slice(0, mentionQuery.start) + token + input.slice(caret)
    const tracked = trackedMentionsRef.current
    if (!tracked.some((m) => m.user_id === candidate.user_id)) {
      tracked.push({ label: candidate.label, user_id: candidate.user_id })
    }
    setInput(next)
    setMentionQuery(null)
    setTimeout(() => {
      const ta = textareaRef.current
      if (ta) {
        ta.focus()
        const pos = mentionQuery.start + token.length
        ta.setSelectionRange(pos, pos)
      }
    }, 0)
  }, [mentionQuery, input])

  const handleAttachFiles = useCallback(async (fileList) => {
    const files = Array.from(fileList || [])
    if (!files.length || !chatroomId) return
    setUploadingCount((n) => n + files.length)
    for (const file of files) {
      try {
        const meta = await chatService.uploadAttachment(chatroomId, file)
        setPendingAttachments((prev) => [...prev, meta])
      } catch (err) {
        showSnackbar(err?.detail || `Could not attach ${file.name}`)
      } finally {
        setUploadingCount((n) => n - 1)
      }
    }
  }, [chatroomId, showSnackbar])

  const sendText = useCallback(async (rawText) => {
    const text = (rawText ?? '').trim()
    const attachments = pendingAttachments
    if ((!text && !attachments.length) || sending || !chatroomId) return

    const mentions = activeMentions(text, trackedMentionsRef.current)
    const reply = replyTo
    const rich = mentions.length > 0 || reply

    const localKey = nextIdRef.current++
    const optimistic = {
      id: localKey,
      serverId: null,
      senderId: user?.id,
      role: 'user',
      mine: true,
      time: nowTime(),
      body: text,
      content: rich ? buildMessageDoc(text, mentions) : null,
      replyToId: reply?.serverId || null,
      attachments,
    }
    setMessages((prev) => [...prev, optimistic])
    setInput('')
    setReplyTo(null)
    setMentionQuery(null)
    setPendingAttachments([])
    trackedMentionsRef.current = []
    setSending(true)
    try {
      const res = await chatService.sendMessage(
        chatroomId,
        {
          ...(rich ? { content: buildMessageDoc(text, mentions) } : { text }),
          replyToId: reply?.serverId || null,
          attachmentIds: attachments.map((a) => a.id),
        },
      )
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
      if (mentions.length) trackedMentionsRef.current = mentions
      if (reply) setReplyTo(reply)
      if (attachments.length) setPendingAttachments(attachments)
      showSnackbar(err?.detail || 'Failed to send message')
    } finally {
      setSending(false)
    }
  }, [sending, chatroomId, user, showSnackbar, replyTo, pendingAttachments])

  const handleSend = useCallback(() => sendText(input), [sendText, input])

  const handleAskAI = useCallback(async () => {
    const t = input.trim()
    if (!t) return
    if (!debugTrace) {
      sendText(t.toLowerCase().startsWith('@talos') ? t : `@talos ${t}`)
      return
    }
    // Debug mode: go through /ask (persists + answers) and render the full
    // RAG trace under the reply. The question is shown locally right away.
    const question = t.replace(/^@talos\s*/i, '')
    setInput('')
    setMessages((prev) => [
      ...prev,
      {
        id: nextIdRef.current++,
        senderId: user?.id,
        role: 'user',
        isAI: false,
        mine: true,
        name: user?.name || 'You',
        initials: initialsOf(user?.name || 'You'),
        time: fmtTime(new Date().toISOString()),
        body: question,
      },
    ])
    setAiThinking(true)
    try {
      const { answer, trace } = await askService.askWithDebug(chatroomId, question)
      setMessages((prev) => [
        ...prev,
        {
          id: nextIdRef.current++,
          senderId: null,
          role: 'assistant',
          isAI: true,
          mine: false,
          name: 'Talos AI',
          initials: 'AI',
          time: fmtTime(new Date().toISOString()),
          body: answer,
          trace,
        },
      ])
    } catch (err) {
      showSnackbar(err?.detail || 'Ask failed')
    } finally {
      setAiThinking(false)
    }
  }, [sendText, input, debugTrace, chatroomId, user, showSnackbar])

  const handleKeyDown = useCallback(
    (e) => {
      if (mentionQuery && mentionCandidates.length) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setMentionIndex((i) => (i + 1) % mentionCandidates.length)
          return
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          setMentionIndex((i) => (i - 1 + mentionCandidates.length) % mentionCandidates.length)
          return
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault()
          pickMention(mentionCandidates[mentionIndex] || mentionCandidates[0])
          return
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          setMentionQuery(null)
          return
        }
      }
      if (e.key === 'Escape' && replyTo) {
        e.preventDefault()
        setReplyTo(null)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend, mentionQuery, mentionCandidates, mentionIndex, pickMention, replyTo],
  )

  const startReply = useCallback((msg) => {
    if (!msg.serverId) return
    setReplyTo({
      serverId: msg.serverId,
      uiId: msg.id,
      name: msg.isAI ? 'Talos AI' : displayName(msg.senderId),
      snippet: (msg.body || '').slice(0, 90),
    })
    setTimeout(() => textareaRef.current?.focus(), 0)
  }, [displayName])

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

  const headerIcons = canViewPresence ? [Search, Users] : [Search]
  const toolbarIcons = [Bold, Code]

  return (
    <div className="flex flex-col h-full bg-base">
      {/* Header */}
      <header className="h-14 bg-surface-1 border-b border-[rgba(28,27,26,0.08)] flex items-center justify-between px-5 shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="w-2 h-2 bg-success rounded-full" />
          <span className="text-[15px] font-semibold text-ink">
            {chatroomName ? (activeDm ? chatroomName : `# ${chatroomName}`) : 'Select a channel'}
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

      {/* Search bar with overlay dropdown */}
      {searchOpen && (
        <div className="relative bg-surface-1 border-b border-[rgba(28,27,26,0.08)] px-5 py-2 flex items-center gap-2 shrink-0">
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
              {searchResults.length}
              {' '}
              {searchResults.length === 1 ? 'match' : 'matches'}
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

          {/* Search results overlay */}
          {searchQuery.trim() && (
            <div className="absolute top-full left-0 right-0 z-50 mx-5 mt-1 bg-base border border-[rgba(28,27,26,0.10)] rounded-xl shadow-lg max-h-[360px] overflow-y-auto">
              {searchResults.length === 0 ? (
                <p className="text-sm text-ink-tertiary text-center py-6 px-4">
                  No messages match your search.
                </p>
              ) : (
                searchResults.map((msg) => {
                  const q = searchQuery.trim().toLowerCase()
                  const body = msg.body || ''
                  const idx = body.toLowerCase().indexOf(q)
                  let before = '', match = '', after = ''
                  if (idx >= 0) {
                    before = body.slice(Math.max(0, idx - 40), idx)
                    if (idx > 40) before = '…' + before
                    match = body.slice(idx, idx + q.length)
                    after = body.slice(idx + q.length, idx + q.length + 60)
                    if (idx + q.length + 60 < body.length) after += '…'
                  } else {
                    before = body.slice(0, 100)
                    if (body.length > 100) before += '…'
                  }

                  return (
                    <button
                      key={msg.id}
                      className="w-full text-left px-4 py-3 hover:bg-surface-2 transition-colors border-b border-[rgba(28,27,26,0.04)] last:border-b-0 flex gap-3 items-start"
                      onClick={() => {
                        scrollToMessage(msg.id)
                        setSearchOpen(false)
                        setSearchQuery('')
                      }}
                    >
                      <Avatar
                        sx={{
                          width: 28,
                          height: 28,
                          bgcolor: msg.mine ? 'primary.light' : '#EEEDEA',
                          color: msg.mine ? 'primary.main' : 'text.secondary',
                          fontSize: 11,
                          fontWeight: 600,
                          flexShrink: 0,
                          mt: 0.25,
                        }}
                      >
                        {initialsOf(displayName(msg.senderId))}
                      </Avatar>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-[13px] font-semibold text-ink truncate">{displayName(msg.senderId)}</span>
                          <span className="text-[11px] text-ink-muted shrink-0">{msg.time}</span>
                        </div>
                        <p className="text-[13px] text-ink-secondary truncate">
                          {before}<mark className="bg-amber/25 text-ink rounded-sm px-0.5">{match}</mark>{after}
                        </p>
                      </div>
                    </button>
                  )
                })
              )}
            </div>
          )}
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

          {chatroomId && messages.length === 0 && (
            <p className="text-center text-sm text-ink-tertiary py-10 px-4">
              No messages yet — say hello 👋
            </p>
          )}

          {messages.map((msg) => {
            if (msg.role === 'system') {
              return (
                <div
                  key={msg.id}
                  data-msg-id={msg.id}
                  className="flex justify-center mb-4"
                >
                  <span className="text-[12px] text-ink-tertiary italic">{msg.body}</span>
                </div>
              )
            }
            const repliedTo = msg.replyToId
              ? messages.find((x) => x.serverId === msg.replyToId)
              : null
            return (
              <div
                key={msg.id}
                data-msg-id={msg.id}
                className="relative flex gap-3 mb-6 group transition-colors duration-500"
              >
                <div className="pt-0.5">
                  <Avatar
                    sx={{
                      width: 34,
                      height: 34,
                      bgcolor: msg.isAI ? 'rgba(196,145,58,0.15)' : msg.mine ? 'primary.light' : '#EEEDEA',
                      color: msg.isAI ? '#C4913A' : msg.mine ? 'primary.main' : 'text.secondary',
                      fontSize: 13,
                      fontWeight: 600,
                      flexShrink: 0,
                    }}
                  >
                    {msg.isAI ? <Sparkles size={16} /> : msg.initials}
                  </Avatar>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[13px] font-semibold text-ink">{msg.isAI ? 'Talos AI' : displayName(msg.senderId)}</span>
                    <span className="text-[12px] text-ink-muted">{msg.time}</span>
                  </div>
                  {msg.replyToId && (
                    <button
                      type="button"
                      onClick={() => repliedTo && scrollToMessage(repliedTo.id)}
                      className="flex items-start gap-1.5 mb-1 max-w-full text-left group/quote"
                      title={repliedTo ? 'Jump to original message' : undefined}
                    >
                      <span className="w-[3px] self-stretch rounded-full bg-amber/50 shrink-0" />
                      <span className="text-[12px] text-ink-tertiary truncate py-0.5">
                        <span className="font-semibold text-ink-secondary group-hover/quote:text-amber transition-colors">
                          {repliedTo ? (repliedTo.isAI ? 'Talos AI' : displayName(repliedTo.senderId)) : 'Original message'}
                        </span>
                        {repliedTo && (
                          <span className="ml-1.5">{(repliedTo.body || '').slice(0, 90)}</span>
                        )}
                      </span>
                    </button>
                  )}
                  <RichMessageBody content={msg.content} fallbackText={msg.body || ''} />
                  <AttachmentView channelId={chatroomId} attachments={msg.attachments} />
                  {msg.trace && <RagTracePanel trace={msg.trace} />}
                </div>
                <div className="absolute -top-2.5 right-0 hidden group-hover:flex items-center bg-base border border-[rgba(28,27,26,0.10)] rounded-lg shadow-sm">
                  <Tooltip title="Reply">
                    <IconButton
                      size="small"
                      onClick={() => startReply(msg)}
                      disabled={!msg.serverId}
                      sx={{ width: 28, height: 28, color: 'text.secondary', '&:hover': { color: '#C4913A' } }}
                    >
                      <Reply size={15} />
                    </IconButton>
                  </Tooltip>
                </div>
              </div>
            )
          })}

          {aiThinking && !searchOpen && <AiTypingIndicator />}
        </div>
      </div>

      {/* Input */}
      {canSend ? (
      <div className="border-t border-[rgba(28,27,26,0.06)] bg-surface-1">
        <div className="max-w-[680px] mx-auto px-5 py-4">
          <div className="relative bg-base border border-[rgba(28,27,26,0.10)] rounded-2xl p-3 px-4 flex flex-col gap-0 focus-within:border-amber focus-within:shadow-[0_0_0_3px_rgba(196,145,58,0.12)] transition-all">
            {mentionQuery && mentionCandidates.length > 0 && (
              <MentionPicker
                candidates={mentionCandidates}
                activeIndex={mentionIndex}
                onPick={pickMention}
                onHover={setMentionIndex}
              />
            )}
            {replyTo && (
              <div className="flex items-center gap-2 mb-2 pl-2.5 pr-1.5 py-1.5 bg-surface-2 rounded-lg border-l-[3px] border-amber">
                <Reply size={13} className="text-amber shrink-0" />
                <span className="text-[12px] text-ink-tertiary truncate flex-1">
                  Replying to <span className="font-semibold text-ink-secondary">{replyTo.name}</span>
                  <span className="ml-1.5">{replyTo.snippet}</span>
                </span>
                <IconButton size="small" onClick={() => setReplyTo(null)} sx={{ width: 22, height: 22 }}>
                  <X size={13} />
                </IconButton>
              </div>
            )}
            {(pendingAttachments.length > 0 || uploadingCount > 0) && (
              <div className="flex flex-wrap items-center gap-1.5 mb-2">
                {pendingAttachments.map((a) => (
                  <span
                    key={a.id}
                    className="inline-flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-lg bg-surface-2 border border-[rgba(28,27,26,0.10)] text-[12px] text-ink-secondary max-w-[220px]"
                  >
                    <FileText size={12} className="text-amber shrink-0" />
                    <span className="truncate">{a.filename}</span>
                    <IconButton
                      size="small"
                      onClick={() => setPendingAttachments((prev) => prev.filter((x) => x.id !== a.id))}
                      sx={{ width: 18, height: 18 }}
                    >
                      <X size={11} />
                    </IconButton>
                  </span>
                ))}
                {uploadingCount > 0 && (
                  <span className="text-[12px] text-ink-tertiary px-1.5">
                    Uploading {uploadingCount} file{uploadingCount === 1 ? '' : 's'}…
                  </span>
                )}
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
                  <IconButton
                    size="small"
                    onClick={() => attachInputRef.current?.click()}
                    title="Attach files (documents, images, videos)"
                    sx={{ width: 28, height: 28, color: 'text.disabled', '&:hover': { color: 'text.secondary' } }}
                  >
                    <Paperclip size={15} />
                  </IconButton>
                  <input
                    ref={attachInputRef}
                    type="file"
                    multiple
                    accept="image/png,image/jpeg,image/webp,video/mp4,video/webm,video/quicktime,video/ogg,.pdf,.docx,.txt,.md"
                    style={{ display: 'none' }}
                    onChange={(e) => {
                      handleAttachFiles(e.target.files)
                      e.target.value = ''
                    }}
                  />
                  <div className="flex-1" />
                  <button
                    onClick={() => setDebugTrace((v) => !v)}
                    className={`flex items-center gap-1 h-7 px-2 rounded-lg text-[12px] font-medium transition-colors ${
                      debugTrace ? 'text-amber bg-amber-subtle' : 'text-ink-muted hover:text-ink-secondary'
                    }`}
                    title="Debug mode: show the full RAG trace with the answer"
                  >
                    <Bug size={13} />
                  </button>
                  <button
                    onClick={handleAskAI}
                    disabled={!input.trim() || !chatroomId || sending}
                    className="flex items-center gap-1.5 h-7 px-2.5 rounded-lg text-[12px] font-medium text-amber hover:bg-amber-subtle transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    title="Ask the AI in this channel (everyone can see the reply)"
                  >
                    <Sparkles size={13} /> Ask AI{debugTrace ? ' (debug)' : ''}
                  </button>
                </div>
                <ChatComposerField
                  inputRef={textareaRef}
                  value={input}
                  onChange={handleInputChange}
                  onKeyDown={handleKeyDown}
                  placeholder={chatroomName ? (activeDm ? `Message ${chatroomName}` : `Message #${chatroomName}`) : 'Message…'}
                />
              </div>
              <button
                onClick={handleSend}
                className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 transition-all ${
                  (input.trim() || pendingAttachments.length) && chatroomId
                    ? 'bg-amber text-white shadow-sm hover:bg-amber-hover hover:shadow-md'
                    : 'bg-surface-3 text-ink-muted cursor-default'
                }`}
                disabled={(!input.trim() && !pendingAttachments.length) || !chatroomId || sending || uploadingCount > 0}
              >
                <ArrowUp size={16} strokeWidth={2.5} />
              </button>
            </div>
          </div>
        </div>
      </div>
      ) : chatroomId && channelPermsLoaded ? (
      <div className="border-t border-[rgba(28,27,26,0.06)] bg-surface-1">
        <p className="text-center text-xs text-ink-tertiary py-3">
          You don't have permission to send messages in this channel.
        </p>
      </div>
      ) : null}

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
