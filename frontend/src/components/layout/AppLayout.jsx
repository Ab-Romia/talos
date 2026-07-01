import { useEffect } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import Sidebar from './Sidebar'
import Topbar from './Topbar'
import { bootstrapWorkspaces } from '../../store/workspaceSlice'
import useNotificationsSocket from '../../hooks/useNotificationsSocket'
import useNotificationClickHandler from '../../hooks/useNotificationClickHandler'
import * as R from '../../constants/Routes'

export default function AppLayout() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const isAuthenticated = useSelector((s) => s.auth.isAuthenticated)

  useEffect(() => {
    if (!isAuthenticated) return
    dispatch(bootstrapWorkspaces())
      .unwrap()
      .then((res) => {
        // Brand-new account with no workspace yet → send them to onboarding.
        if (res && Array.isArray(res.workspaces) && res.workspaces.length === 0) {
          navigate(R.ONBOARDING, { replace: true })
        }
      })
      .catch(() => {
        // Thunk was skipped (workspaces already loaded) or failed — no redirect.
      })
  }, [dispatch, isAuthenticated, navigate])

  useNotificationsSocket()
  useNotificationClickHandler()

  return (
    <div className="flex h-screen overflow-hidden bg-base">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0 bg-surface-1">
        <Topbar />
        <Outlet />
      </main>
    </div>
  )
}
