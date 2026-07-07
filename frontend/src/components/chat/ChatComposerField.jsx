import { useLayoutEffect, useRef, useCallback } from 'react'

const MAX_PX = 200

const EDITOR_TEXT =
  'font-mono text-[14px] leading-[1.5] [font-kerning:normal] [font-feature-settings:normal]'

function segmentMarkdownOverlay(text) {
  const out = []
  const len = text.length
  let i = 0
  let start = 0

  const flush = (end) => {
    if (start < end) out.push({ kind: 'plain', text: text.slice(start, end) })
    start = end
  }

  while (i < len) {
    if (text.startsWith('```', i)) {
      const close = text.indexOf('```', i + 3)
      if (close === -1) {
        i += 1
        continue
      }
      const endBlock = close + 3
      flush(i)
      out.push({ kind: 'fence', text: text.slice(i, endBlock) })
      i = endBlock
      start = i
      continue
    }

    if (text[i] === '`') {
      const end = text.indexOf('`', i + 1)
      if (end !== -1) {
        flush(i)
        out.push({ kind: 'inlineCode', text: text.slice(i, end + 1) })
        i = end + 1
        start = i
        continue
      }
    }

    if (text.startsWith('**', i)) {
      const end = text.indexOf('**', i + 2)
      if (end !== -1) {
        flush(i)
        out.push({ kind: 'bold', inner: text.slice(i + 2, end) })
        i = end + 2
        start = i
        continue
      }
    }

    if (text.startsWith('~~', i)) {
      const end = text.indexOf('~~', i + 2)
      if (end !== -1) {
        flush(i)
        out.push({ kind: 'strike', inner: text.slice(i + 2, end) })
        i = end + 2
        start = i
        continue
      }
    }

    if (text[i] === '[') {
      const closeBr = text.indexOf(']', i)
      if (closeBr !== -1 && text[closeBr + 1] === '(') {
        const closePr = text.indexOf(')', closeBr + 2)
        if (closePr !== -1) {
          flush(i)
          out.push({
            kind: 'link',
            label: text.slice(i + 1, closeBr),
            href: text.slice(closeBr + 2, closePr),
          })
          i = closePr + 1
          start = i
          continue
        }
      }
    }

    if (text[i] === '*' && text[i + 1] !== '*' && text[i + 1] !== ' ') {
      const end = text.indexOf('*', i + 1)
      if (end !== -1 && (!text[end + 1] || text[end + 1] !== '*')) {
        flush(i)
        out.push({ kind: 'italic', inner: text.slice(i + 1, end) })
        i = end + 1
        start = i
        continue
      }
    }

    i += 1
  }
  flush(len)
  return out
}

function SegmentView({ s }) {
  const dim = 'text-ink/35'

  switch (s.kind) {
    case 'plain':
      return <span className="text-ink/90">{s.text}</span>
    case 'inlineCode': {
      const body = s.text.length >= 2 ? s.text.slice(1, -1) : s.text
      return (
        <span className="align-baseline">
          <span className={dim}>{"`"}</span>
          <span className="bg-surface-2/90 text-ink rounded-sm py-0 align-baseline">
            {body}
          </span>
          <span className={dim}>{"`"}</span>
        </span>
      )
    }
    case 'bold':
      return (
        <span>
          <span className={dim}>**</span>
          <span className="font-semibold text-ink">{s.inner}</span>
          <span className={dim}>**</span>
        </span>
      )
    case 'strike':
      return (
        <span>
          <span className={dim}>~~</span>
          <span className="line-through text-ink/75">{s.inner}</span>
          <span className={dim}>~~</span>
        </span>
      )
    case 'italic':
      return (
        <span>
          <span className={dim}>*</span>
          <span className="italic text-ink">{s.inner}</span>
          <span className={dim}>*</span>
        </span>
      )
    case 'link':
      return (
        <span>
          <span className={dim}>[</span>
          <span className="text-amber/90 font-medium underline decoration-amber/35 underline-offset-2">
            {s.label}
          </span>
          <span className={dim}>]</span>
          <span className={dim}>(</span>
          <span className="text-ink/45 break-all text-[14px]">{s.href}</span>
          <span className={dim}>)</span>
        </span>
      )
    case 'fence': {
      const lines = s.text.split('\n')
      return (
        <span className={`text-ink/85 whitespace-pre-wrap break-words ${EDITOR_TEXT}`}>
          {lines.map((line, idx) => (
            <span key={idx}>
              {idx > 0 && '\n'}
              <span
                className={
                  line.trimStart().startsWith('```')
                    ? 'text-ink/35'
                    : 'text-ink/90 bg-surface-2/45 rounded-sm px-0.5 -mx-0.5'
                }
              >
                {line}
              </span>
            </span>
          ))}
        </span>
      )
    }
    default:
      return null
  }
}

export function ChatComposerField({
  value,
  onChange,
  onKeyDown,
  onPaste,
  inputRef: inputRefFromParent,
  placeholder = 'Message Talos…',
  className = '',
}) {
  const internalRef = useRef(null)
  const underlayRef = useRef(null)
  const wrapRef = useRef(null)

  const setTextareaRef = useCallback(
    (el) => {
      internalRef.current = el
      if (inputRefFromParent) {
        if (typeof inputRefFromParent === 'function') inputRefFromParent(el)
        else inputRefFromParent.current = el
      }
    },
    [inputRefFromParent],
  )

  const scrollSync = useCallback(() => {
    const ta = internalRef.current
    const ul = underlayRef.current
    if (ta && ul) ul.scrollTop = ta.scrollTop
  }, [])

  useLayoutEffect(() => {
    const ta = internalRef.current
    if (!ta) return
    ta.style.height = 'auto'
    const h = Math.min(MAX_PX, Math.max(24, ta.scrollHeight))
    ta.style.height = `${h}px`
    if (wrapRef.current) {
      wrapRef.current.style.minHeight = `${h}px`
    }
    if (underlayRef.current) {
      underlayRef.current.style.minHeight = `${h}px`
    }
  }, [value])

  const segs = value ? segmentMarkdownOverlay(value) : []
  const nodes = value ? segs.map((s, i) => <SegmentView key={i} s={s} />) : null

  return (
    <div ref={wrapRef} className={`relative w-full min-h-[24px] ${className}`.trim()}>
      <div
        ref={underlayRef}
        aria-hidden
        className={`absolute left-0 right-0 top-0 z-0 min-h-[24px] max-h-[200px] overflow-y-auto overflow-x-hidden rounded-md pointer-events-none text-left whitespace-pre-wrap break-words [scrollbar-width:thin] ${EDITOR_TEXT} text-ink/90`}
        style={{ maxHeight: MAX_PX }}
      >
        {value ? (
          <div className="min-h-[1.5em] pr-0.5 select-none">{nodes}</div>
        ) : (
          <div
            className={`min-h-[1.5em] pr-0.5 text-ink-muted/90 select-none ${EDITOR_TEXT}`.trim()}
          >
            {placeholder}
          </div>
        )}
      </div>
      <textarea
        ref={setTextareaRef}
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        onScroll={scrollSync}
        rows={1}
        placeholder=""
        autoComplete="off"
        spellCheck
        aria-label={placeholder}
        className={`relative z-10 w-full min-h-[24px] max-h-[200px] resize-none overflow-y-auto overflow-x-hidden bg-transparent text-transparent caret-amber-600 selection:bg-amber-200/40 ${EDITOR_TEXT} outline-none border-0 p-0 [scrollbar-width:thin]`}
        style={{ maxHeight: MAX_PX, lineHeight: '1.5' }}
      />
    </div>
  )
}
