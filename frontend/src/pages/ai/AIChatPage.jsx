import { useEffect, useRef, useState } from 'react'
import { useSelector } from 'react-redux'
import Drawer from '@mui/material/Drawer'
import CircularProgress from '@mui/material/CircularProgress'
import { Sparkles, Send, SquarePen, History, Trash2, X, Paperclip, FileText, Lock } from 'lucide-react'
import { ChatMessageContent } from '../../components/chat/ChatMessageContent'
import {
  streamAiQuery,
  getAiConversations,
  getAiConversationMessages,
  deleteAiConversation,
} from '../../services/ai'
import { documentService } from '../../services/documents'
import { dedupeSources } from '../../utils/sources'
import SidebarToggle from '../../components/layout/SidebarToggle'

const SUGGESTIONS = [
  'Summarize the key points across my documents.',
  'What decisions or deadlines were mentioned recently?',
  'Who is responsible for what in this workspace?',
]

let _uid = 0
const nextId = () => `m${++_uid}`
const newConversationId = () => crypto.randomUUID()

function formatWhen(iso) {
  if (!iso) return ''
  const then = new Date(iso)
  const diff = Date.now() - then.getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'Just now'
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day}d ago`
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export default function AIChatPage() {
  const workspaceId = useSelector((s) => s.workspace.activeWorkspaceId)
  const workspaces = useSelector((s) => s.workspace.workspaces)
  const activeWorkspace = workspaces.find((w) => w.id === workspaceId)

  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  // Starts true so the first paint shows a loader instead of flashing the
  // empty-state prompt before the saved conversation is fetched.
  const [historyLoading, setHistoryLoading] = useState(true)
  const [conversationId, setConversationId] = useState(null)
  const [conversations, setConversations] = useState([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [privateFiles, setPrivateFiles] = useState([]) // user's private AI-tab uploads
  const [uploading, setUploading] = useState(0)

  const scrollRef = useRef(null)
  const abortRef = useRef(null)
  const fileInputRef = useRef(null)
  const pollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  useEffect(() => () => abortRef.current?.abort(), [])
  useEffect(() => () => clearTimeout(pollRef.current), [])

  const loadPrivateFiles = async (wsId = workspaceId) => {
    if (!wsId) return []
    try {
      const list = await documentService.listPrivate(wsId)
      const arr = Array.isArray(list) ? list : []
      setPrivateFiles(arr)
      // Keep polling while anything is still processing, so the chip flips to ready.
      if (arr.some((f) => f.status !== 'indexed' && f.status !== 'processing_failed')) {
        clearTimeout(pollRef.current)
        pollRef.current = setTimeout(() => loadPrivateFiles(wsId), 2500)
      }
      return arr
    } catch {
      return []
    }
  }

  useEffect(() => { setPrivateFiles([]); loadPrivateFiles(workspaceId) }, [workspaceId])

  const uploadPrivateFiles = async (fileList) => {
    const files = Array.from(fileList || [])
    if (!files.length || !workspaceId) return
    setUploading((n) => n + files.length)
    for (const file of files) {
      try {
        const meta = await documentService.uploadPrivate(workspaceId, file)
        setPrivateFiles((prev) => [meta, ...prev.filter((f) => f.id !== meta.id)])
      } catch {
        /* ignore individual failures */
      } finally {
        setUploading((n) => n - 1)
      }
    }
    loadPrivateFiles(workspaceId)
  }

  const deletePrivateFile = async (fileId) => {
    setPrivateFiles((prev) => prev.filter((f) => f.id !== fileId))
    try { await documentService.deletePrivate(workspaceId, fileId) } catch { loadPrivateFiles(workspaceId) }
  }

  const onComposerPaste = (e) => {
    const items = Array.from(e.clipboardData?.items || [])
    const files = items.filter((it) => it.kind === 'file').map((it) => it.getAsFile()).filter(Boolean)
    if (files.length) { e.preventDefault(); uploadPrivateFiles(files) }
  }

  const refreshConversations = async () => {
    if (!workspaceId) return []
    try {
      const list = await getAiConversations(workspaceId)
      const arr = Array.isArray(list) ? list : []
      setConversations(arr)
      return arr
    } catch {
      return []
    }
  }

  // On workspace change, resume the most recent saved conversation (or start
  // fresh when there are none). Past chats stay available via the history panel.
  useEffect(() => {
    abortRef.current?.abort()
    setStreaming(false)
    setMessages([])
    setInput('')
    setConversations([])
    setConversationId(null)
    setHistoryOpen(false)
    if (!workspaceId) { setHistoryLoading(false); return }
    let cancelled = false
    setHistoryLoading(true)
    ;(async () => {
      try {
        const list = await getAiConversations(workspaceId)
        if (cancelled) return
        const arr = Array.isArray(list) ? list : []
        setConversations(arr)
        if (arr.length) {
          const latest = arr[0]
          const msgs = await getAiConversationMessages(workspaceId, latest.id)
          if (cancelled) return
          setConversationId(latest.id)
          setMessages(
            (Array.isArray(msgs) ? msgs : []).map((m) => ({
              id: m.id || nextId(),
              role: m.role,
              content: m.content,
            })),
          )
        } else {
          setConversationId(newConversationId())
        }
      } catch {
        if (!cancelled) setConversationId(newConversationId())
      } finally {
        if (!cancelled) setHistoryLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [workspaceId])

  const send = async (text) => {
    const question = text.trim()
    if (!question || streaming || !workspaceId) return

    const convId = conversationId || newConversationId()
    if (convId !== conversationId) setConversationId(convId)

    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    const userMsg = { id: nextId(), role: 'user', content: question }
    const aiMsg = { id: nextId(), role: 'assistant', content: '' }
    setMessages((prev) => [...prev, userMsg, aiMsg])
    setInput('')
    setStreaming(true)

    abortRef.current = new AbortController()
    try {
      await streamAiQuery(
        workspaceId,
        { question, history, conversationId: convId },
        (chunk) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === aiMsg.id ? { ...m, content: m.content + chunk } : m)),
          )
        },
        abortRef.current.signal,
      )
      // Collapse any duplicate Sources block the model may have emitted.
      setMessages((prev) =>
        prev.map((m) => (m.id === aiMsg.id ? { ...m, content: dedupeSources(m.content) } : m)),
      )
      refreshConversations()
    } catch (e) {
      if (e.name !== 'AbortError') {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiMsg.id
              ? { ...m, content: `${m.content}\n\n_Sorry — something went wrong. Please try again._` }
              : m,
          ),
        )
      }
    } finally {
      setStreaming(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  // Start a brand-new conversation. The current one stays saved and reachable
  // from the history panel — nothing is deleted.
  const newChat = () => {
    abortRef.current?.abort()
    setStreaming(false)
    setMessages([])
    setInput('')
    setConversationId(newConversationId())
    setHistoryOpen(false)
  }

  const openConversation = async (cid) => {
    if (!workspaceId || cid === conversationId) {
      setHistoryOpen(false)
      return
    }
    abortRef.current?.abort()
    setStreaming(false)
    setHistoryOpen(false)
    setHistoryLoading(true)
    setMessages([])
    setConversationId(cid)
    try {
      const msgs = await getAiConversationMessages(workspaceId, cid)
      setMessages(
        (Array.isArray(msgs) ? msgs : []).map((m) => ({
          id: m.id || nextId(),
          role: m.role,
          content: m.content,
        })),
      )
    } catch {
      // transient error — leave the thread empty
    } finally {
      setHistoryLoading(false)
    }
  }

  const removeConversation = async (cid) => {
    if (!workspaceId) return
    try {
      await deleteAiConversation(workspaceId, cid)
    } catch {
      return
    }
    const remaining = await refreshConversations()
    if (cid === conversationId) {
      if (remaining.length) {
        openConversation(remaining[0].id)
      } else {
        newChat()
      }
    }
  }

  const lastId = messages.length ? messages[messages.length - 1].id : null

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-surface-1">
      {/* Header */}
      <div className="h-14 shrink-0 flex items-center justify-between px-3 sm:px-5 border-b border-[rgba(28,27,26,0.08)]">
        <div className="flex items-center gap-2 min-w-0">
          <SidebarToggle />
          <div className="w-7 h-7 rounded-lg bg-amber flex items-center justify-center text-white shrink-0">
            <Sparkles size={15} />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-ink leading-tight">Talos AI</div>
            <div className="text-[11px] text-ink-tertiary truncate">
              {activeWorkspace ? `Grounded in ${activeWorkspace.name}` : 'Ask about your workspace'}
            </div>
          </div>
        </div>
        {workspaceId && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setHistoryOpen(true)}
              className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-[13px] font-medium text-ink-secondary hover:bg-surface-3 transition-colors"
              title="Chat history"
            >
              <History size={14} />
              <span className="hidden sm:inline">History</span>
              {conversations.length > 0 && (
                <span className="text-[11px] text-ink-tertiary">({conversations.length})</span>
              )}
            </button>
            {messages.length > 0 && (
              <button
                onClick={newChat}
                className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-[13px] font-medium text-ink-secondary hover:bg-surface-3 transition-colors"
                title="Start a new chat"
              >
                <SquarePen size={14} /> <span className="hidden sm:inline">New chat</span>
              </button>
            )}
          </div>
        )}
      </div>

      {/* Thread */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0">
        <div className="max-w-[1000px] mx-auto px-4 sm:px-5 py-6">
          {messages.length === 0 ? (
            historyLoading ? (
              <div className="flex justify-center py-20">
                <CircularProgress size={22} sx={{ color: '#C4913A' }} />
              </div>
            ) : <EmptyState onPick={send} disabled={!workspaceId} />
          ) : (
            <div className="flex flex-col gap-5">
              {messages.map((m) =>
                m.role === 'user' ? (
                  <div key={m.id} className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-amber-subtle text-ink px-3.5 py-2 text-[14px] leading-relaxed whitespace-pre-wrap">
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <div key={m.id} className="flex gap-3">
                    <div className="w-7 h-7 rounded-lg bg-amber/15 text-amber flex items-center justify-center shrink-0 mt-0.5">
                      <Sparkles size={14} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <ChatMessageContent
                        content={m.content}
                        renderCursor={streaming && m.id === lastId}
                      />
                    </div>
                  </div>
                ),
              )}
            </div>
          )}
        </div>
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t border-[rgba(28,27,26,0.08)] px-4 sm:px-5 py-3">
        <div className="max-w-[1000px] mx-auto">
          {!workspaceId && (
            <div className="text-[12px] text-ink-tertiary mb-2">
              Select or create a workspace to start chatting with the assistant.
            </div>
          )}

          {/* Private files: only you can ask the assistant about these. */}
          {(privateFiles.length > 0 || uploading > 0) && (
            <div className="flex flex-wrap items-center gap-1.5 mb-2">
              {privateFiles.map((f) => {
                const ready = f.status === 'indexed'
                const failed = f.status === 'processing_failed'
                return (
                  <span
                    key={f.id}
                    className={`inline-flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-lg border text-[12px] max-w-[220px] ${
                      failed ? 'border-red-300 bg-red-50 text-red-700'
                        : 'border-[rgba(28,27,26,0.12)] bg-surface-1 text-ink-secondary'
                    }`}
                    title={failed ? 'Could not read this file' : ready ? 'Ready — ask me about it' : 'Processing…'}
                  >
                    {ready ? <FileText size={13} className="text-amber shrink-0" />
                      : failed ? <X size={13} className="shrink-0" />
                      : <CircularProgress size={11} sx={{ color: '#C4913A' }} />}
                    <span className="truncate">{f.original_filename}</span>
                    <button
                      onClick={() => deletePrivateFile(f.id)}
                      className="w-4 h-4 rounded flex items-center justify-center text-ink-muted hover:text-ink hover:bg-[rgba(28,27,26,0.06)] shrink-0"
                      aria-label={`Remove ${f.original_filename}`}
                    >
                      <X size={12} />
                    </button>
                  </span>
                )
              })}
              {uploading > 0 && (
                <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg border border-[rgba(28,27,26,0.12)] bg-surface-1 text-[12px] text-ink-muted">
                  <CircularProgress size={11} sx={{ color: '#C4913A' }} /> Uploading…
                </span>
              )}
            </div>
          )}

          <div
            className="flex items-end gap-2 bg-base border border-[rgba(28,27,26,0.12)] rounded-xl px-3 py-2 focus-within:border-amber/50 transition-colors"
            onDragOver={(e) => { e.preventDefault() }}
            onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files?.length) uploadPrivateFiles(e.dataTransfer.files) }}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,.pdf,.docx,.pptx,.txt,.md"
              style={{ display: 'none' }}
              onChange={(e) => { uploadPrivateFiles(e.target.files); e.target.value = '' }}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={!workspaceId}
              title="Upload a private file (only you can ask about it)"
              className="w-8 h-8 rounded-lg text-ink-muted hover:text-ink hover:bg-[rgba(28,27,26,0.05)] flex items-center justify-center shrink-0 disabled:opacity-40"
              aria-label="Attach private file"
            >
              <Paperclip size={16} />
            </button>
            <textarea
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              onPaste={onComposerPaste}
              disabled={!workspaceId}
              placeholder="Ask anything, or attach a file to ask about it…"
              className="flex-1 resize-none bg-transparent border-none outline-none text-[14px] text-ink placeholder:text-ink-muted max-h-40 py-1 leading-relaxed disabled:opacity-60"
            />
            <button
              onClick={() => send(input)}
              disabled={!input.trim() || streaming || !workspaceId}
              className="w-8 h-8 rounded-lg bg-amber text-white flex items-center justify-center shrink-0 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-amber-600 transition-colors"
              aria-label="Send"
            >
              <Send size={15} />
            </button>
          </div>
          <div className="text-[11px] text-ink-muted mt-1.5 text-center flex items-center justify-center gap-1">
            <Lock size={10} /> Files you upload here are private to you. Answers use this workspace's documents and chat history.
          </div>
        </div>
      </div>

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        conversations={conversations}
        activeId={conversationId}
        onSelect={openConversation}
        onDelete={removeConversation}
        onNewChat={newChat}
      />
    </div>
  )
}

function HistoryDrawer({ open, onClose, conversations, activeId, onSelect, onDelete, onNewChat }) {
  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <div className="w-[320px] max-w-[85vw] h-full flex flex-col bg-surface-1">
        <div className="h-14 shrink-0 flex items-center justify-between px-4 border-b border-[rgba(28,27,26,0.08)]">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            <History size={16} className="text-amber" /> Chat history
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg text-ink-tertiary hover:bg-surface-3 flex items-center justify-center transition-colors"
            aria-label="Close history"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-3 shrink-0">
          <button
            onClick={onNewChat}
            className="w-full flex items-center justify-center gap-2 h-9 rounded-lg bg-amber text-white text-[13px] font-medium hover:bg-amber-600 transition-colors"
          >
            <SquarePen size={14} /> New chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0 px-2 pb-3">
          {conversations.length === 0 ? (
            <div className="text-[13px] text-ink-tertiary text-center px-4 pt-8">
              No saved chats yet. Ask something to start one.
            </div>
          ) : (
            <div className="flex flex-col gap-0.5">
              {conversations.map((c) => (
                <div
                  key={c.id}
                  className={`group flex items-center gap-2 rounded-lg px-2.5 py-2 cursor-pointer transition-colors ${
                    c.id === activeId ? 'bg-amber-subtle' : 'hover:bg-surface-3'
                  }`}
                  onClick={() => onSelect(c.id)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium text-ink truncate">{c.title}</div>
                    <div className="text-[11px] text-ink-tertiary">
                      {formatWhen(c.updated_at)} · {c.message_count} message
                      {c.message_count === 1 ? '' : 's'}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(c.id)
                    }}
                    className="w-7 h-7 rounded-md text-ink-tertiary hover:text-red-600 hover:bg-red-50 flex items-center justify-center shrink-0 sm:opacity-0 sm:group-hover:opacity-100 transition"
                    title="Delete conversation"
                    aria-label="Delete conversation"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Drawer>
  )
}

function EmptyState({ onPick, disabled }) {
  return (
    <div className="flex flex-col items-center text-center pt-10">
      <div className="w-12 h-12 rounded-2xl bg-amber flex items-center justify-center text-white mb-4 shadow-sm">
        <Sparkles size={22} />
      </div>
      <h2 className="text-lg font-semibold text-ink mb-1">Ask your workspace anything</h2>
      <p className="text-[13px] text-ink-tertiary max-w-[420px] mb-6">
        The assistant retrieves from your documents and conversations to answer with citations.
      </p>
      <div className="flex flex-col gap-2 w-full max-w-[440px]">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            disabled={disabled}
            className="text-left text-[13px] text-ink-secondary bg-surface-2 hover:bg-surface-3 border border-[rgba(28,27,26,0.08)] rounded-lg px-3.5 py-2.5 transition-colors disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}
