import { useState, useEffect, useCallback } from 'react'
import { useSelector } from 'react-redux'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import { ShieldCheck } from 'lucide-react'
import { permissionsService } from '../../services/permissions'
import { chatService } from '../../services/chat'
import RoleList from './RoleList'
import RoleDetail from './RoleDetail'

const SCOPE_LABEL = { 0: 'any', 1: 'own' }

export default function PermissionsManager() {
  const { activeWorkspaceId, workspaces, chatrooms } = useSelector((s) => s.workspace)
  const user = useSelector((s) => s.auth.user)
  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId) || null
  const isOwner = Boolean(activeWorkspace && user && activeWorkspace.owner_id === user.id)

  const [canView, setCanView] = useState(false)
  const [canManage, setCanManage] = useState(false)
  const [roles, setRoles] = useState([])
  const [selectedRoleId, setSelectedRoleId] = useState(null)
  const [roleDetail, setRoleDetail] = useState(null)
  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')

  const [perms, setPerms] = useState([])
  const [permsLoading, setPermsLoading] = useState(false)
  const [permsError, setPermsError] = useState('')

  const loadRoles = useCallback(async () => {
    if (!activeWorkspaceId) return []
    try {
      const list = await permissionsService.getRoles(activeWorkspaceId)
      const arr = Array.isArray(list) ? list : []
      setRoles(arr)
      return arr
    } catch (err) {
      setError(err?.detail || 'Could not load roles')
      return []
    }
  }, [activeWorkspaceId])

  const loadRoleDetail = useCallback(async (roleId) => {
    if (!activeWorkspaceId || !roleId) { setRoleDetail(null); return }
    setDetailLoading(true)
    try {
      const detail = await permissionsService.getRole(activeWorkspaceId, roleId)
      setRoleDetail(detail)
    } catch (err) {
      setError(err?.detail || 'Could not load role details')
    } finally {
      setDetailLoading(false)
    }
  }, [activeWorkspaceId])

  const loadMembers = useCallback(async () => {
    if (!activeWorkspaceId) return
    try {
      const list = await chatService.getMembers(activeWorkspaceId)
      setMembers(Array.isArray(list) ? list : [])
    } catch { /* ignore */ }
  }, [activeWorkspaceId])

  useEffect(() => {
    setCanView(false)
    setCanManage(false)
    setSelectedRoleId(null)
    setRoleDetail(null)
    setRoles([])
  }, [activeWorkspaceId])

  useEffect(() => {
    if (!activeWorkspaceId) { setLoading(false); return }
    const init = async () => {
      setLoading(true)
      setError('')
      setPermsError('')
      if (isOwner) {
        setCanView(true)
        setCanManage(true)
      } else {
        try {
          const myPerms = await permissionsService.myPermissions(activeWorkspaceId)
          const permsList = Array.isArray(myPerms) ? myPerms : []
          const hasView = permsList.some(
            (p) => p.resource === 'workspace.role' && p.action === 'view',
          )
          const hasManage = permsList.some(
            (p) => p.resource === 'workspace.role' && p.action === 'manage',
          )
          setCanView(hasView)
          setCanManage(hasManage)
          if (!hasManage) setPerms(permsList)
        } catch {
          setCanView(false)
          setCanManage(false)
        }
      }
      setLoading(false)
    }
    init()
  }, [activeWorkspaceId, isOwner])

  useEffect(() => {
    if (!activeWorkspaceId || loading) return
    if (canManage) {
      Promise.all([loadRoles(), loadMembers()]).then(([roleList]) => {
        if (roleList?.length && !selectedRoleId) setSelectedRoleId(roleList[0].id)
      })
    }
  }, [activeWorkspaceId, canManage, loading, loadRoles, loadMembers])

  useEffect(() => {
    if (canManage && selectedRoleId) loadRoleDetail(selectedRoleId)
  }, [canManage, selectedRoleId, loadRoleDetail])

  const handleCreateRole = async (name, priority, description) => {
    const role = await permissionsService.createRole(activeWorkspaceId, { name, priority, description })
    await loadRoles()
    setSelectedRoleId(role.id)
  }

  const handleDeleteRole = async () => {
    if (!selectedRoleId || selectedRoleId === activeWorkspaceId) return
    try {
      await permissionsService.deleteRole(activeWorkspaceId, selectedRoleId)
    } catch (err) {
      setError(err?.detail || 'Failed to delete role')
      throw err
    }
    setSelectedRoleId(null)
    setRoleDetail(null)
    const remaining = await loadRoles()
    if (remaining.length) setSelectedRoleId(remaining[0].id)
  }

  if (!activeWorkspaceId) {
    return <Alert severity="info">Create or select a workspace to view your access.</Alert>
  }

  if (loading) {
    return <div className="flex justify-center py-10"><CircularProgress size={22} /></div>
  }

  if (!canView) {
    return (
      <p className="text-[13px] text-ink-tertiary py-4">
        You don't have permission to view roles in this workspace.
      </p>
    )
  }

  if (!canManage) {
    return (
      <>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-[15px] font-semibold text-ink">Access &amp; roles</h3>
        </div>
        <p className="text-[13px] text-ink-secondary mb-4">
          Your effective permissions{activeWorkspace?.name ? ` in ${activeWorkspace.name}` : ''}.
          These are enforced server-side on every request.
        </p>
        {permsLoading ? (
          <div className="flex justify-center py-10"><CircularProgress size={22} /></div>
        ) : permsError ? (
          <Alert severity="error">{permsError}</Alert>
        ) : perms.length === 0 ? (
          <p className="text-[13px] text-ink-tertiary">No permissions granted in this workspace.</p>
        ) : (
          <div className="border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden">
            {perms.map((p, i) => (
              <div
                key={`${p.resource}:${p.action}:${p.scope}`}
                className={`flex items-center gap-3 p-3 px-4 ${i < perms.length - 1 ? 'border-b border-[rgba(28,27,26,0.06)]' : ''}`}
              >
                <div className="w-8 h-8 rounded-md bg-amber-subtle flex items-center justify-center text-amber shrink-0">
                  <ShieldCheck size={16} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink font-mono">{p.resource}:{p.action}</p>
                </div>
                <Chip label={SCOPE_LABEL[p.scope] || String(p.scope)} size="small" variant="outlined" />
              </div>
            ))}
          </div>
        )}
      </>
    )
  }

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-[15px] font-semibold text-ink">Roles &amp; permissions</h3>
          <p className="text-[13px] text-ink-secondary">
            Manage roles and permissions{activeWorkspace?.name ? ` for ${activeWorkspace.name}` : ''}
          </p>
        </div>
        {isOwner && (
          <Chip label="Owner" size="small" sx={{ color: 'var(--amber)', bgcolor: 'rgba(196,145,58,0.10)', fontWeight: 600 }} />
        )}
      </div>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      <div className="flex flex-col md:flex-row gap-4 md:min-h-[400px]">
        <RoleList
          roles={roles}
          selectedRoleId={selectedRoleId}
          baseRoleId={activeWorkspaceId}
          onSelect={setSelectedRoleId}
          onCreate={handleCreateRole}
        />
        <div className="flex-1 min-w-0">
          <RoleDetail
            role={roleDetail}
            loading={detailLoading}
            isBase={roleDetail?.id === activeWorkspaceId}
            workspaceId={activeWorkspaceId}
            members={members}
            chatrooms={chatrooms}
            onRefresh={() => loadRoleDetail(selectedRoleId)}
            onDelete={handleDeleteRole}
            onError={setError}
          />
        </div>
      </div>
    </>
  )
}
