import { useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import { Hash, MessageSquare, FileText } from 'lucide-react'
import { createWorkspace } from '../../store/workspaceSlice'
import * as R from '../../constants/Routes'

export default function OnboardingPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const user = useSelector((s) => s.auth.user)
  const workspaces = useSelector((s) => s.workspace.workspaces)

  const firstName = (user?.name || user?.username || '').split(' ')[0]
  const [name, setName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleCreate = async (e) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Give your workspace a name.')
      return
    }
    setSubmitting(true)
    setError('')
    const result = await dispatch(createWorkspace(trimmed))
    setSubmitting(false)
    if (createWorkspace.fulfilled.match(result)) {
      navigate(R.CHAT_PAGE, { replace: true })
    } else {
      setError(result.payload || 'Could not create workspace. Try a different name.')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-base p-6">
      <div className="w-full max-w-[460px]">
        <div className="flex items-center gap-3 mb-8 justify-center">
          <div className="w-9 h-9 bg-amber rounded-lg flex items-center justify-center text-white text-xl font-bold">T</div>
          <span className="text-3xl font-bold text-ink tracking-tight">Talos</span>
        </div>

        <div className="bg-surface-1 border border-[rgba(28,27,26,0.08)] rounded-2xl p-8 shadow-sm">
          <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-1">
            {firstName ? `Welcome, ${firstName}!` : 'Welcome to Talos!'}
          </h1>
          <p className="text-sm text-ink-secondary mb-6">
            Let’s create your first workspace — a home for your team’s channels, conversations
            and documents.
          </p>

          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          <form onSubmit={handleCreate}>
            <TextField
              autoFocus
              fullWidth
              label="Workspace name"
              placeholder="e.g. Acme Inc, Alex Uni, My Team"
              value={name}
              onChange={(e) => { setName(e.target.value); if (error) setError('') }}
              sx={{ mb: 2 }}
            />

            <div className="rounded-lg bg-surface-2 border border-[rgba(28,27,26,0.06)] p-3 mb-5">
              <p className="text-[12px] font-medium text-ink-tertiary uppercase tracking-wide mb-2">
                You’ll start with
              </p>
              <div className="space-y-1.5 text-[13px] text-ink-secondary">
                <div className="flex items-center gap-2"><Hash size={14} className="text-ink-tertiary" /> #general &amp; #random channels</div>
                <div className="flex items-center gap-2"><MessageSquare size={14} className="text-ink-tertiary" /> Real-time team chat</div>
                <div className="flex items-center gap-2"><FileText size={14} className="text-ink-tertiary" /> A shared documents space</div>
              </div>
            </div>

            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={submitting}
              startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : null}
            >
              {submitting ? 'Creating…' : 'Create workspace & continue'}
            </Button>
          </form>

          {workspaces.length > 0 && (
            <button
              onClick={() => navigate(R.CHAT_PAGE, { replace: true })}
              className="w-full text-center text-sm text-ink-tertiary hover:text-ink-secondary mt-4"
            >
              Skip — go to my existing workspace
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
