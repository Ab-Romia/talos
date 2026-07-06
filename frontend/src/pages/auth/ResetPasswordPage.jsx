import { useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import InputAdornment from '@mui/material/InputAdornment'
import Alert from '@mui/material/Alert'
import LinearProgress from '@mui/material/LinearProgress'
import CircularProgress from '@mui/material/CircularProgress'
import { Eye, EyeOff, CheckCircle } from 'lucide-react'
import { resetPassword, clearError } from '../../store/authSlice'
import * as R from '../../constants/Routes'

const MIN_PASSWORD = 12

function getPasswordStrength(pw) {
  if (!pw) return { score: 0, label: '', color: 'inherit' }
  if (pw.length < MIN_PASSWORD) {
    return { score: 1, label: `Too short — at least ${MIN_PASSWORD} characters`, color: 'error' }
  }
  let score = 1
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

export default function ResetPasswordPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { loading, error } = useSelector((s) => s.auth)
  const [params] = useSearchParams()
  const token = params.get('token')

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [success, setSuccess] = useState(false)

  const strength = getPasswordStrength(password)
  const passwordsMatch = !confirm || password === confirm
  const canSubmit = password.length >= MIN_PASSWORD && password === confirm

  const handleSubmit = async (e) => {
    e.preventDefault()
    dispatch(clearError())
    const result = await dispatch(resetPassword({ token, password }))
    if (resetPassword.fulfilled.match(result)) {
      setSuccess(true)
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

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base p-12">
        <div className="w-full max-w-[400px]">
          <Alert severity="error" sx={{ mb: 3 }}>
            This password reset link is missing its token or has expired.
          </Alert>
          <Link to={R.FORGOT_PASSWORD} className="text-amber font-medium hover:underline">Request a new reset link</Link>
        </div>
      </div>
    )
  }

  if (success) {
    return (
      <div className="flex min-h-screen">
        {BrandPanel}
        <div className="w-full lg:w-1/2 flex items-center justify-center p-12 bg-base">
          <div className="w-full max-w-[400px] text-center">
            <div className="w-14 h-14 rounded-full bg-amber-subtle flex items-center justify-center mx-auto mb-5 text-amber">
              <CheckCircle size={28} />
            </div>
            <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-2">Password reset</h1>
            <p className="text-sm text-ink-secondary mb-6">
              Your password has been updated successfully. You can now sign in with your new password.
            </p>
            <Button
              variant="contained"
              fullWidth
              onClick={() => navigate(R.LOGIN)}
            >
              Sign in
            </Button>
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

          <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-1">Set a new password</h1>
          <p className="text-sm text-ink-secondary mb-8">
            Choose a strong password for your account.
          </p>

          {error && (
            <Alert severity="error" onClose={() => dispatch(clearError())} sx={{ mb: 3 }}>
              {error}
            </Alert>
          )}

          <TextField
            fullWidth
            label="New password"
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            autoComplete="new-password"
            placeholder={`Min. ${MIN_PASSWORD} characters`}
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
          {password && (
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
            label="Confirm new password"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            error={!passwordsMatch}
            helperText={!passwordsMatch ? 'Passwords do not match' : ''}
            sx={{ mb: 3 }}
          />

          <Button
            type="submit"
            variant="contained"
            fullWidth
            disabled={loading || !canSubmit}
            sx={{ mb: 3 }}
          >
            {loading ? <CircularProgress size={20} color="inherit" /> : 'Reset password'}
          </Button>

          <p className="text-center text-sm text-ink-secondary">
            <Link to={R.LOGIN} className="font-medium text-amber hover:underline">Back to sign in</Link>
          </p>
        </form>
      </div>
    </div>
  )
}
