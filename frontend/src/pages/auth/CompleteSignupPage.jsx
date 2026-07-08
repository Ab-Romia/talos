import { useEffect, useRef, useState } from 'react'
import { useDispatch } from 'react-redux'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import { MailCheck } from 'lucide-react'
import { completeSignup } from '../../store/authSlice'
import * as R from '../../constants/Routes'

const MIN_PASSWORD = 12
const PENDING_KEY = 'talos_signup_pending'

function readPending() {
  try {
    return JSON.parse(localStorage.getItem(PENDING_KEY) || '{}')
  } catch {
    return {}
  }
}

export default function CompleteSignupPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const token = params.get('token')

  const pending = readPending()
  const hasProfile = !!pending.username && (pending.password || '').length >= MIN_PASSWORD

  const [form, setForm] = useState({
    name: pending.name || '',
    username: pending.username || '',
    password: pending.password || '',
  })
  // 'verifying' while we auto-complete from the stashed profile; 'form' if we need
  // the user to re-enter (e.g. link opened on a different device); 'error' on failure.
  const [status, setStatus] = useState(token && hasProfile ? 'verifying' : 'form')
  const [error, setError] = useState('')
  const autoTried = useRef(false)

  const submit = async (data) => {
    setError('')
    const result = await dispatch(completeSignup({ email_token: token, ...data }))
    if (completeSignup.fulfilled.match(result)) {
      localStorage.removeItem(PENDING_KEY)
      navigate(R.ONBOARDING, { replace: true }) // → create your first workspace
      return true
    }
    setStatus('form')
    setError(result.payload || 'Could not complete signup. Please re-enter your details.')
    return false
  }

  // Arrived from the email link with a stashed profile → finish automatically.
  useEffect(() => {
    if (!token || autoTried.current) return
    if (hasProfile) {
      autoTried.current = true
      submit({ name: pending.name, username: pending.username, password: pending.password })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const upd = (f) => (e) => setForm({ ...form, [f]: e.target.value })
  const handleSubmit = (e) => {
    e.preventDefault()
    setStatus('verifying')
    submit(form)
  }

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base p-6 sm:p-12">
        <div className="w-full max-w-[400px]">
          <Alert severity="error" sx={{ mb: 3 }}>
            This verification link is missing its token or has expired.
          </Alert>
          <Link to={R.SIGNUP} className="text-amber font-medium hover:underline">Back to sign up</Link>
        </div>
      </div>
    )
  }

  // Happy path: verifying the email + finishing signup automatically.
  if (status === 'verifying') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base p-6 sm:p-12">
        <div className="w-full max-w-[400px] text-center">
          <div className="w-14 h-14 rounded-full bg-amber-subtle flex items-center justify-center mx-auto mb-5 text-amber">
            <MailCheck size={28} />
          </div>
          <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-2">Verifying your email…</h1>
          <p className="text-sm text-ink-secondary mb-6">Hang tight — finishing setting up your account.</p>
          <CircularProgress size={24} />
        </div>
      </div>
    )
  }

  // Fallback: no stashed profile (e.g. opened on another device) — ask once.
  const canSubmit = form.username && form.password.length >= MIN_PASSWORD
  return (
    <div className="flex min-h-screen items-center justify-center bg-base p-6 sm:p-12">
      <form onSubmit={handleSubmit} className="w-full max-w-[400px]">
        <div className="flex items-center gap-3 mb-8 justify-center">
          <div className="w-8 h-8 bg-amber rounded-lg flex items-center justify-center text-white text-lg font-bold">T</div>
          <span className="text-3xl font-bold text-ink tracking-tight">Talos</span>
        </div>

        <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-1">Finish creating your account</h1>
        <p className="text-sm text-ink-secondary mb-6">
          Your email is verified. Confirm your details to continue.
        </p>

        {error && <Alert severity="error" sx={{ mb: 3 }}>{error}</Alert>}

        <TextField fullWidth label="Full name" value={form.name} onChange={upd('name')} sx={{ mb: 2 }} />
        <TextField fullWidth label="Username" value={form.username} onChange={upd('username')} sx={{ mb: 2 }} />
        <TextField
          fullWidth
          label="Password"
          type="password"
          value={form.password}
          onChange={upd('password')}
          helperText={`At least ${MIN_PASSWORD} characters`}
          sx={{ mb: 3 }}
        />

        <Button type="submit" variant="contained" fullWidth disabled={!canSubmit} sx={{ mb: 2 }}>
          Complete signup
        </Button>

        <p className="text-center text-sm text-ink-secondary">
          <Link to={R.LOGIN} className="font-medium text-amber hover:underline">Back to sign in</Link>
        </p>
      </form>
    </div>
  )
}
