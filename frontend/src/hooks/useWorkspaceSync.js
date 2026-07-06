import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { onWorkspaceSync, reconnectSocket } from '../services/socket'
import {
  refreshWorkspaces,
  workspaceRemoved,
  loadDms,
  bumpMembersVersion,
  bumpPermissionsVersion,
  setSyncNotice,
} from '../store/workspaceSlice'

// Applies realtime `workspace_sync` events (emitted by the backend when another
// user changes membership, channels, DMs or permissions) to local state so the
// UI stays consistent without a manual refresh. Reconnecting the socket lets the
// server re-compute which channel rooms this client belongs to.
export function useWorkspaceSync() {
  const dispatch = useDispatch()
  const activeWorkspaceId = useSelector((s) => s.workspace.activeWorkspaceId)

  useEffect(() => {
    const off = onWorkspaceSync((payload) => {
      if (!payload || typeof payload !== 'object') return
      const { resource, workspace_id: wsId, action, name } = payload

      switch (resource) {
        case 'workspaces':
          if (action === 'removed') {
            dispatch(setSyncNotice(name ? `You were removed from ${name}` : 'You were removed from a workspace'))
            dispatch(workspaceRemoved(wsId))
            reconnectSocket()
          } else if (action === 'left') {
            // Self-initiated on another device/tab — sync silently.
            dispatch(workspaceRemoved(wsId))
            reconnectSocket()
          } else if (action === 'added') {
            dispatch(setSyncNotice(name ? `You were added to ${name}` : 'You were added to a workspace'))
            dispatch(refreshWorkspaces()).finally(() => reconnectSocket())
          }
          break
        case 'channels':
          dispatch(refreshWorkspaces()).finally(() => reconnectSocket())
          break
        case 'dms':
          if (wsId === activeWorkspaceId) dispatch(loadDms(activeWorkspaceId))
          break
        case 'members':
          dispatch(bumpMembersVersion())
          break
        case 'permissions':
          dispatch(bumpPermissionsVersion())
          dispatch(refreshWorkspaces()).finally(() => reconnectSocket())
          break
        default:
          break
      }
    })
    return off
  }, [dispatch, activeWorkspaceId])
}
