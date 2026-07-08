import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { Layers, Plus, LogOut } from 'lucide-react'
import { bootstrapWorkspaces, switchWorkspace } from '../../store/workspaceSlice'
import { logout } from '../../store/authSlice'
import * as R from '../../constants/Routes'

function Spinner() {
  return (
    <div className="flex items-center justify-center h-screen bg-base">
      <div className="w-8 h-8 border-[3px] border-amber border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

// Landing page after login. Lists the workspaces the user belongs to:
//   - none    -> onboarding (create the first workspace)
//   - exactly one -> enter it directly
//   - several -> let the user pick
export default function WorkspaceSelectPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const user = useSelector((s) => s.auth.user)
  const { workspaces, loading } = useSelector((s) => s.workspace)
  const [decided, setDecided] = useState(false)
  // Only decide once the workspace fetch has actually run. Deciding off the
  // initial (empty, not-loading) state would wrongly bounce to onboarding
  // before the list is loaded.
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    dispatch(bootstrapWorkspaces()).finally(() => { if (!cancelled) setReady(true) })
    return () => { cancelled = true }
  }, [dispatch])

  useEffect(() => {
    if (!ready || decided || loading || !Array.isArray(workspaces)) return
    if (workspaces.length === 0) {
      setDecided(true)
      navigate(R.ONBOARDING, { replace: true })
    } else if (workspaces.length === 1) {
      setDecided(true)
      dispatch(switchWorkspace(workspaces[0].id))
      navigate(R.CHAT_PAGE, { replace: true })
    }
  }, [ready, workspaces, loading, decided, dispatch, navigate])

  const enter = (id) => {
    dispatch(switchWorkspace(id))
    navigate(R.CHAT_PAGE)
  }

  // While loading, or while auto-entering the only/no workspace, show a spinner.
  if (loading || !Array.isArray(workspaces) || workspaces.length < 2) {
    return <Spinner />
  }

  return (
    <div className="min-h-screen bg-base flex flex-col items-center px-4 py-10 sm:py-16">
      <div className="w-full max-w-[720px]">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 bg-amber rounded-lg flex items-center justify-center text-white text-xl font-bold">T</div>
          <span className="text-2xl font-bold text-ink tracking-tight">Talos</span>
        </div>

        <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-1">
          Choose a workspace
        </h1>
        <p className="text-sm text-ink-secondary mb-6">
          Welcome back{user?.name ? `, ${user.name.split(' ')[0]}` : ''}. Pick where you'd like to continue.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {workspaces.map((ws) => {
            const isOwner = user && ws.owner_id === user.id
            const channelCount = Array.isArray(ws.channels) ? ws.channels.length : 0
            return (
              <button
                key={ws.id}
                onClick={() => enter(ws.id)}
                className="text-left bg-surface-1 border border-[rgba(28,27,26,0.10)] rounded-xl p-4 flex items-center gap-3 hover:border-amber hover:bg-amber-subtle transition-colors"
              >
                <div className="w-11 h-11 bg-amber rounded-lg flex items-center justify-center text-white text-lg font-bold shrink-0 shadow-sm">
                  {(ws.name || 'W').charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-ink truncate">{ws.name}</p>
                  <p className="text-[12px] text-ink-tertiary flex items-center gap-1.5">
                    <span>{isOwner ? 'Owner' : 'Member'}</span>
                    {channelCount > 0 && (
                      <>
                        <span aria-hidden>·</span>
                        <span>{channelCount} {channelCount === 1 ? 'channel' : 'channels'}</span>
                      </>
                    )}
                  </p>
                </div>
              </button>
            )
          })}
        </div>

        <div className="flex items-center justify-between mt-8 pt-6 border-t border-[rgba(28,27,26,0.08)]">
          <button
            onClick={() => navigate(R.ONBOARDING)}
            className="flex items-center gap-2 text-[13px] font-medium text-amber hover:underline"
          >
            <Plus size={15} /> Create a new workspace
          </button>
          <button
            onClick={() => dispatch(logout())}
            className="flex items-center gap-2 text-[13px] font-medium text-ink-tertiary hover:text-ink-secondary"
          >
            <LogOut size={15} /> Sign out
          </button>
        </div>
      </div>
    </div>
  )
}
