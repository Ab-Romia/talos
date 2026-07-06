import { useEffect, useRef, useState } from 'react'
import { useSelector } from 'react-redux'
import { Sparkles, Send, SquarePen } from 'lucide-react'
import { ChatMessageContent } from '../../components/chat/ChatMessageContent'
import { streamAiQuery, getAiHistory, clearAiHistory } from '../../services/ai'
import SidebarToggle from '../../components/layout/SidebarToggle'

const SUGGESTIONS = [
  'Summarize the key points across my documents.',
  'What decisions or deadlines were mentioned recently?',
  'Who is responsible for what in this workspace?',
]

let _uid = 0
const nextId = () => `m${++_uid}`

export default function AIChatPage() {
  const workspaceId = useSelector((s) => s.workspace.activeWorkspaceId)
  const workspaces = useSelector((s) => s.workspace.workspaces)
  const activeWorkspace = workspaces.find((w) => w.id === workspaceId)

  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)

  const scrollRef = useRef(null)
  const abortRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  useEffect(() => () => abortRef.current?.abort(), [])

  // Load the saved per-user conversation for this workspace.
  useEffect(() => {
    abortRef.current?.abort()
    setStreaming(false)
    setMessages([])
    setInput('')
    if (!workspaceId) return
    let cancelled = false
    setHistoryLoading(true)
    ;(async () => {
      try {
        const saved = await getAiHistory(workspaceId)
        if (cancelled || !Array.isArray(saved)) return
        setMessages(saved.map((m) => ({ id: m.id || nextId(), role: m.role, content: m.content })))
      } catch {
        // no saved history (or transient error) — start empty
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
        { question, history },
        (chunk) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === aiMsg.id ? { ...m, content: m.content + chunk } : m)),
          )
        },
        abortRef.current.signal,
      )
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

  const newChat = () => {
    abortRef.current?.abort()
    setStreaming(false)
    setMessages([])
    setInput('')
    if (workspaceId) clearAiHistory(workspaceId).catch(() => {})
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
        {messages.length > 0 && (
          <button
            onClick={newChat}
            className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-[13px] font-medium text-ink-secondary hover:bg-surface-3 transition-colors"
          >
            <SquarePen size={14} /> New chat
          </button>
        )}
      </div>

      {/* Thread */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0">
        <div className="max-w-[1000px] mx-auto px-4 sm:px-5 py-6">
          {messages.length === 0 ? (
            historyLoading ? null : <EmptyState onPick={send} disabled={!workspaceId} />
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
          <div className="flex items-end gap-2 bg-base border border-[rgba(28,27,26,0.12)] rounded-xl px-3 py-2 focus-within:border-amber/50 transition-colors">
            <textarea
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={!workspaceId}
              placeholder="Ask anything about this workspace…"
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
          <div className="text-[11px] text-ink-muted mt-1.5 text-center">
            Answers are grounded in this workspace's documents and chat history.
          </div>
        </div>
      </div>
    </div>
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
