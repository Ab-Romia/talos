import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

const rehypeSanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: ['className', ...(defaultSchema.attributes?.code || [])],
    pre: ['className', ...(defaultSchema.attributes?.pre || [])],
  },
}

export function ChatMessageContent({
  className = '',
  content = '',
  renderCursor = false,
  interactiveLinks = true,
}) {
  const rehypePlugins = useMemo(
    () => [[rehypeSanitize, rehypeSanitizeSchema]],
    [],
  )

  if (content == null) return null

  const hasText = String(content).trim().length > 0
  const streamingWithNoTextYet = renderCursor && !hasText

  if (streamingWithNoTextYet) {
    return (
      <div
        className={`chat-message-md text-[14px] text-ink leading-relaxed min-w-0 max-w-full ${className}`.trim()}
        role="status"
        aria-live="polite"
        aria-label="Assistant is replying"
      >
        <span className="text-ink-secondary">Thinking</span>
        <span className="inline-flex gap-0.5 ml-1 align-middle" aria-hidden>
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-ink-tertiary/70 animate-bounce [animation-delay:0ms]" />
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-ink-tertiary/70 animate-bounce [animation-delay:0.15s]" />
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-ink-tertiary/70 animate-bounce [animation-delay:0.3s]" />
        </span>
      </div>
    )
  }

  if (!hasText && !renderCursor) {
    return null
  }

  return (
    <div
      className={`chat-message-md text-[14px] text-ink leading-relaxed min-w-0 max-w-full ${className}`.trim()}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        rehypePlugins={rehypePlugins}
        components={{
          p: ({ children }) => <p className="mb-2 last:mb-0 [li>&]:mb-0">{children}</p>,
          a: ({ href, children }) => (
            <a
              href={href}
              target={interactiveLinks ? '_blank' : undefined}
              rel={interactiveLinks ? 'noopener noreferrer' : undefined}
              onClick={interactiveLinks ? undefined : (e) => e.preventDefault()}
              className={`text-amber font-medium underline decoration-amber/40 underline-offset-2 ${
                interactiveLinks ? 'hover:decoration-amber' : 'cursor-text'
              }`}
            >
              {children}
            </a>
          ),
          h1: ({ children }) => <h1 className="text-lg font-bold mt-2 mb-1 text-ink first:mt-0">{children}</h1>,
          h2: ({ children }) => <h3 className="text-base font-bold mt-2 mb-1 text-ink first:mt-0">{children}</h3>,
          h3: ({ children }) => <h4 className="text-[15px] font-semibold mt-2 mb-1 text-ink first:mt-0">{children}</h4>,
          ul: ({ children }) => <ul className="list-disc pl-5 my-2 space-y-0.5 [li>ul]:list-[circle]">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 my-2 space-y-0.5">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-[3px] border-amber/40 pl-3 my-2 text-ink-secondary italic bg-amber/5 py-0.5 rounded-r">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-3 border-[rgba(28,27,26,0.1)]" />,
          table: ({ children }) => (
            <div className="overflow-x-auto my-2 max-w-full rounded-lg border border-[rgba(28,27,26,0.1)]">
              <table className="w-full min-w-0 text-[13px] border-collapse [&_th]:text-left">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border-b border-[rgba(28,27,26,0.1)] bg-surface-2 px-2 py-1.5 font-semibold">
              {children}
            </th>
          ),
          td: ({ children }) => <td className="border-b border-[rgba(28,27,26,0.06)] px-2 py-1.5 align-top">{children}</td>,
          tr: ({ children }) => <tr className="last:[&>td]:border-b-0">{children}</tr>,
          img: ({ src, alt }) => (
            <img
              src={src}
              alt={alt || ''}
              className="max-w-full h-auto rounded-lg my-2 border border-[rgba(28,27,26,0.08)]"
              loading="lazy"
            />
          ),
          pre: ({ children }) => (
            <div className="mb-2 max-w-full first:mt-0 overflow-x-auto rounded-xl border border-[rgba(28,27,26,0.1)]">
              {children}
            </div>
          ),
          code({ className, children, ...rest }) {
            const match = /language-(\w+)/.exec(className || '')
            const isBlock = match != null
            if (isBlock) {
              return (
                <SyntaxHighlighter
                  style={oneLight}
                  language={match[1].toLowerCase() === 'text' ? 'text' : match[1]}
                  PreTag="div"
                  customStyle={{
                    margin: 0,
                    borderRadius: '0.75rem',
                    fontSize: '12.5px',
                    lineHeight: 1.55,
                    padding: '0.9rem 1rem',
                    background: 'var(--md-code-bg, #f6f8fa)',
                    border: 'none',
                  }}
                  codeTagProps={{ className: 'font-mono' }}
                >
                  {String(children).replace(/\n$/, '')}
                </SyntaxHighlighter>
              )
            }
            return (
              <code
                className="bg-surface-2 text-ink px-1.5 py-0.5 rounded-md text-[0.9em] font-mono [li>&]:px-1"
                {...rest}
              >
                {children}
              </code>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
      {renderCursor && hasText && (
        <span
          className="inline-block w-[2px] h-[1.1em] align-text-bottom ml-0.5 rounded-sm bg-amber-600/85 animate-pulse"
          style={{ verticalAlign: '-0.1em' }}
          aria-hidden
        />
      )}
    </div>
  )
}

export function attachmentLabel(a) {
  if (a == null) return ''
  if (typeof a === 'string') return a
  return a.filename || a.name || String(a)
}

export function attachmentKey(a, i) {
  if (a != null && typeof a === 'object' && a.file_id) return a.file_id
  return `${attachmentLabel(a)}-${i}`
}
