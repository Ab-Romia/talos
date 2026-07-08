import { useSelector } from 'react-redux'
import { ChatMessageContent } from './ChatMessageContent'
import { docText } from '../../utils/prosemirrorText'

function hasMentions(node) {
  if (!node || typeof node !== 'object') return false
  if (node.type === 'mention') return true
  return (node.content || []).some(hasMentions)
}

function MentionChip({ attrs, selfId }) {
  const isMe = selfId && String(attrs.user_id) === String(selfId)
  return (
    <span
      className={`inline-flex items-center rounded-md px-1 py-0 text-[13.5px] font-medium align-baseline ${
        isMe
          ? 'bg-amber text-white'
          : 'bg-amber-subtle text-amber-700 border border-amber/20'
      }`}
    >
      @{attrs.label}
    </span>
  )
}

function InlineRun({ nodes, selfId }) {
  return nodes.map((n, i) => {
    if (n.type === 'mention') return <MentionChip key={i} attrs={n.attrs || {}} selfId={selfId} />
    if (n.type === 'reference') return <span key={i} className="text-amber underline decoration-amber/40">{n.attrs?.label || 'reference'}</span>
    if (n.type === 'hard_break') return <br key={i} />
    return <span key={i}>{n.text || docText(n)}</span>
  })
}

/**
 * Structural renderer for rich message docs. Messages without mentions keep
 * the full markdown pipeline (ChatMessageContent); messages WITH mentions are
 * rendered paragraph-by-paragraph so mention nodes become highlighted chips.
 */
export function RichMessageBody({ content, fallbackText, renderCursor = false }) {
  const selfId = useSelector((s) => s.auth.user?.id)

  if (!content || typeof content !== 'object' || !hasMentions(content)) {
    return <ChatMessageContent content={fallbackText ?? (content ? docText(content) : '')} renderCursor={renderCursor} />
  }

  const blocks = content.content || []
  return (
    <div className="text-[14px] leading-relaxed text-ink-secondary whitespace-pre-wrap break-words">
      {blocks.map((b, i) => (
        <p key={i} className="my-0.5 min-h-[1.2em]">
          {b.content ? <InlineRun nodes={b.content} selfId={selfId} /> : null}
        </p>
      ))}
    </div>
  )
}
