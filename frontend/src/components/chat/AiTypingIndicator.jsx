import { Avatar, Box } from '@mui/material'
import { keyframes } from '@mui/system'
import { Sparkles } from 'lucide-react'

const AMBER = '#C4913A'

// Gentle wave for the three typing dots.
const dotWave = keyframes`
  0%, 60%, 100% { transform: translateY(0); opacity: 0.35; }
  30%          { transform: translateY(-4px); opacity: 1; }
`

// Soft breathing halo behind the avatar to signal active work.
const halo = keyframes`
  0%   { transform: scale(1);   opacity: 0.55; }
  70%  { transform: scale(1.6); opacity: 0; }
  100% { transform: scale(1.6); opacity: 0; }
`

/**
 * Ephemeral "Talos is thinking…" indicator shown in a channel while the
 * in-channel assistant generates a reply. It is never part of message
 * history — it appears on the `ai_typing:start` signal and disappears on
 * `ai_typing:stop` (or when the reply lands). Mirrors the assistant message
 * row so it reads as the same speaker warming up.
 */
export function AiTypingIndicator() {
  return (
    <div className="flex gap-3 mb-6" aria-live="polite" aria-label="Talos AI is thinking">
      <div className="pt-0.5">
        <Box sx={{ position: 'relative', width: 34, height: 34, flexShrink: 0 }}>
          <Box
            sx={{
              position: 'absolute',
              inset: 0,
              borderRadius: '50%',
              bgcolor: 'rgba(196,145,58,0.30)',
              animation: `${halo} 1.8s ease-out infinite`,
            }}
          />
          <Avatar
            sx={{
              position: 'relative',
              width: 34,
              height: 34,
              bgcolor: 'rgba(196,145,58,0.15)',
              color: AMBER,
            }}
          >
            <Sparkles size={16} />
          </Avatar>
        </Box>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[13px] font-semibold text-ink">Talos AI</span>
        </div>
        <Box
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 1,
            px: 1.5,
            py: 1,
            borderRadius: '14px',
            background: 'linear-gradient(180deg, rgba(196,145,58,0.10), rgba(196,145,58,0.05))',
            border: '1px solid rgba(196,145,58,0.20)',
          }}
        >
          <Box sx={{ display: 'flex', gap: '4px' }}>
            {[0, 1, 2].map((i) => (
              <Box
                key={i}
                sx={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  bgcolor: AMBER,
                  animation: `${dotWave} 1.2s ease-in-out ${i * 0.16}s infinite`,
                }}
              />
            ))}
          </Box>
          <span className="text-[12.5px] text-ink-secondary">Talos is thinking…</span>
        </Box>
      </div>
    </div>
  )
}
