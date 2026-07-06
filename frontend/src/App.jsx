import { lazy, Suspense, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { refreshToken, completeOAuthHandoff } from './store/authSlice'
import { setSessionToken } from './services/api'
import * as R from './constants/Routes'

const LoginPage = lazy(() => import('./pages/auth/LoginPage'))
const SignupPage = lazy(() => import('./pages/auth/SignupPage'))
const CompleteSignupPage = lazy(() => import('./pages/auth/CompleteSignupPage'))
const ForgotPasswordPage = lazy(() => import('./pages/auth/ForgotPasswordPage'))
const ResetPasswordPage = lazy(() => import('./pages/auth/ResetPasswordPage'))
const OnboardingPage = lazy(() => import('./pages/onboarding/OnboardingPage'))
const ChatPage = lazy(() => import('./pages/chat/ChatPage'))
const AIChatPage = lazy(() => import('./pages/ai/AIChatPage'))
const DocumentsPage = lazy(() => import('./pages/documents/DocumentsPage'))
const SettingsPage = lazy(() => import('./pages/settings/SettingsPage'))
const AppLayout = lazy(() => import('./components/layout/AppLayout'))

function ProtectedRoute({ children }) {
  const { isAuthenticated, sessionChecked } = useSelector((state) => state.auth)
  if (!sessionChecked) return <Fallback />
  if (!isAuthenticated) return <Navigate to={R.LOGIN} replace />
  return children
}

function GuestRoute({ children }) {
  const { isAuthenticated, sessionChecked } = useSelector((state) => state.auth)
  if (!sessionChecked) return <Fallback />
  if (isAuthenticated) return <Navigate to={R.CHAT_PAGE} replace />
  return children
}

function Fallback() {
  return (
    <div className="flex items-center justify-center h-screen bg-base">
      <div className="w-8 h-8 border-3 border-amber border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

export default function App() {
  const dispatch = useDispatch()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const handoff = params.get('oauth_handoff')
    const oauthError = params.get('oauth_error') || params.get('error')
    const oauthSuccess = params.get('oauth_success')

    if (oauthError) {
      // OAuth bounced us back without a session — become a clean guest so the
      // guards land on the signup screen (which surfaces the error), not the app.
      setSessionToken(null)
      dispatch({ type: 'auth/logout/fulfilled' })
      return
    }

    if (oauthSuccess) {
      // OAuth signed us in via a fresh session cookie — drop any stale bearer
      // token so the cookie is used, then load the user (which returns a new
      // session token), and clean the flag out of the URL.
      setSessionToken(null)
      dispatch(refreshToken())
      params.delete('oauth_success')
      const s = params.toString()
      window.history.replaceState(null, '', window.location.pathname + (s ? `?${s}` : '') + window.location.hash)
      return
    }

    if (handoff) {
      void (async () => {
        try {
          await dispatch(completeOAuthHandoff(handoff)).unwrap()
        } catch {}
        params.delete('oauth_handoff')
        const s = params.toString()
        const next =
          window.location.pathname + (s ? `?${s}` : '') + window.location.hash
        window.history.replaceState(null, '', next)
        dispatch(refreshToken())
      })()
    } else {
      dispatch(refreshToken())
    }
  }, [dispatch])

  return (
    <Suspense fallback={<Fallback />}>
    <Routes>
      <Route path={R.LOGIN} element={<GuestRoute><LoginPage /></GuestRoute>} />
      <Route path={R.SIGNUP} element={<GuestRoute><SignupPage /></GuestRoute>} />
      <Route path={R.FORGOT_PASSWORD} element={<GuestRoute><ForgotPasswordPage /></GuestRoute>} />
      <Route path={R.RESET_PASSWORD} element={<GuestRoute><ResetPasswordPage /></GuestRoute>} />
      {/* Not a GuestRoute: completion logs the user in, then redirects to onboarding. */}
      <Route path={R.SIGNUP_COMPLETE} element={<CompleteSignupPage />} />
      <Route path={R.ONBOARDING} element={<ProtectedRoute><OnboardingPage /></ProtectedRoute>} />

      <Route path="/" element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
        <Route index element={<Navigate to={R.CHAT_PAGE} replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="ai" element={<AIChatPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>

      <Route path="*" element={<Navigate to={R.LOGIN} replace />} />
    </Routes>
    </Suspense>
  )
}
