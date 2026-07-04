import { useState, useRef, useCallback, useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link } from 'react-router-dom'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import { MailCheck } from 'lucide-react'
import { forgotPassword, clearError } from '../../store/authSlice'
import * as R from '../../constants/Routes'

export default function ForgotPasswordPage() {
  const dispatch = useDispatch()
  const { loading, error } = useSelector((s) => s.auth)

  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const cooldownRef = useRef(null)

  const startCooldown = useCallback(() => {
    setCooldown(60)
    clearInterval(cooldownRef.current)
    cooldownRef.current = setInterval(() => {
      setCooldown((prev) => {
        if (prev <= 1) { clearInterval(cooldownRef.current); return 0 }
        return prev - 1
      })
    }, 1000)
  }, [])

  useEffect(() => () => clearInterval(cooldownRef.current), [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    dispatch(clearError())
    const result = await dispatch(forgotPassword({ email: email.trim() }))
    if (forgotPassword.fulfilled.match(result)) {
      setSubmitted(true)
      startCooldown()
    }
  }

  const handleResend = async () => {
    dispatch(clearError())
    const result = await dispatch(forgotPassword({ email: email.trim() }))
    if (forgotPassword.fulfilled.match(result)) {
      startCooldown()
    }
  }

  const BrandPanel = (
    <div className="hidden lg:flex w-1/2 bg-amber-subtle flex-col items-center justify-center p-12">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-12 h-12 bg-amber rounded-lg flex items-center justify-center text-white text-2xl font-bold tracking-tight">T</div>
        <span className="text-4xl font-bold text-ink tracking-tight">Talos</span>
      </div>
      <p className="text-ink-secondary text-base mb-10">Your knowledge, connected.</p>
    </div>
  )

  if (submitted) {
    return (
      <div className="flex min-h-screen">
        {BrandPanel}
        <div className="w-full lg:w-1/2 flex items-center justify-center p-12 bg-base">
          <div className="w-full max-w-[400px] text-center">
            <div className="w-14 h-14 rounded-full bg-amber-subtle flex items-center justify-center mx-auto mb-5 text-amber">
              <MailCheck size={28} />
            </div>
            <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-2">Check your email</h1>
            <p className="text-sm text-ink-secondary mb-6">
              If an account exists for <span className="font-medium text-ink">{email}</span>, we sent a password reset link.
            </p>
            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
            <Button
              variant="outlined"
              fullWidth
              onClick={handleResend}
              disabled={loading || cooldown > 0}
              sx={{ mb: 2 }}
            >
              {loading ? <CircularProgress size={20} color="inherit" /> : cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend reset email'}
            </Button>
            <p className="text-center text-sm text-ink-secondary">
              <Link to={R.LOGIN} className="font-medium text-amber hover:underline">Back to sign in</Link>
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen">
      {BrandPanel}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-12 bg-base">
        <form onSubmit={handleSubmit} className="w-full max-w-[400px]">
          <div className="flex lg:hidden items-center gap-3 mb-8 justify-center">
            <div className="w-8 h-8 bg-amber rounded-lg flex items-center justify-center text-white text-lg font-bold">T</div>
            <span className="text-3xl font-bold text-ink tracking-tight">Talos</span>
          </div>

          <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-1">Forgot your password?</h1>
          <p className="text-sm text-ink-secondary mb-8">
            Enter the email address associated with your account and we'll send you a link to reset your password.
          </p>

          {error && (
            <Alert severity="error" onClose={() => dispatch(clearError())} sx={{ mb: 3 }}>
              {error}
            </Alert>
          )}

          <TextField
            fullWidth
            label="Email address"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
            autoComplete="email"
            sx={{ mb: 3 }}
          />

          <Button
            type="submit"
            variant="contained"
            fullWidth
            disabled={loading || !email.trim()}
            sx={{ mb: 3 }}
          >
            {loading ? <CircularProgress size={20} color="inherit" /> : 'Send reset link'}
          </Button>

          <p className="text-center text-sm text-ink-secondary">
            Remember your password?{' '}
            <Link to={R.LOGIN} className="font-medium text-amber hover:underline">Sign in</Link>
          </p>
        </form>
      </div>
    </div>
  )
}
