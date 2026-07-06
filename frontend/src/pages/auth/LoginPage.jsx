import { useState, useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useNavigate } from 'react-router-dom'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import InputAdornment from '@mui/material/InputAdornment'
import Alert from '@mui/material/Alert'
import Divider from '@mui/material/Divider'
import CircularProgress from '@mui/material/CircularProgress'
import { Eye, EyeOff, KeyRound } from 'lucide-react'
import { login, clearError, verifyTotp, loginWithPasskey } from '../../store/authSlice'
import { authService } from '../../services/auth'
import { webauthn } from '../../services/webauthn'
import * as R from '../../constants/Routes'

export default function LoginPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { loading, error, requiresOtp, isAuthenticated } = useSelector((state) => state.auth)

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [otp, setOtp] = useState('')
  const [passkeySupported, setPasskeySupported] = useState(false)

  useEffect(() => {
    setPasskeySupported(webauthn.isSupported())
  }, [])

  useEffect(() => {
    if (isAuthenticated) navigate(R.CHAT_PAGE)
  }, [isAuthenticated, navigate])

  const handleSubmit = async (e) => {
    e.preventDefault()
    dispatch(clearError())
    await dispatch(login({ username, password }))
  }

  const handleVerifyOtp = async (e) => {
    e.preventDefault()
    dispatch(clearError())
    const result = await dispatch(verifyTotp({ otp }))
    if (verifyTotp.fulfilled.match(result)) {
      navigate(R.CHAT_PAGE)
    }
  }

  const handlePasskeyLogin = async () => {
    dispatch(clearError())
    const result = await dispatch(loginWithPasskey())
    if (loginWithPasskey.fulfilled.match(result)) {
      navigate(R.CHAT_PAGE)
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* Left Brand Panel */}
      <div className="hidden lg:flex w-1/2 bg-amber-subtle flex-col items-center justify-center p-12">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 bg-amber rounded-lg flex items-center justify-center text-white text-2xl font-bold tracking-tight">
            T
          </div>
          <span className="text-4xl font-bold text-ink tracking-tight">Talos</span>
        </div>
        <p className="text-ink-secondary text-base mb-10">Your knowledge, connected.</p>

        <div className="relative w-80 h-60">
          <div className="absolute w-44 h-56 bg-white/70 rounded-lg border border-amber/15 top-2.5 left-10 -rotate-3" />
          <div className="absolute w-44 h-56 bg-white/85 rounded-lg border border-amber/15 top-1 left-18 rotate-1" />
          <div className="absolute w-44 h-56 bg-white/95 rounded-lg border border-amber/15 top-0 left-25 rotate-3 shadow-md">
            <div className="mt-6 mx-4 space-y-2">
              <div className="h-0.5 bg-ink/8 rounded w-3/5" />
              <div className="h-0.5 bg-ink/8 rounded w-4/5" />
              <div className="h-0.5 bg-amber/25 rounded w-7/10" />
              <div className="h-0.5 bg-ink/8 rounded w-9/10" />
              <div className="h-0.5 bg-ink/8 rounded w-1/2" />
            </div>
          </div>
          <div className="absolute w-15 h-0.5 bg-amber/30 top-20 left-5 rotate-15 rounded" />
          <div className="absolute w-11 h-0.5 bg-amber/30 top-35 left-62 -rotate-10 rounded" />
          <div className="absolute w-2 h-2 bg-amber/50 rounded-full top-19.5 left-4.5" />
          <div className="absolute w-2 h-2 bg-amber/50 rounded-full top-34.5 left-73" />
        </div>
      </div>

      {/* Right Form Panel */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6 sm:p-12 bg-base">
        {requiresOtp ? (
          <form onSubmit={handleVerifyOtp} className="w-full max-w-[400px]">
            <div className="flex lg:hidden items-center gap-3 mb-8 justify-center">
              <div className="w-8 h-8 bg-amber rounded-lg flex items-center justify-center text-white text-lg font-bold">T</div>
              <span className="text-3xl font-bold text-ink tracking-tight">Talos</span>
            </div>

            <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-1">Two-factor authentication</h1>
            <p className="text-sm text-ink-secondary mb-8">
              Enter the 6-digit code from your authenticator app.
            </p>

            {error && (
              <Alert severity="error" onClose={() => dispatch(clearError())} className="mb-6" sx={{ mb: 3 }}>
                {error}
              </Alert>
            )}

            <TextField
              fullWidth
              label="Verification code"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
              autoFocus
              autoComplete="one-time-code"
              inputMode="numeric"
              slotProps={{ htmlInput: { maxLength: 6, style: { letterSpacing: '0.5em', textAlign: 'center', fontSize: 18 } } }}
              sx={{ mb: 3 }}
            />

            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading || otp.length !== 6}
              sx={{ mb: 2 }}
            >
              {loading ? <CircularProgress size={20} color="inherit" /> : 'Verify'}
            </Button>

            <p className="text-center text-sm text-ink-secondary">
              Having trouble?{' '}
              <Link to={R.LOGIN} className="font-medium text-amber hover:underline" onClick={() => dispatch(clearError())}>
                Use another method
              </Link>
            </p>
          </form>
        ) : (
          <form onSubmit={handleSubmit} className="w-full max-w-[400px]">
            <div className="flex lg:hidden items-center gap-3 mb-8 justify-center">
              <div className="w-8 h-8 bg-amber rounded-lg flex items-center justify-center text-white text-lg font-bold">T</div>
              <span className="text-3xl font-bold text-ink tracking-tight">Talos</span>
            </div>

            <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-1">Welcome back</h1>
            <p className="text-sm text-ink-secondary mb-8">Sign in to your workspace</p>

            {error && (
              <Alert severity="error" onClose={() => dispatch(clearError())} className="mb-6" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}

            <Button
              variant="outlined"
              fullWidth
              onClick={() => authService.googleLogin()}
              sx={{ mb: 1.5, justifyContent: 'center', gap: 1 }}
            >
              <svg width="18" height="18" viewBox="0 0 18 18">
                <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
                <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
                <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
                <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
              </svg>
              Continue with Google
            </Button>

            <Button
              variant="outlined"
              fullWidth
              onClick={() => authService.githubLogin()}
              sx={{ mb: 1.5, justifyContent: 'center', gap: 1 }}
            >
              <svg width="18" height="18" viewBox="0 0 18 18">
                <path d="M9 0C4.03 0 0 4.03 0 9c0 3.98 2.58 7.35 6.16 8.54.45.08.61-.2.61-.43 0-.21-.01-.78-.01-1.53-2.51.55-3.04-1.21-3.04-1.21-.41-1.04-1-1.32-1-1.32-.82-.56.06-.55.06-.55.9.06 1.38.93 1.38.93.8 1.37 2.1.98 2.61.75.08-.58.31-.98.57-1.2-2-.23-4.1-1-4.1-4.46 0-.98.35-1.79.93-2.42-.09-.23-.4-1.15.09-2.39 0 0 .76-.24 2.48.93A8.66 8.66 0 019 4.38c.77.004 1.54.1 2.26.3 1.72-1.17 2.48-.93 2.48-.93.49 1.24.18 2.16.09 2.39.58.63.93 1.44.93 2.42 0 3.47-2.11 4.23-4.12 4.45.32.28.61.83.61 1.67 0 1.2-.01 2.17-.01 2.47 0 .24.16.52.62.43A9.002 9.002 0 0018 9c0-4.97-4.03-9-9-9z" fill="#1C1B1A"/>
              </svg>
              Continue with GitHub
            </Button>

            {passkeySupported && (
              <Button
                variant="outlined"
                fullWidth
                onClick={handlePasskeyLogin}
                startIcon={<KeyRound size={16} />}
                disabled={loading}
                sx={{ mb: 3, justifyContent: 'center', gap: 1 }}
              >
                Sign in with a passkey
              </Button>
            )}

            <Divider sx={{ my: 3, color: 'text.disabled', fontSize: '14px' }}>or</Divider>

            <TextField
              fullWidth
              label="Email or username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              sx={{ mb: 2 }}
            />

            <TextField
              fullWidth
              label="Password"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
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
              sx={{ mb: 3 }}
            />

            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading || !username || !password}
              sx={{ mb: 3 }}
            >
              {loading ? <CircularProgress size={20} color="inherit" /> : 'Sign in'}
            </Button>

            <p className="text-center text-sm text-ink-secondary">
              Don't have an account?{' '}
              <Link to={R.SIGNUP} className="font-medium text-amber hover:underline">Sign up</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
