import { useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import Sidebar from './Sidebar'
import { bootstrapWorkspaces } from '../../store/workspaceSlice'

export default function AppLayout() {
  const dispatch = useDispatch()
  const isAuthenticated = useSelector((s) => s.auth.isAuthenticated)

  useEffect(() => {
    if (isAuthenticated) dispatch(bootstrapWorkspaces())
  }, [dispatch, isAuthenticated])

  return (
    <div className="flex h-screen overflow-hidden bg-base">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0 bg-surface-1">
        <Outlet />
      </main>
    </div>
  )
}
