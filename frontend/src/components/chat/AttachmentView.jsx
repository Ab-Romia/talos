import { useEffect, useRef, useState } from 'react'
import Dialog from '@mui/material/Dialog'
import IconButton from '@mui/material/IconButton'
import CircularProgress from '@mui/material/CircularProgress'
import { FileText, Download, X, Maximize2 } from 'lucide-react'
import { chatService } from '../../services/chat'

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2]

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

// Resolve (and cache) the signed streaming URL for an attachment.
function useMediaUrl(channelId, attachment) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    let cancelled = false
    setUrl(null)
    if (!channelId || !attachment?.id) return undefined
    chatService
      .getAttachmentUrl(channelId, attachment.id)
      .then((res) => { if (!cancelled && res?.url) setUrl(res.url) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [channelId, attachment?.id])
  return url
}

function ImageAttachment({ channelId, attachment }) {
  const url = useMediaUrl(channelId, attachment)
  const [open, setOpen] = useState(false)
  if (!url) return <MediaPlaceholder label={attachment.filename} />
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="block text-left">
        <img
          src={url}
          alt={attachment.filename}
          loading="lazy"
          className="max-h-[260px] w-auto max-w-full sm:max-w-[360px] rounded-xl border border-[rgba(28,27,26,0.10)] object-cover hover:brightness-95 transition"
        />
      </button>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="lg">
        <div className="relative bg-black/95 flex items-center justify-center">
          <IconButton onClick={() => setOpen(false)} sx={{ position: 'absolute', top: 8, right: 8, color: 'white', zIndex: 1 }}>
            <X size={18} />
          </IconButton>
          <img src={url} alt={attachment.filename} className="max-h-[85vh] max-w-[90vw] object-contain" />
        </div>
      </Dialog>
    </>
  )
}

function VideoPlayer({ url, autoPlay = false, className = '' }) {
  const ref = useRef(null)
  const [speed, setSpeed] = useState(1)
  const applySpeed = (s) => {
    setSpeed(s)
    if (ref.current) ref.current.playbackRate = s
  }
  return (
    <div className={`flex flex-col gap-1 ${className}`.trim()}>
      <video
        ref={ref}
        src={url}
        controls
        preload="metadata"
        autoPlay={autoPlay}
        playsInline
        className="w-full rounded-xl bg-black outline-none"
      />
      <div className="flex items-center gap-1 self-end">
        <span className="text-[11px] text-ink-tertiary mr-0.5">Speed</span>
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => applySpeed(s)}
            className={`px-1.5 h-5 rounded text-[11px] font-medium transition-colors ${
              speed === s ? 'bg-amber text-white' : 'text-ink-tertiary hover:bg-surface-3'
            }`}
          >
            {s}×
          </button>
        ))}
      </div>
    </div>
  )
}

function VideoAttachment({ channelId, attachment }) {
  const url = useMediaUrl(channelId, attachment)
  const [expanded, setExpanded] = useState(false)
  if (!url) return <MediaPlaceholder label={attachment.filename} />
  return (
    <div className="relative max-w-[420px]">
      <VideoPlayer url={url} />
      <button
        type="button"
        onClick={() => setExpanded(true)}
        title="Open large player"
        className="absolute top-2 right-2 w-7 h-7 rounded-lg bg-black/50 text-white flex items-center justify-center hover:bg-black/70 transition"
      >
        <Maximize2 size={13} />
      </button>
      <Dialog open={expanded} onClose={() => setExpanded(false)} maxWidth="lg" fullWidth>
        <div className="relative bg-black p-4 pt-10">
          <IconButton onClick={() => setExpanded(false)} sx={{ position: 'absolute', top: 4, right: 4, color: 'white', zIndex: 1 }}>
            <X size={18} />
          </IconButton>
          <VideoPlayer url={url} autoPlay className="[&_video]:max-h-[78vh]" />
          <p className="text-white/70 text-[12px] mt-1 truncate">{attachment.filename}</p>
        </div>
      </Dialog>
    </div>
  )
}

function FileAttachment({ channelId, attachment }) {
  const url = useMediaUrl(channelId, attachment)
  return (
    <a
      href={url || undefined}
      download={attachment.filename}
      target="_blank"
      rel="noreferrer"
      className={`inline-flex items-center gap-2.5 pl-2.5 pr-3 py-2 rounded-xl border border-[rgba(28,27,26,0.10)] bg-surface-2 hover:bg-surface-3 transition-colors max-w-[320px] ${url ? '' : 'pointer-events-none opacity-60'}`}
    >
      <span className="w-8 h-8 rounded-lg bg-amber-subtle text-amber flex items-center justify-center shrink-0">
        <FileText size={16} />
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-ink truncate">{attachment.filename}</span>
        <span className="block text-[11px] text-ink-tertiary">{formatSize(attachment.size_bytes)}</span>
      </span>
      <Download size={14} className="text-ink-tertiary shrink-0 ml-1" />
    </a>
  )
}

function MediaPlaceholder({ label }) {
  return (
    <div className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-2 border border-[rgba(28,27,26,0.08)]">
      <CircularProgress size={14} />
      <span className="text-[12px] text-ink-tertiary truncate max-w-[220px]">{label}</span>
    </div>
  )
}

export function AttachmentView({ channelId, attachments }) {
  if (!attachments?.length) return null
  return (
    <div className="flex flex-wrap gap-2 mt-1.5">
      {attachments.map((a) => {
        const type = a.content_type || ''
        if (type.startsWith('image/')) return <ImageAttachment key={a.id} channelId={channelId} attachment={a} />
        if (type.startsWith('video/')) return <VideoAttachment key={a.id} channelId={channelId} attachment={a} />
        return <FileAttachment key={a.id} channelId={channelId} attachment={a} />
      })}
    </div>
  )
}
