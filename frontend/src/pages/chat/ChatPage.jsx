import { useState, useRef, useEffect, useCallback, useMemo, Fragment } from 'react'
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
  Search, Users, Bold, Code, ArrowUp, X, Sparkles, Reply, Paperclip, FileText, FolderOpen,
  MessageSquare, Hash,
} from 'lucide-react'

import { useSearchParams } from 'react-router-dom'
import { useSelector, useDispatch as useReduxDispatch } from 'react-redux'
import { usePermissions } from '../../contexts/PermissionsContext'
import { markChannelRead, setActiveChatroom, switchWorkspace } from '../../store/workspaceSlice'
import { chatService } from '../../services/chat'
import { getBotIdentity } from '../../services/ai'
import { onChatMessage, onAiTyping, onAiStream, getSocket } from '../../services/socket'
import { RagTracePanel } from '../../components/chat/RagTracePanel'
import { askService } from '../../services/ask'
import { AiTypingIndicator } from '../../components/chat/AiTypingIndicator'
import { ChatComposerField } from '../../components/chat/ChatComposerField'
import SidebarToggle from '../../components/layout/SidebarToggle'
import SharedFilesPanel from '../../components/chat/SharedFilesPanel'
import { MentionPicker } from '../../components/chat/MentionPicker'
import { RichMessageBody } from '../../components/chat/RichMessageBody'
import { AttachmentView } from '../../components/chat/AttachmentView'
import { docText } from '../../utils/prosemirrorText'
import { buildMessageDoc, activeMentions } from '../../utils/mentionDoc'
import { getDevMode, onDevModeChange } from '../../utils/devMode'

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

// Friendly day label for the in-thread date separators.
function dayLabelOf(dayKey) {
  if (!dayKey) return ''
  const d = new Date(dayKey)
  if (Number.isNaN(d.getTime())) return ''
  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  const sameYear = d.getFullYear() === today.getFullYear()
  return d.toLocaleDateString([], {
    weekday: 'short', month: 'short', day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  })
}

// Stable, pleasant colour for a sender's name in group chats (WhatsApp style).
const NAME_COLORS = ['#B4703A', '#3C7A6A', '#8A5A9E', '#4A6FA5', '#A85454', '#5C7A3A', '#9E6A3A', '#4E7E8A']
function nameColor(id) {
  const s = String(id || '')
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return NAME_COLORS[h % NAME_COLORS.length]
}

const GROUP_GAP_MS = 5 * 60 * 1000


export default function ChatPage() {
  const reduxDispatch = useReduxDispatch()
  const [searchParams, setSearchParams] = useSearchParams()
  const pendingMsgId = searchParams.get('msg')
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  // True while a conversation's initial history is loading, so the "welcome"
  // empty state isn't shown for a frame before existing messages arrive.
  const [messagesLoading, setMessagesLoading] = useState(true)
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
  const [debugTrace, setDebugTrace] = useState(getDevMode)
  const [bot, setBot] = useState(null)
  const [mentionQuery, setMentionQuery] = useState(null) // { start, query } while typing @…
  const [mentionIndex, setMentionIndex] = useState(0)
  const [replyTo, setReplyTo] = useState(null) // { serverId, uiId, name, snippet }
  const [pendingAttachments, setPendingAttachments] = useState([]) // uploaded, not yet sent
  const [uploadingCount, setUploadingCount] = useState(0)
  const [sharedFilesOpen, setSharedFilesOpen] = useState(false)
  const trackedMentionsRef = useRef([]) // [{ label, user_id }] inserted via the picker
  const attachInputRef = useRef(null)

  const user = useSelector((state) => state.auth.user)
  const {
    workspaces,
    chatrooms,
    dms,
    activeWorkspaceId: workspaceId,
    activeChatroomId: chatroomId,
    membersVersion,
  } = useSelector((s) => s.workspace)

  const activeDm = useMemo(
    () => dms.find((d) => d.id === chatroomId) || null,
    [dms, chatroomId],
  )
  // Channels render Slack-style (grouped rows). DMs and group chats render
  // WhatsApp-style bubbles — own messages right, everyone else left.
  const bubbleMode = Boolean(activeDm)
  const isGroupChat = Boolean(activeDm?.is_group)

  // Keep the in-chat trace display in sync with the Settings "Developer mode".
  useEffect(() => onDevModeChange(setDebugTrace), [])

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
  // Latest workspace, so a slow member fetch can't overwrite the new
  // workspace's roster after a quick switch.
  const wsRef = useRef(workspaceId)
  wsRef.current = workspaceId
  const aiThinkingTimer = useRef(null)
  const firstSearchHitRef = useRef(null)
  const lastScrolledFirstMatchId = useRef(null)

  const membersMap = useMemo(() => {
    const map = new Map()
    for (const m of members) map.set(String(m.id), m)
    membersMapRef.current = map
    return map
  }, [members])

  const displayName = useCallback(
    (senderId) => {
      if (senderId && senderId === user?.id) return user?.name || user?.username || 'You'
      const m = membersMap.get(String(senderId))
      return (m && (m.name || m.username)) || 'Member'
    },
    [user, membersMap],
  )

  const avatarUrl = useCallback(
    (senderId) => {
      if (senderId && senderId === user?.id) return user?.avatar_url || undefined
      return membersMap.get(String(senderId))?.avatar_url || undefined
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
        avatarUrl: isAI ? undefined : avatarUrl(m.sender_id),
        time: fmtTime(m.sent_at),
        sentAt: m.sent_at || null,
        body: docText(m.content),
        content: m.content,
        replyToId: m.reply_to_id || null,
        attachments: m.attachments || [],
      }
    },
    [displayName, avatarUrl, user],
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

  const [searchResults, setSearchResults] = useState([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchTotal, setSearchTotal] = useState(0)
  const searchAbort = useRef(null)

  useEffect(() => {
    if (!searchOpen || !searchQuery.trim() || !chatroomId) {
      setSearchResults([])
      setSearchTotal(0)
      return
    }
    const timer = setTimeout(async () => {
      if (searchAbort.current) searchAbort.current.abort = true
      const token = { abort: false }
      searchAbort.current = token
      setSearchLoading(true)
      try {
        const res = await chatService.searchMessages(chatroomId, {
          text: searchQuery.trim(),
          pageSize: 30,
        })
        if (token.abort) return
        const msgs = (res.messages || []).map((m) => ({
          id: m.id,
          serverId: m.id,
          senderId: m.sender_id,
          mine: m.sender_id === user?.id,
          name: displayName(m.sender_id),
          initials: initialsOf(displayName(m.sender_id)),
          avatarUrl: avatarUrl(m.sender_id),
          time: fmtTime(m.sent_at),
          body: docText(m.content),
        }))
        setSearchResults(msgs)
        setSearchTotal(res.total || msgs.length)
      } catch {
        if (!token.abort) setSearchResults([])
      } finally {
        if (!token.abort) setSearchLoading(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery, searchOpen, chatroomId, user, displayName])

  const highlightedMessageId = useRef(null)

  const scrollToMessage = useCallback((msgId, attempt = 0) => {
    highlightedMessageId.current = msgId
    const el = document.querySelector(`[data-msg-id="${msgId}"]`)
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      el.classList.add('search-highlight')
      setTimeout(() => el.classList.remove('search-highlight'), 2000)
    } else if (attempt < 12) {
      // The target may not be mounted yet (just fetched / still rendering) —
      // retry briefly so the jump lands once it paints.
      setTimeout(() => scrollToMessage(msgId, attempt + 1), 100)
    }
  }, [])

  // Jump to a message by its SERVER id (data-msg-id). Used by search results and
  // reply previews. If it isn't in the loaded window, fetch and insert it first.
  const jumpToMessage = useCallback(async (serverId) => {
    if (!serverId) return
    if (!document.querySelector(`[data-msg-id="${serverId}"]`)) {
      try {
        const m = await chatService.getMessage(chatroomId, serverId)
        if (m) {
          const uiMsg = toUiMessage(m)
          setMessages((prev) => (prev.some((x) => x.serverId === serverId) ? prev : [uiMsg, ...prev]))
        }
      } catch { /* message may have been deleted */ }
    }
    scrollToMessage(serverId)
  }, [chatroomId, toUiMessage, scrollToMessage])

  useEffect(() => {
    const cr = chatrooms.find((c) => c.id === chatroomId)
    if (cr) {
      setChatroomName(cr.name || '')
      return
    }
    const dm = dms.find((d) => d.id === chatroomId)
    if (dm) {
      setChatroomName(dm.is_group ? (dm.name || 'Group') : (dm.peer?.name || 'Direct message'))
    } else {
      setChatroomName('')
    }
  }, [chatrooms, dms, chatroomId])

  // Clear messages when switching channels.
  useEffect(() => {
    setMessages([])
    setMessagesLoading(Boolean(chatroomId))
  }, [chatroomId])

  // Opening a conversation clears its unread badge and marks its notifications
  // read on the server, so the count doesn't reappear on the next reload.
  useEffect(() => {
    if (chatroomId) reduxDispatch(markChannelRead(chatroomId))
  }, [chatroomId, reduxDispatch])

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
      } finally {
        if (!cancelled) setMessagesLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [chatroomId, toUiMessage])

  // Deep-link from a notification (email "Open in Talos" or in-app click):
  // ?channel=<id>&workspace=<id> — switch to that workspace (if needed) and open
  // the conversation. ?msg is left in place for the message-jump effect below.
  const pendingChannelId = searchParams.get('channel')
  const pendingWorkspaceId = searchParams.get('workspace')
  useEffect(() => {
    if (!pendingChannelId) return
    let cancelled = false
    ;(async () => {
      if (pendingWorkspaceId && pendingWorkspaceId !== workspaceId) {
        await reduxDispatch(switchWorkspace(pendingWorkspaceId))
      }
      if (cancelled) return
      reduxDispatch(setActiveChatroom(pendingChannelId))
      setSearchParams(
        (prev) => { prev.delete('channel'); prev.delete('workspace'); return prev },
        { replace: true },
      )
    })()
    return () => { cancelled = true }
  }, [pendingChannelId, pendingWorkspaceId, workspaceId, reduxDispatch, setSearchParams])

  // Deep-link: if ?msg=UUID is present, scroll to that message (fetch it if not loaded).
  useEffect(() => {
    if (!pendingMsgId || !chatroomId || messages.length === 0) return
    const already = messages.find((m) => m.serverId === pendingMsgId)
    if (already) {
      requestAnimationFrame(() => scrollToMessage(pendingMsgId))
      setSearchParams((prev) => { prev.delete('msg'); return prev }, { replace: true })
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const msg = await chatService.getMessage(chatroomId, pendingMsgId)
        if (cancelled || !msg) return
        const uiMsg = toUiMessage(msg)
        setMessages((prev) => {
          if (prev.some((m) => m.serverId === pendingMsgId)) return prev
          return [uiMsg, ...prev]
        })
        requestAnimationFrame(() => scrollToMessage(pendingMsgId))
      } catch { /* message may not exist */ }
      if (!cancelled) {
        setSearchParams((prev) => { prev.delete('msg'); return prev }, { replace: true })
      }
    })()
    return () => { cancelled = true }
  }, [pendingMsgId, chatroomId, messages, toUiMessage, scrollToMessage, setSearchParams])

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

      // Unread badges, DM-list refresh and OS notifications for messages in
      // other conversations are handled app-wide in useNotificationsSocket.
      // Here we only care about the conversation currently open.
      if (m.channel_id !== chatroomId) return

      // A message arrived in the conversation the user is actively viewing —
      // mark it read on the server so its badge/bell count doesn't linger.
      if (m.sender_id && m.sender_id !== user?.id && document.visibilityState === 'visible') {
        reduxDispatch(markChannelRead(chatroomId))
      }

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

  // Realtime: token-by-token streaming of the in-channel AI reply. A placeholder
  // assistant message is created on `start`, grown on each `delta`, and finalised
  // (real serverId + content) on `end` so it streams in live like a typical assistant.
  useEffect(() => {
    if (!chatroomId) return
    getSocket()
    const off = onAiStream((payload) => {
      if (!payload || payload.channel_id !== chatroomId) return
      const sid = payload.stream_id

      if (payload.status === 'start') {
        setAiThinking(false) // the streaming bubble now carries the feedback
        setMessages((prev) => {
          if (prev.some((m) => m.streamId === sid)) return prev
          return [...prev, {
            id: nextIdRef.current++,
            streamId: sid,
            streaming: true,
            serverId: null,
            senderId: payload.sender_id || null,
            role: 'assistant',
            isAI: true,
            mine: false,
            name: 'Talos AI',
            initials: 'AI',
            time: nowTime(),
            sentAt: new Date().toISOString(),
            body: '',
            content: null,
            attachments: [],
          }]
        })
        return
      }

      if (payload.delta) {
        setMessages((prev) => prev.map((m) =>
          m.streamId === sid ? { ...m, body: (m.body || '') + payload.delta } : m,
        ))
        return
      }

      if (payload.status === 'end') {
        setAiThinking(false)
        setMessages((prev) => {
          const idx = prev.findIndex((m) => m.streamId === sid)
          if (payload.message) {
            const finalMsg = { ...toUiMessage(payload.message), streaming: false }
            if (idx === -1) {
              if (prev.some((m) => m.serverId === payload.message.id)) return prev
              return [...prev, finalMsg]
            }
            const next = [...prev]
            next[idx] = finalMsg
            return next
          }
          // errored / no message — just stop the cursor on whatever streamed.
          if (idx === -1) return prev
          const next = [...prev]
          next[idx] = { ...next[idx], streaming: false }
          return next
        })
      }
    })
    return () => off()
  }, [chatroomId, toUiMessage])

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

  // Paste (Ctrl+V) an image/file directly into the message composer → attach it.
  const handleComposerPaste = useCallback((e) => {
    const files = Array.from(e.clipboardData?.items || [])
      .filter((it) => it.kind === 'file')
      .map((it) => it.getAsFile())
      .filter(Boolean)
    if (files.length) {
      e.preventDefault()
      handleAttachFiles(files)
    }
  }, [handleAttachFiles])

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
    // Instant feedback: if this message addresses the AI, show the thinking
    // indicator right away (before the server's ai_typing/ai_stream signals).
    const triggersAi =
      /(^|\s)[@/]talos/i.test(text) ||
      mentions.some((m) => bot && String(m.user_id) === String(bot.user_id))
    if (triggersAi) setAiThinking(true)
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
  }, [sending, chatroomId, user, showSnackbar, replyTo, pendingAttachments, bot])

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
        avatarUrl: user?.avatar_url || undefined,
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
    const wsId = workspaceId
    if (!wsId) return
    setMembersLoading(true)
    try {
      const list = await chatService.getMembers(wsId)
      if (wsId !== wsRef.current) return
      setMembers(Array.isArray(list) ? list : [])
    } catch (err) {
      if (wsId !== wsRef.current) return
      setMembers([])
      showSnackbar(err?.detail || 'Could not load members')
    } finally {
      if (wsId === wsRef.current) setMembersLoading(false)
    }
    if (chatroomId) {
      try {
        const res = await chatService.getOnline(chatroomId)
        if (wsId !== wsRef.current) return
        setOnlineIds(new Set((res?.online_users || []).map(String)))
      } catch {
        if (wsId !== wsRef.current) return
        setOnlineIds(new Set())
      }
    }
  }, [workspaceId, chatroomId, showSnackbar])

  // Load members eagerly so display names are available for messages.
  // `membersVersion` bumps when another user changes the roster.
  useEffect(() => { loadMembers() }, [loadMembers, membersVersion])

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

  // Walk the thread once, attaching grouping + date-divider metadata so both
  // the Slack (channel) and WhatsApp (DM/group) renderers can share it.
  const decorated = useMemo(() => {
    // Carry forward the last calendar day we actually saw so an optimistic /
    // streaming message with no timestamp can't reset it and print a second
    // "Today" divider.
    let lastDayKey = null
    const rows = messages.map((m, i) => {
      const prev = messages[i - 1] || null
      const tCur = m.sentAt ? new Date(m.sentAt).getTime() : null
      const tPrev = prev?.sentAt ? new Date(prev.sentAt).getTime() : null
      const dayKey = m.sentAt && !Number.isNaN(tCur) ? new Date(m.sentAt).toDateString() : null
      const showDate = m.role !== 'system' && Boolean(dayKey) && dayKey !== lastDayKey
      if (dayKey) lastDayKey = dayKey
      const sameSender =
        prev && prev.role !== 'system' && m.role !== 'system' &&
        prev.senderId === m.senderId && prev.isAI === m.isAI
      const closeInTime = tPrev != null && tCur != null ? tCur - tPrev < GROUP_GAP_MS : true
      const startsGroup = !sameSender || !closeInTime || showDate || Boolean(m.replyToId)
      return { msg: m, showDate, dayKey, startsGroup, endsGroup: true }
    })
    for (let i = 0; i < rows.length; i++) {
      rows[i].endsGroup = i === rows.length - 1 ? true : rows[i + 1].startsGroup
    }
    return rows
  }, [messages])

  const headerIcons = canViewPresence ? [Search, Users] : [Search]
  const toolbarIcons = [Bold, Code]

  return (
    <div className="flex flex-col h-full bg-base">
      <style>{`
        @keyframes talosIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
      `}</style>
      {/* Header */}
      <header className="h-14 bg-surface-1 border-b border-[rgba(28,27,26,0.08)] flex items-center justify-between px-3 sm:px-5 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <SidebarToggle />
          <span className="w-2 h-2 bg-success rounded-full shrink-0" />
          <span className="text-[15px] font-semibold text-ink truncate">
            {chatroomName ? (activeDm ? chatroomName : `# ${chatroomName}`) : 'Select a channel'}
          </span>
          {workspaceName && (
            <span className="text-[12px] text-ink-tertiary shrink-0 hidden sm:inline">· {workspaceName}</span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          {chatroomId && (
            <Tooltip title="Shared files">
              <IconButton
                size="small"
                onClick={() => setSharedFilesOpen(true)}
                sx={{ color: 'text.secondary', '&:hover': { bgcolor: 'rgba(28,27,26,0.04)' } }}
              >
                <FolderOpen size={16} />
              </IconButton>
            </Tooltip>
          )}
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
            placeholder="Search all messages in this channel…"
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
            <span className="text-xs text-ink-tertiary tabular-nums shrink-0 min-w-[4.5rem] text-right">
              {searchLoading ? 'Searching…' : `${searchTotal} ${searchTotal === 1 ? 'match' : 'matches'}`}
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
              {searchLoading ? (
                <div className="flex items-center justify-center py-6 gap-2">
                  <div className="w-4 h-4 border-2 border-amber border-t-transparent rounded-full animate-spin" />
                  <span className="text-sm text-ink-tertiary">Searching…</span>
                </div>
              ) : searchResults.length === 0 ? (
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
                        setSearchOpen(false)
                        setSearchQuery('')
                        jumpToMessage(msg.serverId || msg.id)
                      }}
                    >
                      <Avatar
                        src={msg.avatarUrl}
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
        <div className="w-full px-4 sm:px-6 lg:px-8 py-6">
          {!chatroomId && (
            <div className="flex flex-col items-center justify-center text-center py-24 px-4 gap-3">
              <div className="w-14 h-14 rounded-2xl bg-surface-2 flex items-center justify-center text-ink-tertiary">
                <Users size={24} />
              </div>
              <p className="text-sm font-medium text-ink-secondary">No conversation selected</p>
              <p className="text-[13px] text-ink-tertiary max-w-xs">
                Pick a channel or a direct message from the sidebar to start chatting.
              </p>
            </div>
          )}

          {chatroomId && messagesLoading && messages.length === 0 && (
            <div className="flex justify-center py-24">
              <div className="w-6 h-6 border-2 border-amber border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {chatroomId && !messagesLoading && messages.length === 0 && (
            <div
              className="flex flex-col items-center justify-center text-center py-24 px-4 gap-3"
              style={{ animation: 'talosIn .4s ease-out' }}
            >
              <div className="w-16 h-16 rounded-2xl bg-amber/10 flex items-center justify-center text-amber">
                {bubbleMode ? <MessageSquare size={26} /> : <Hash size={26} />}
              </div>
              <p className="text-[15px] font-semibold text-ink">
                {bubbleMode
                  ? (isGroupChat ? `Welcome to ${chatroomName || 'the group'}` : `Chat with ${chatroomName || 'this person'}`)
                  : `Welcome to #${chatroomName || 'the channel'}`}
              </p>
              <p className="text-[13px] text-ink-tertiary max-w-sm leading-relaxed">
                {bubbleMode
                  ? 'This is the very beginning of your conversation. Say hello 👋'
                  : 'This is the start of the channel. Share updates, ask questions, and keep everyone in the loop.'}
              </p>
            </div>
          )}

          {decorated.map((d) => {
            const msg = d.msg
            const key = msg.id

            if (msg.role === 'system') {
              return (
                <div key={key} data-msg-id={msg.serverId || msg.id} className="flex justify-center my-5">
                  <span className="text-[12px] text-ink-tertiary bg-surface-2 px-3 py-1 rounded-full">{msg.body}</span>
                </div>
              )
            }

            const repliedTo = msg.replyToId ? messages.find((x) => x.serverId === msg.replyToId) : null
            const dateDivider = d.showDate ? (
              <div className="flex items-center gap-4 my-6 first:mt-0">
                <span className="flex-1 h-px bg-[rgba(28,27,26,0.06)]" />
                <span className="text-[11px] font-semibold text-ink-tertiary tracking-wide px-3 py-1 rounded-full bg-surface-2 shadow-sm">
                  {dayLabelOf(d.dayKey)}
                </span>
                <span className="flex-1 h-px bg-[rgba(28,27,26,0.06)]" />
              </div>
            ) : null

            const replyBtn = (
              <div className="self-center opacity-0 group-hover:opacity-100 transition-opacity">
                <Tooltip title="Reply">
                  <IconButton
                    size="small"
                    onClick={() => startReply(msg)}
                    disabled={!msg.serverId}
                    sx={{ width: 26, height: 26, color: 'text.secondary', '&:hover': { color: '#C4913A' } }}
                  >
                    <Reply size={14} />
                  </IconButton>
                </Tooltip>
              </div>
            )

            // ── WhatsApp-style bubbles: DMs + group chats (own → right, others → left) ──
            if (bubbleMode) {
              const mine = msg.mine
              let round = 'rounded-2xl'
              if (mine) {
                if (!d.startsGroup) round += ' rounded-tr-md'
                if (!d.endsGroup) round += ' rounded-br-md'
              } else {
                if (!d.startsGroup) round += ' rounded-tl-md'
                if (!d.endsGroup) round += ' rounded-bl-md'
              }
              // AI replies always identify themselves (name + avatar) even in a
              // 1:1 DM, so it's clear "the other side" is Talos, and get a
              // distinct amber tint.
              const showIdentity = !mine && (isGroupChat || msg.isAI)
              const bubbleTone = mine
                ? 'bg-amber/15 border border-amber/25'
                : msg.isAI
                  ? 'bg-amber/[0.06] border border-amber/20'
                  : 'bg-white border border-[rgba(28,27,26,0.07)]'
              return (
                <Fragment key={key}>
                  {dateDivider}
                  <div
                    data-msg-id={msg.serverId || msg.id}
                    className={`group flex items-end gap-2 ${mine ? 'justify-end' : 'justify-start'} ${d.startsGroup ? 'mt-3' : 'mt-[3px]'}`}
                    style={{ animation: 'talosIn .26s ease-out' }}
                  >
                    {showIdentity && (
                      <div className="w-7 shrink-0 self-end mb-1">
                        {d.endsGroup && (
                          <Avatar
                            src={msg.avatarUrl}
                            sx={{
                              width: 28, height: 28, fontSize: 11, fontWeight: 600,
                              bgcolor: msg.isAI ? 'rgba(196,145,58,0.15)' : '#EEEDEA',
                              color: msg.isAI ? '#C4913A' : 'text.secondary',
                            }}
                          >
                            {msg.isAI ? <Sparkles size={14} /> : msg.initials}
                          </Avatar>
                        )}
                      </div>
                    )}
                    {mine && replyBtn}
                    <div className={`relative max-w-[82%] sm:max-w-[68%] flex flex-col ${mine ? 'items-end' : 'items-start'}`}>
                      {showIdentity && d.startsGroup && (
                        <span className="text-[12px] font-semibold mb-0.5 px-1" style={{ color: msg.isAI ? '#C4913A' : nameColor(msg.senderId) }}>
                          {msg.isAI ? 'Talos AI' : displayName(msg.senderId)}
                        </span>
                      )}
                      <div className={`px-3 py-2 shadow-sm ${bubbleTone} ${round}`}>
                        {msg.replyToId && (
                          <button
                            type="button"
                            onClick={() => jumpToMessage(msg.replyToId)}
                            className="flex items-stretch gap-1.5 mb-1.5 w-full text-left rounded-md bg-[rgba(28,27,26,0.04)] hover:bg-[rgba(28,27,26,0.07)] transition-colors overflow-hidden"
                            title="Jump to original message"
                          >
                            <span className="w-[3px] bg-amber/60 shrink-0" />
                            <span className="min-w-0 py-1 pr-2">
                              <span className="block text-[11px] font-semibold text-amber-700 truncate">
                                {repliedTo ? (repliedTo.isAI ? 'Talos AI' : displayName(repliedTo.senderId)) : 'Original message'}
                              </span>
                              {repliedTo && (
                                <span className="block text-[12px] text-ink-tertiary truncate">{(repliedTo.body || '').slice(0, 80)}</span>
                              )}
                            </span>
                          </button>
                        )}
                        <RichMessageBody content={msg.content} fallbackText={msg.body || ''} renderCursor={Boolean(msg.streaming)} />
                        <AttachmentView channelId={chatroomId} attachments={msg.attachments} />
                        <div className="flex justify-end mt-0.5 -mb-0.5">
                          <span className="text-[10px] tabular-nums text-ink-muted">{msg.time}</span>
                        </div>
                      </div>
                      {msg.trace && <RagTracePanel trace={msg.trace} />}
                    </div>
                    {!mine && replyBtn}
                  </div>
                </Fragment>
              )
            }

            // ── Slack-style grouped rows: channels ──
            return (
              <Fragment key={key}>
                {dateDivider}
                <div
                  data-msg-id={msg.serverId || msg.id}
                  className={`relative flex gap-3 group -mx-2 px-2 rounded-lg hover:bg-[rgba(28,27,26,0.025)] transition-colors ${d.startsGroup ? 'mt-4 pt-1' : 'mt-0.5'} ${d.endsGroup ? 'pb-1' : ''}`}
                  style={d.startsGroup ? { animation: 'talosIn .26s ease-out' } : undefined}
                >
                  <div className="w-[34px] shrink-0 pt-0.5">
                    {d.startsGroup ? (
                      <Avatar
                        src={msg.avatarUrl}
                        sx={{
                          width: 34, height: 34,
                          bgcolor: msg.isAI ? 'rgba(196,145,58,0.15)' : msg.mine ? 'primary.light' : '#EEEDEA',
                          color: msg.isAI ? '#C4913A' : msg.mine ? 'primary.main' : 'text.secondary',
                          fontSize: 13, fontWeight: 600,
                        }}
                      >
                        {msg.isAI ? <Sparkles size={16} /> : msg.initials}
                      </Avatar>
                    ) : (
                      <span className="hidden group-hover:block text-[10px] leading-5 text-ink-muted text-right tabular-nums pr-1">
                        {msg.time}
                      </span>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    {d.startsGroup && (
                      <div className="flex items-baseline gap-2 mb-0.5">
                        <span className="text-[13px] font-semibold text-ink">{msg.isAI ? 'Talos AI' : displayName(msg.senderId)}</span>
                        <span className="text-[11px] text-ink-muted">{msg.time}</span>
                      </div>
                    )}
                    {msg.replyToId && (
                      <button
                        type="button"
                        onClick={() => jumpToMessage(msg.replyToId)}
                        className="flex items-start gap-1.5 mb-1 max-w-full text-left group/quote cursor-pointer"
                        title="Jump to original message"
                      >
                        <span className="w-[3px] self-stretch rounded-full bg-amber/50 shrink-0" />
                        <span className="text-[12px] text-ink-tertiary truncate py-0.5">
                          <span className="font-semibold text-ink-secondary group-hover/quote:text-amber transition-colors">
                            {repliedTo ? (repliedTo.isAI ? 'Talos AI' : displayName(repliedTo.senderId)) : 'Original message'}
                          </span>
                          {repliedTo && <span className="ml-1.5">{(repliedTo.body || '').slice(0, 90)}</span>}
                        </span>
                      </button>
                    )}
                    <RichMessageBody content={msg.content} fallbackText={msg.body || ''} renderCursor={Boolean(msg.streaming)} />
                    <AttachmentView channelId={chatroomId} attachments={msg.attachments} />
                    {msg.trace && <RagTracePanel trace={msg.trace} />}
                  </div>
                  <div className="absolute -top-3 right-2 hidden group-hover:flex items-center bg-base border border-[rgba(28,27,26,0.10)] rounded-lg shadow-sm">
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
              </Fragment>
            )
          })}

          {aiThinking && !searchOpen && <AiTypingIndicator />}
        </div>
      </div>

      {/* Input */}
      {canSend ? (
      <div className="border-t border-[rgba(28,27,26,0.06)] bg-surface-1">
        <div className="w-full px-4 sm:px-6 lg:px-8 py-4">
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
                    accept="image/*,video/*,.pdf,.docx,.pptx,.txt,.md"
                    style={{ display: 'none' }}
                    onChange={(e) => {
                      handleAttachFiles(e.target.files)
                      e.target.value = ''
                    }}
                  />
                  <div className="flex-1" />
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
                  onPaste={handleComposerPaste}
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
                    <Avatar src={m.avatar_url || undefined} sx={{ width: 28, height: 28, fontSize: 12, bgcolor: '#EEEDEA', color: 'text.secondary' }}>
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

      {/* Shared files panel (WhatsApp-style, newest first) */}
      <SharedFilesPanel
        channelId={chatroomId}
        open={sharedFilesOpen}
        onClose={() => setSharedFilesOpen(false)}
      />

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
