import { useState, useEffect, useRef, useCallback } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useSearchParams } from 'react-router-dom'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import InputAdornment from '@mui/material/InputAdornment'
import Alert from '@mui/material/Alert'
import Divider from '@mui/material/Divider'
import LinearProgress from '@mui/material/LinearProgress'
import CircularProgress from '@mui/material/CircularProgress'
import { Eye, EyeOff, MailCheck } from 'lucide-react'
import { signup, clearError } from '../../store/authSlice'
import { authService } from '../../services/auth'
import * as R from '../../constants/Routes'

const MIN_PASSWORD = 12

function getPasswordStrength(pw) {
  if (!pw) return { score: 0, label: '', color: 'inherit' }
  // Length is a hard requirement — never call a sub-minimum password "Strong".
  if (pw.length < MIN_PASSWORD) {
    return { score: 1, label: `Too short — at least ${MIN_PASSWORD} characters`, color: 'error' }
  }
  let score = 1 // length requirement met
  if (/[A-Z]/.test(pw)) score++
  if (/[0-9]/.test(pw)) score++
  if (/[^A-Za-z0-9]/.test(pw)) score++
  const levels = [
    { label: 'Weak', color: 'error' },
    { label: 'Fair', color: 'warning' },
    { label: 'Good', color: 'primary' },
    { label: 'Strong', color: 'success' },
  ]
  return { score, ...levels[Math.min(score - 1, 3)] }
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

// Returns a { field: message } map of everything blocking submission.
function validateSignup(form) {
  const errors = {}
  if (!form.name.trim()) errors.name = 'Enter your full name'
  if (!form.username.trim()) errors.username = 'Choose a username'
  if (!form.email.trim()) errors.email = 'Enter your email'
  else if (!EMAIL_RE.test(form.email.trim())) errors.email = 'Enter a valid email address'
  if (!form.password) errors.password = 'Enter a password'
  else if (form.password.length < MIN_PASSWORD)
    errors.password = `Password must be at least ${MIN_PASSWORD} characters`
  if (!form.confirm) errors.confirm = 'Re-enter your password'
  else if (form.password !== form.confirm) errors.confirm = 'Passwords do not match'
  return errors
}

export default function SignupPage() {
  const dispatch = useDispatch()
  const { loading, error } = useSelector((state) => state.auth)
  const [searchParams, setSearchParams] = useSearchParams()

  const [form, setForm] = useState({ name: '', username: '', email: '', password: '', confirm: '' })
  const [showPassword, setShowPassword] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [resent, setResent] = useState(false)
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
  const [fieldErrors, setFieldErrors] = useState({})
  const [oauthError, setOauthError] = useState('')

  // Surface a failed/aborted OAuth sign-in that redirected back here, then strip
  // the flag from the URL so it doesn't linger on refresh.
  useEffect(() => {
    const code = searchParams.get('oauth_error') || searchParams.get('error')
    if (!code) return
    setOauthError(
      code === 'unavailable'
        ? 'Could not reach the sign-in provider. Please try again in a moment.'
        : 'That sign-in was cancelled or could not be completed. Try again, or sign up with your email below.'
    )
    const next = new URLSearchParams(searchParams)
    next.delete('oauth_error')
    next.delete('error')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  const strength = getPasswordStrength(form.password)
  const passwordsMatch = !form.confirm || form.password === form.confirm

  const updateField = (field) => (e) => {
    setForm({ ...form, [field]: e.target.value })
    // Clear this field's error as soon as the user edits it.
    if (fieldErrors[field]) setFieldErrors((prev) => ({ ...prev, [field]: undefined }))
  }

  const requestVerification = async () => {
    // Stash the profile so the completion step (opened from the email link, often
    // in a NEW TAB) can finish signup automatically with the token. Use
    // localStorage — sessionStorage is per-tab and would be empty in the new tab.
    localStorage.setItem(
      'talos_signup_pending',
      JSON.stringify({ name: form.name, username: form.username, password: form.password })
    )
    return dispatch(signup({ email: form.email }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    dispatch(clearError())
    const errors = validateSignup(form)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return // show inline errors, don't submit
    const result = await requestVerification()
    if (signup.fulfilled.match(result)) { setSubmitted(true); startCooldown() }
  }

  const handleResend = async () => {
    dispatch(clearError())
    setResent(false)
    const result = await requestVerification()
    if (signup.fulfilled.match(result)) { setResent(true); startCooldown() }
  }

  const BrandPanel = (
    <div className="hidden lg:flex w-1/2 bg-amber-subtle flex-col items-center justify-center p-12">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-12 h-12 bg-amber rounded-lg flex items-center justify-center text-white text-2xl font-bold tracking-tight">T</div>
        <span className="text-4xl font-bold text-ink tracking-tight">Talos</span>
      </div>
      <p className="text-ink-secondary text-base mb-10">Your knowledge, connected.</p>
      <div className="relative w-80 h-60">
        <div className="absolute w-44 h-56 bg-white/70 rounded-lg border border-amber/15 top-2.5 left-10 -rotate-3" />
        <div className="absolute w-44 h-56 bg-white/85 rounded-lg border border-amber/15 top-1 left-18 rotate-1" />
        <div className="absolute w-44 h-56 bg-white/95 rounded-lg border border-amber/15 top-0 left-25 rotate-3 shadow-md" />
      </div>
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
              We sent a verification link to <span className="font-medium text-ink">{form.email}</span>.
              Open it to finish creating your account.
            </p>
            {resent && <Alert severity="success" sx={{ mb: 2 }}>Verification email resent.</Alert>}
            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
            <Button variant="outlined" fullWidth onClick={handleResend} disabled={loading || cooldown > 0} sx={{ mb: 2 }}>
              {loading ? <CircularProgress size={20} color="inherit" /> : cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend verification email'}
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

      {/* Right Form Panel */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-12 bg-base">
        <form onSubmit={handleSubmit} className="w-full max-w-[400px]">
          <div className="flex lg:hidden items-center gap-3 mb-8 justify-center">
            <div className="w-8 h-8 bg-amber rounded-lg flex items-center justify-center text-white text-lg font-bold">T</div>
            <span className="text-3xl font-bold text-ink tracking-tight">Talos</span>
          </div>

          <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-1">Create your account</h1>
          <p className="text-sm text-ink-secondary mb-8">Start building your knowledge base</p>

          {oauthError && (
            <Alert severity="error" onClose={() => setOauthError('')} sx={{ mb: 3 }}>
              {oauthError}
            </Alert>
          )}

          {error && (
            <Alert severity="error" onClose={() => dispatch(clearError())} sx={{ mb: 3 }}>
              {error}
              {/already exists/i.test(error) && (
                <>
                  {' '}
                  <Link to={R.LOGIN} className="font-medium text-amber hover:underline">Go to sign in</Link>
                </>
              )}
            </Alert>
          )}

          <Button variant="outlined" fullWidth onClick={() => authService.googleLogin()} sx={{ mb: 1.5, justifyContent: 'center', gap: 1 }}>
            <svg width="18" height="18" viewBox="0 0 18 18"><path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/><path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/><path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/><path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/></svg>
            Continue with Google
          </Button>
          <Button variant="outlined" fullWidth onClick={() => authService.githubLogin()} sx={{ mb: 3, justifyContent: 'center', gap: 1 }}>
            <svg width="18" height="18" viewBox="0 0 18 18"><path d="M9 0C4.03 0 0 4.03 0 9c0 3.98 2.58 7.35 6.16 8.54.45.08.61-.2.61-.43 0-.21-.01-.78-.01-1.53-2.51.55-3.04-1.21-3.04-1.21-.41-1.04-1-1.32-1-1.32-.82-.56.06-.55.06-.55.9.06 1.38.93 1.38.93.8 1.37 2.1.98 2.61.75.08-.58.31-.98.57-1.2-2-.23-4.1-1-4.1-4.46 0-.98.35-1.79.93-2.42-.09-.23-.4-1.15.09-2.39 0 0 .76-.24 2.48.93A8.66 8.66 0 019 4.38c.77.004 1.54.1 2.26.3 1.72-1.17 2.48-.93 2.48-.93.49 1.24.18 2.16.09 2.39.58.63.93 1.44.93 2.42 0 3.47-2.11 4.23-4.12 4.45.32.28.61.83.61 1.67 0 1.2-.01 2.17-.01 2.47 0 .24.16.52.62.43A9.002 9.002 0 0018 9c0-4.97-4.03-9-9-9z" fill="#1C1B1A"/></svg>
            Continue with GitHub
          </Button>

          <Divider sx={{ my: 3, color: 'text.disabled', fontSize: '14px' }}>or</Divider>

          <TextField
            fullWidth label="Full name" value={form.name} onChange={updateField('name')}
            error={!!fieldErrors.name} helperText={fieldErrors.name || ''} sx={{ mb: 2 }}
          />
          <TextField
            fullWidth label="Username" value={form.username} onChange={updateField('username')}
            error={!!fieldErrors.username} helperText={fieldErrors.username || ''} sx={{ mb: 2 }}
          />
          <TextField
            fullWidth label="Email" type="email" value={form.email} onChange={updateField('email')}
            autoComplete="email" error={!!fieldErrors.email} helperText={fieldErrors.email || ''} sx={{ mb: 2 }}
          />

          <TextField
            fullWidth
            label="Password"
            type={showPassword ? 'text' : 'password'}
            value={form.password}
            onChange={updateField('password')}
            placeholder={`Min. ${MIN_PASSWORD} characters`}
            error={!!fieldErrors.password}
            helperText={fieldErrors.password || ''}
            slotProps={{
              input: {
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton size="small" onClick={() => setShowPassword(!showPassword)} edge="end">
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </IconButton>
                  </InputAdornment>
                ),
              },
            }}
            sx={{ mb: 0.5 }}
          />
          {form.password && (
            <div className="mb-4">
              <LinearProgress
                variant="determinate"
                value={strength.score * 25}
                color={strength.color}
                sx={{ height: 3, borderRadius: 2, mb: 0.5 }}
              />
              <span className="text-xs" style={{ color: `var(--mui-palette-${strength.color}-main)` }}>
                {strength.label}
              </span>
            </div>
          )}

          <TextField
            fullWidth
            label="Confirm password"
            type="password"
            value={form.confirm}
            onChange={updateField('confirm')}
            error={!passwordsMatch || !!fieldErrors.confirm}
            helperText={!passwordsMatch ? 'Passwords do not match' : (fieldErrors.confirm || '')}
            sx={{ mb: 3 }}
          />

          <Button type="submit" variant="contained" fullWidth disabled={loading} sx={{ mb: 2 }}>
            {loading ? <CircularProgress size={20} color="inherit" /> : 'Create account'}
          </Button>

          <p className="text-center text-sm text-ink-secondary">
            Already have an account?{' '}
            <Link to={R.LOGIN} className="font-medium text-amber hover:underline">Sign in</Link>
          </p>
        </form>
      </div>
    </div>
  )
}
