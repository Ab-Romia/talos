import { lazy, Suspense, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { refreshToken, completeOAuthHandoff } from './store/authSlice'
import * as R from './constants/Routes'

const LoginPage = lazy(() => import('./pages/auth/LoginPage'))
const SignupPage = lazy(() => import('./pages/auth/SignupPage'))
const ChatPage = lazy(() => import('./pages/chat/ChatPage'))
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

      <Route path="/" element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
        <Route index element={<Navigate to={R.CHAT_PAGE} replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>

      <Route path="*" element={<Navigate to={R.LOGIN} replace />} />
    </Routes>
    </Suspense>
  )
}
