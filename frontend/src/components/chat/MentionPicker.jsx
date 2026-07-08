import { useEffect, useRef } from 'react'
import Avatar from '@mui/material/Avatar'
import { Sparkles } from 'lucide-react'

function initialsOf(name) {
  return (name || 'M').split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()
}

/**
 * Slack-style @-mention autocomplete. Rendered above the composer while the
 * user is typing an @token. Fully keyboard-driven from the parent (which owns
 * the active index so the textarea keeps focus).
 */
export function MentionPicker({ candidates, activeIndex, onPick, onHover }) {
  const listRef = useRef(null)

  useEffect(() => {
    const el = listRef.current?.children?.[activeIndex]
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  if (!candidates.length) return null

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 z-50 bg-base border border-[rgba(28,27,26,0.12)] rounded-xl shadow-lg overflow-hidden">
      <div className="px-3 pt-2 pb-1 text-[11px] font-medium text-ink-tertiary uppercase tracking-wider">
        Mention
      </div>
      <ul ref={listRef} className="max-h-[220px] overflow-y-auto pb-1">
        {candidates.map((c, i) => (
          <li key={c.user_id}>
            <button
              type="button"
              onMouseDown={(e) => { e.preventDefault(); onPick(c) }}
              onMouseEnter={() => onHover?.(i)}
              className={`w-full flex items-center gap-2.5 px-3 py-1.5 text-left transition-colors ${
                i === activeIndex ? 'bg-amber-subtle' : 'hover:bg-surface-2'
              }`}
            >
              {c.isBot ? (
                <span className="w-6 h-6 rounded-lg bg-amber/15 text-amber flex items-center justify-center shrink-0">
                  <Sparkles size={13} />
                </span>
              ) : (
                <Avatar sx={{ width: 24, height: 24, fontSize: 10, fontWeight: 600, bgcolor: '#EEEDEA', color: 'text.secondary' }}>
                  {initialsOf(c.label)}
                </Avatar>
              )}
              <span className="text-[13.5px] text-ink font-medium truncate">{c.label}</span>
              {c.isBot && <span className="text-[11px] text-amber ml-auto shrink-0">AI assistant</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
