import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { useSelector } from 'react-redux'
import { permissionsService } from '../services/permissions'

const PermissionsContext = createContext({
  hasPerm: () => true,
  hasChannelPerm: () => true,
  isOwner: false,
  permissionsLoaded: false,
  channelPermsLoaded: false,
})

export function PermissionsProvider({ children }) {
  const { activeWorkspaceId, workspaces } = useSelector((s) => s.workspace)
  const activeChatroomId = useSelector((s) => s.workspace.activeChatroomId)
  const permissionsVersion = useSelector((s) => s.workspace.permissionsVersion)
  const user = useSelector((s) => s.auth.user)

  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId)
  const isOwner = Boolean(activeWorkspace && user && activeWorkspace.owner_id === user.id)

  const [workspacePerms, setWorkspacePerms] = useState([])
  const [channelPerms, setChannelPerms] = useState([])
  const [permissionsLoaded, setPermissionsLoaded] = useState(false)
  const [channelPermsLoaded, setChannelPermsLoaded] = useState(false)

  useEffect(() => {
    if (!activeWorkspaceId) {
      setWorkspacePerms([])
      setPermissionsLoaded(false)
      return
    }
    if (isOwner) {
      setWorkspacePerms([])
      setPermissionsLoaded(true)
      return
    }
    let cancelled = false
    setPermissionsLoaded(false)
    permissionsService
      .myPermissions(activeWorkspaceId)
      .then((perms) => {
        if (!cancelled) setWorkspacePerms(Array.isArray(perms) ? perms : [])
      })
      .catch(() => {
        if (!cancelled) setWorkspacePerms([])
      })
      .finally(() => {
        if (!cancelled) setPermissionsLoaded(true)
      })
    return () => { cancelled = true }
  }, [activeWorkspaceId, isOwner, permissionsVersion])

  useEffect(() => {
    if (!activeChatroomId) {
      setChannelPerms([])
      setChannelPermsLoaded(false)
      return
    }
    if (isOwner) {
      setChannelPerms([])
      setChannelPermsLoaded(true)
      return
    }
    let cancelled = false
    setChannelPermsLoaded(false)
    permissionsService
      .myChannelPermissions(activeChatroomId)
      .then((perms) => {
        if (!cancelled) setChannelPerms(Array.isArray(perms) ? perms : [])
      })
      .catch(() => {
        if (!cancelled) setChannelPerms([])
      })
      .finally(() => {
        if (!cancelled) setChannelPermsLoaded(true)
      })
    return () => { cancelled = true }
  }, [activeChatroomId, isOwner, permissionsVersion])

  const hasPerm = useCallback(
    (resource, action) => {
      if (isOwner) return true
      return workspacePerms.some((p) => p.resource === resource && p.action === action)
    },
    [isOwner, workspacePerms],
  )

  const hasChannelPerm = useCallback(
    (resource, action) => {
      if (isOwner) return true
      return channelPerms.some((p) => p.resource === resource && p.action === action)
    },
    [isOwner, channelPerms],
  )

  return (
    <PermissionsContext.Provider
      value={{ hasPerm, hasChannelPerm, isOwner, permissionsLoaded, channelPermsLoaded }}
    >
      {children}
    </PermissionsContext.Provider>
  )
}

export function usePermissions() {
  return useContext(PermissionsContext)
}
