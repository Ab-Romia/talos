import { useState } from 'react'
import { ChevronDown, ChevronRight, Bug } from 'lucide-react'

/**
 * Collapsible rendering of a RagTrace (the /ask debug payload):
 * timings + model chips, query rewrite, effective config with provenance,
 * retrieved file/chat candidates, and the final context + prompt.
 */

function Chip({ label, value }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface-2 text-[11px] text-ink-secondary whitespace-nowrap">
      <span className="text-ink-muted">{label}</span>
      <span className="font-mono font-medium text-ink">{value}</span>
    </span>
  )
}

function Section({ title, count, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-t border-[rgba(28,27,26,0.06)]">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1.5 py-1.5 text-[12px] font-medium text-ink-secondary hover:text-ink transition-colors"
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {title}
        {count != null && <span className="text-ink-muted font-normal">({count})</span>}
      </button>
      {open && <div className="pb-2 pl-5">{children}</div>}
    </div>
  )
}

function CandidateList({ docs }) {
  if (!docs?.length) return <p className="text-[12px] text-ink-muted italic">none retrieved</p>
  return (
    <div className="space-y-2">
      {docs.map((d, i) => {
        const meta = d.metadata || {}
        const source = meta.filename || (meta.source === 'chat' ? `chat segment` : meta.source) || 'unknown'
        const extras = [
          meta.page_number != null && meta.page_number !== 0 && `p.${meta.page_number}`,
          meta.section && `§ ${meta.section}`,
          meta.chunk_index != null && `chunk ${meta.chunk_index}`,
        ].filter(Boolean).join(' · ')
        return (
          <div key={i} className="rounded-lg bg-surface-2 px-2.5 py-1.5">
            <div className="flex items-baseline gap-2 text-[11px]">
              <span className="font-mono font-medium text-amber">[{i + 1}]</span>
              <span className="font-medium text-ink">{source}</span>
              {extras && <span className="text-ink-muted">{extras}</span>}
            </div>
            <p className="text-[12px] text-ink-secondary mt-0.5 whitespace-pre-wrap break-words">{d.snippet}</p>
          </div>
        )
      })}
    </div>
  )
}

export function RagTracePanel({ trace }) {
  const [open, setOpen] = useState(false)
  if (!trace) return null

  const cfg = trace.effective_config || {}
  const prov = trace.config_provenance || {}
  const sel = trace.chat_selection || {}

  return (
    <div className="mt-2 rounded-xl border border-amber/25 bg-amber/[0.04] text-ink">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 text-[12px] font-medium text-amber hover:bg-amber-subtle rounded-xl transition-colors"
      >
        <Bug size={13} />
        RAG trace
        <span className="font-normal text-ink-muted">
          retrieval {Math.round(trace.retrieval_ms)}ms · generation {Math.round(trace.generation_ms)}ms
        </span>
        <span className="flex-1" />
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>

      {open && (
        <div className="px-3 pb-2">
          <div className="flex flex-wrap gap-1.5 pb-2">
            <Chip label="model" value={trace.model} />
            <Chip label="embeddings" value={trace.embedding_provider} />
            <Chip label="top_k" value={cfg.retrieval_top_k} />
            <Chip label="fetch_k" value={cfg.rerank_fetch_k} />
            <Chip label="rerank" value={String(cfg.use_reranking)} />
            <Chip label="rewrite" value={String(cfg.use_query_rewrite)} />
            <Chip label="hyde" value={String(trace.hyde_used)} />
            <Chip label="req" value={(trace.request_id || '').slice(-8)} />
          </div>

          {trace.rewritten_query && trace.rewritten_query !== trace.original_query && (
            <div className="pb-2 text-[12px]">
              <span className="text-ink-muted">rewritten query: </span>
              <span className="italic text-ink-secondary">{trace.rewritten_query}</span>
            </div>
          )}

          <Section title="File candidates" count={trace.file_candidates?.length ?? 0}>
            <CandidateList docs={trace.file_candidates} />
          </Section>

          <Section title="Chat memory" count={trace.chat_candidates?.length ?? 0}>
            <div className="flex flex-wrap gap-1.5 mb-2">
              <Chip label="tail" value={trace.injected_tail_size} />
              <Chip label="fetched" value={sel.fetched ?? 0} />
              <Chip label="kept" value={sel.kept ?? 0} />
              <Chip label="dropped" value={(sel.dropped_tail ?? 0) + (sel.dropped_redundant ?? 0)} />
            </div>
            <CandidateList docs={trace.chat_candidates} />
          </Section>

          <Section title="Effective config + provenance">
            <table className="text-[11px] font-mono">
              <tbody>
                {Object.entries(cfg).map(([k, v]) => (
                  <tr key={k}>
                    <td className="pr-3 text-ink-muted">{k}</td>
                    <td className="pr-3 text-ink">{String(v)}</td>
                    <td className="text-amber">{prov[k] || 'global'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="Final context">
            <pre className="text-[11px] text-ink-secondary whitespace-pre-wrap break-words max-h-64 overflow-y-auto bg-surface-2 rounded-lg p-2">
              {trace.final_context || '(empty)'}
            </pre>
          </Section>

          <Section title="Full prompt">
            <pre className="text-[11px] text-ink-secondary whitespace-pre-wrap break-words max-h-64 overflow-y-auto bg-surface-2 rounded-lg p-2">
              {trace.prompt || '(empty)'}
            </pre>
          </Section>
        </div>
      )}
    </div>
  )
}
