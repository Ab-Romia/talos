import { useEffect, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import Snackbar from '@mui/material/Snackbar'
import Alert from '@mui/material/Alert'
import Sidebar from './Sidebar'
import { bootstrapWorkspaces, clearSyncNotice } from '../../store/workspaceSlice'
import { PermissionsProvider } from '../../contexts/PermissionsContext'
import useNotificationsSocket from '../../hooks/useNotificationsSocket'
import useNotificationClickHandler from '../../hooks/useNotificationClickHandler'
import { useWorkspaceSync } from '../../hooks/useWorkspaceSync'
import * as R from '../../constants/Routes'

export default function AppLayout() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const isAuthenticated = useSelector((s) => s.auth.isAuthenticated)
  const syncNotice = useSelector((s) => s.workspace.syncNotice)

  // Sidebar starts open on desktop, closed on small screens (drawer style).
  const [sidebarOpen, setSidebarOpen] = useState(
    () => (typeof window === 'undefined' ? true : window.innerWidth >= 768),
  )
  const toggleSidebar = () => setSidebarOpen((o) => !o)

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
  useWorkspaceSync()

  return (
    <PermissionsProvider>
      <div className="flex h-screen overflow-hidden bg-base">
        {/* Mobile backdrop when the drawer is open */}
        {sidebarOpen && (
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 bg-black/30 z-30 md:hidden"
          />
        )}
        {/* Sidebar: off-canvas drawer under md, collapsible column at md+ */}
        <div
          className={`z-40 h-full shrink-0 fixed md:static inset-y-0 left-0 transition-[width,transform] duration-200 ease-in-out ${
            sidebarOpen
              ? 'translate-x-0 w-[260px]'
              : '-translate-x-full w-[260px] md:translate-x-0 md:w-0 md:overflow-hidden'
          }`}
        >
          <Sidebar onNavigate={() => { if (window.innerWidth < 768) setSidebarOpen(false) }} />
        </div>
        <main className="flex-1 flex flex-col min-w-0 bg-surface-1">
          <Outlet context={{ sidebarOpen, toggleSidebar }} />
        </main>
      </div>
      <Snackbar
        open={Boolean(syncNotice)}
        autoHideDuration={5000}
        onClose={() => dispatch(clearSyncNotice())}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity="info" variant="filled" onClose={() => dispatch(clearSyncNotice())}>
          {syncNotice}
        </Alert>
      </Snackbar>
    </PermissionsProvider>
  )
}
