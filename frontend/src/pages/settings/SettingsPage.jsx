import { useState, useEffect, useCallback, useRef } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import Tabs from '@mui/material/Tabs'
import Tab from '@mui/material/Tab'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Avatar from '@mui/material/Avatar'
import Switch from '@mui/material/Switch'
import Chip from '@mui/material/Chip'
import Snackbar from '@mui/material/Snackbar'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import { KeyRound, Trash2, Hash, Pencil, AlertTriangle, LogOut, Camera } from 'lucide-react'
import {
  changePassword,
  deleteAccount,
  revokeSession,
  revokeAllSessions,
  clearSettingsError,
  listSessions,
  setupTotp,
  registerTotp,
  disableTotp,
  clearTotpSetup,
  registerPasskey,
  clearPasskeyError,
  listPasskeys,
  deletePasskey,
  updateAvatar,
  removeAvatar,
} from '../../store/authSlice'
import { authService } from '../../services/auth'
import { chatService } from '../../services/chat'
import { permissionsService } from '../../services/permissions'
import PermissionsManager from '../../components/settings/PermissionsManager'
import ChannelSettingsDialog from '../../components/settings/ChannelSettingsDialog'
import MemberSearchAutocomplete from '../../components/workspace/MemberSearchAutocomplete'
import NotificationsSettingsTab from './NotificationsSettingsTab'
import SidebarToggle from '../../components/layout/SidebarToggle'
import { getDevMode, setDevMode } from '../../utils/devMode'

function TabPanel({ value, index: key, children }) {
  if (value !== key) return null
  return <div>{children}</div>
}

const CONNECTABLE_PROVIDERS = [
  { key: 'google', label: 'Google', glyph: 'G' },
  { key: 'github', label: 'GitHub', glyph: 'GH' },
]

function providerLabel(key) {
  return CONNECTABLE_PROVIDERS.find((p) => p.key === key)?.label || key
}

function initialsOf(name) {
  return (name || '?')
    .split(' ')
    .map((n) => n[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

// Turn a raw User-Agent into a friendly "Browser on OS" label.
function deviceLabel(ua) {
  if (!ua) return 'Unknown device'
  if (/iPhone/i.test(ua)) return 'iPhone'
  if (/iPad/i.test(ua)) return 'iPad'
  if (/Android/i.test(ua)) return 'Android device'
  const os = /Windows/i.test(ua) ? 'Windows'
    : /Mac OS X|Macintosh/i.test(ua) ? 'macOS'
    : /CrOS/i.test(ua) ? 'ChromeOS'
    : /Linux/i.test(ua) ? 'Linux' : 'device'
  const browser = /Edg\//i.test(ua) ? 'Edge'
    : /OPR\/|Opera/i.test(ua) ? 'Opera'
    : /Chrome\//i.test(ua) ? 'Chrome'
    : /Firefox\//i.test(ua) ? 'Firefox'
    : /Safari\//i.test(ua) ? 'Safari' : 'Browser'
  return `${browser} on ${os}`
}

function describeSession(s) {
  const last = s.last_used_at ? new Date(s.last_used_at).toLocaleString() : 'Unknown'
  return { device: deviceLabel(s.user_agent), location: `Last active ${last}` }
}

// Collapse many logins from the same device into one entry that carries a
// sign-in history, instead of showing every login as a separate "device".
function groupSessions(sessions) {
  const groups = new Map()
  for (const s of sessions) {
    const key = s.user_agent || 'unknown'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(s)
  }
  const out = []
  for (const [key, list] of groups) {
    const logins = [...list].sort(
      (a, b) => new Date(b.created_at || b.last_used_at) - new Date(a.created_at || a.last_used_at),
    )
    const lastActive = list.reduce(
      (mx, s) => Math.max(mx, new Date(s.last_used_at || s.created_at || 0).getTime()), 0,
    )
    out.push({
      key,
      device: deviceLabel(key === 'unknown' ? null : key),
      current: list.some((s) => s.current),
      lastActive,
      logins,
      revocableIds: list.filter((s) => !s.current).map((s) => s.id),
    })
  }
  return out.sort((a, b) => (b.current ? 1 : 0) - (a.current ? 1 : 0) || b.lastActive - a.lastActive)
}

function describePasskey(p) {
  const kind = p.backed_up || p.device_type === 'multi_device' ? 'Synced passkey' : 'This device'
  const added = p.created_at ? new Date(p.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : null
  return added ? `${kind} · Added ${added}` : kind
}

// Softer, greyer labels/placeholders for password fields so the hints read as
// hints, not primary text.
const mutedFieldSx = {
  '& .MuiInputLabel-root': { color: 'rgba(28,27,26,0.45)' },
  '& .MuiInputBase-input::placeholder': { color: 'rgba(28,27,26,0.38)', opacity: 1 },
}

export default function SettingsPage() {
  const dispatch = useDispatch()
  const {
    user,
    settingsLoading,
    settingsError,
    sessions,
    sessionsLoading,
    totpSetup,
    totpError,
    passkeyLoading,
    passkeyError,
    passkeys,
    passkeysLoading,
  } = useSelector((s) => s.auth)

  const [tab, setTab] = useState(0)
  const [snackbar, setSnackbar] = useState({ open: false, message: '' })
  const showSnackbar = (message) => setSnackbar({ open: true, message })

  const [loadSessionsOpen, setLoadSessionsOpen] = useState(false)
  const [loadSessionsPassword, setLoadSessionsPassword] = useState('')
  const [revokeDialog, setRevokeDialog] = useState({ open: false, sessionIds: [], device: '' })
  const [expandedDevice, setExpandedDevice] = useState(null)
  const [revokePassword, setRevokePassword] = useState('')
  const [revokeAllDialog, setRevokeAllDialog] = useState(false)
  const [revokeAllPassword, setRevokeAllPassword] = useState('')
  const [sessionDetail, setSessionDetail] = useState(null)
  const [sessionDetailLoading, setSessionDetailLoading] = useState(false)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const { activeWorkspaceId, workspaces, membersVersion } = useSelector((s) => s.workspace)
  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId) || null
  // Latest active workspace, so async loads can discard responses that arrive
  // after the user has switched workspaces (otherwise stale members / owner
  // labels from the previous workspace bleed into the new one).
  const wsRef = useRef(activeWorkspaceId)
  wsRef.current = activeWorkspaceId
  const isOwner = Boolean(activeWorkspace && user && activeWorkspace.owner_id === user.id)

  const [members, setMembers] = useState([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteSubmitting, setInviteSubmitting] = useState(false)
  const [inviteError, setInviteError] = useState('')
  const [removingId, setRemovingId] = useState(null)
  const [showAccessTab, setShowAccessTab] = useState(false)
  const [memberRolesMap, setMemberRolesMap] = useState({})

  const [channels, setChannels] = useState([])
  const [channelsLoading, setChannelsLoading] = useState(false)
  const [channelEditOpen, setChannelEditOpen] = useState(false)
  const [channelEditTarget, setChannelEditTarget] = useState(null)
  const [deleteChannelDialog, setDeleteChannelDialog] = useState(false)
  const [deleteChannelTarget, setDeleteChannelTarget] = useState(null)
  const [deletingChannel, setDeletingChannel] = useState(false)

  const [twoFaOn, setTwoFaOn] = useState(false)
  const [totpDialogOpen, setTotpDialogOpen] = useState(false)
  const [totpPassword, setTotpPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [sudoForSetup, setSudoForSetup] = useState(false)

  const [passkeyDialogOpen, setPasskeyDialogOpen] = useState(false)
  const [passkeyName, setPasskeyName] = useState('')
  const [passkeyPassword, setPasskeyPassword] = useState('')
  const [removePasskey, setRemovePasskey] = useState({ open: false, id: null, name: '' })
  const [removePasskeyPassword, setRemovePasskeyPassword] = useState('')
  const avatarInputRef = useRef(null)
  const [avatarUploading, setAvatarUploading] = useState(false)

  const [connections, setConnections] = useState({})
  const [connectingProvider, setConnectingProvider] = useState(null)
  const [focusConnections, setFocusConnections] = useState(false)

  const [wsName, setWsName] = useState('')
  const [wsDescription, setWsDescription] = useState('')
  const [wsSettingsLoading, setWsSettingsLoading] = useState(false)
  const [wsSaving, setWsSaving] = useState(false)
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [deleteWsDialogOpen, setDeleteWsDialogOpen] = useState(false)
  const [deleteWsConfirm, setDeleteWsConfirm] = useState('')
  const [deletingWs, setDeletingWs] = useState(false)

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deletePassword, setDeletePassword] = useState('')
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [deleting, setDeleting] = useState(false)

  const getInitials = () => {
    const name = user?.name || user?.username || 'U'
    return name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()
  }

  const loadWorkspaceSettings = useCallback(async () => {
    if (!activeWorkspaceId) return
    const wsId = activeWorkspaceId
    setWsSettingsLoading(true)
    try {
      const ws = await chatService.getWorkspaceSettings(wsId)
      if (wsId !== wsRef.current) return
      setWsName(ws.name || '')
      setWsDescription(ws.description || '')
    } catch {
      if (wsId !== wsRef.current) return
      // fallback to what we already have
      setWsName(activeWorkspace?.name || '')
      setWsDescription('')
    } finally {
      if (wsId === wsRef.current) setWsSettingsLoading(false)
    }
  }, [activeWorkspaceId, activeWorkspace?.name])

  const handleSaveWorkspace = async () => {
    if (!activeWorkspaceId) return
    setWsSaving(true)
    try {
      const updates = []
      if (wsName.trim() && wsName.trim() !== activeWorkspace?.name) {
        updates.push(chatService.renameWorkspace(activeWorkspaceId, wsName.trim()))
      }
      if (wsDescription !== (activeWorkspace?.description || '')) {
        updates.push(chatService.updateWorkspaceDescription(activeWorkspaceId, wsDescription))
      }
      if (updates.length) {
        await Promise.all(updates)
        showSnackbar('Workspace updated')
      }
    } catch (err) {
      showSnackbar(err?.detail || 'Failed to update workspace')
    } finally {
      setWsSaving(false)
    }
  }

  const handleLeaveWorkspace = async () => {
    if (!activeWorkspaceId) return
    setLeaving(true)
    try {
      await chatService.leaveWorkspace(activeWorkspaceId)
      setLeaveDialogOpen(false)
      showSnackbar('You left the workspace')
      window.location.reload()
    } catch (err) {
      showSnackbar(err?.detail || 'Failed to leave workspace')
    } finally {
      setLeaving(false)
    }
  }

  const handleDeleteWorkspace = async () => {
    if (!activeWorkspaceId) return
    setDeletingWs(true)
    try {
      await chatService.deleteWorkspace(activeWorkspaceId)
      setDeleteWsDialogOpen(false)
      showSnackbar('Workspace deleted')
      window.location.reload()
    } catch (err) {
      showSnackbar(err?.detail || 'Failed to delete workspace')
    } finally {
      setDeletingWs(false)
    }
  }

  const loadChannels = useCallback(async () => {
    const wsId = activeWorkspaceId
    if (!wsId) { setChannels([]); return }
    setChannelsLoading(true)
    try {
      const list = await chatService.listChannels(wsId)
      if (wsId !== wsRef.current) return
      setChannels(Array.isArray(list) ? list : [])
    } catch (err) {
      if (wsId === wsRef.current) showSnackbar(err?.detail || 'Could not load channels')
    } finally {
      if (wsId === wsRef.current) setChannelsLoading(false)
    }
  }, [activeWorkspaceId])



  const handleDeleteChannel = async () => {
    if (!deleteChannelTarget || !activeWorkspaceId) return
    setDeletingChannel(true)
    try {
      await chatService.deleteChannel(activeWorkspaceId, deleteChannelTarget.id)
      setDeleteChannelDialog(false)
      setDeleteChannelTarget(null)
      showSnackbar('Channel deleted')
      loadChannels()
    } catch (err) {
      showSnackbar(err?.detail || 'Failed to delete channel')
    } finally {
      setDeletingChannel(false)
    }
  }

  const loadMembers = useCallback(async () => {
    const wsId = activeWorkspaceId
    if (!wsId) {
      setMembers([])
      return
    }
    setMembersLoading(true)
    try {
      const list = await chatService.getMembers(wsId)
      if (wsId !== wsRef.current) return
      setMembers(Array.isArray(list) ? list : [])
    } catch (err) {
      if (wsId === wsRef.current) showSnackbar(err?.detail || 'Could not load members')
    } finally {
      if (wsId === wsRef.current) setMembersLoading(false)
    }
  }, [activeWorkspaceId])

  useEffect(() => {
    if (isOwner) { setShowAccessTab(true); return }
    if (!activeWorkspaceId) { setShowAccessTab(false); return }
    const wsId = activeWorkspaceId
    permissionsService.myPermissions(wsId).then((perms) => {
      if (wsId !== wsRef.current) return
      const list = Array.isArray(perms) ? perms : []
      setShowAccessTab(list.some((p) => p.resource === 'workspace.role' && p.action === 'view'))
    }).catch(() => { if (wsId === wsRef.current) setShowAccessTab(false) })
  }, [activeWorkspaceId, isOwner])

  const [devMode, setDevModeState] = useState(getDevMode)

  const tabs = [
    { label: 'Profile', key: 'profile' },
    { label: 'Workspace', key: 'workspace' },
    ...(showAccessTab ? [{ label: 'Access', key: 'access' }] : []),
    { label: 'Security', key: 'security' },
    { label: 'Notifications', key: 'notifications' },
    { label: 'Advanced', key: 'advanced' },
  ]
  const safeTab = tab < tabs.length ? tab : 0
  const activeKey = tabs[safeTab]?.key || 'profile'

  const loadConnections = useCallback(async () => {
    try {
      const res = await authService.getConnections()
      setConnections(res && typeof res === 'object' ? res : {})
    } catch {
      // non-fatal — leave whatever we had
    }
  }, [])

  useEffect(() => {
    loadConnections()
  }, [loadConnections])

  useEffect(() => {
    dispatch(listPasskeys())
  }, [dispatch])

  // Surface the outcome of returning from a "Connect" OAuth redirect.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const connected = params.get('connected')
    const connectError = params.get('connect_error')
    if (!connected && !connectError) return
    if (connected) {
      showSnackbar(`${providerLabel(connected)} connected`)
      loadConnections()
    } else {
      showSnackbar(`${providerLabel(connectError)} is already linked to another account`)
    }
    setFocusConnections(true)
    params.delete('connected')
    params.delete('connect_error')
    const qs = params.toString()
    window.history.replaceState({}, '', window.location.pathname + (qs ? `?${qs}` : ''))
  }, [loadConnections])

  // Jump to the Security tab (where connected accounts live) after a connect.
  useEffect(() => {
    if (!focusConnections) return
    const idx = tabs.findIndex((t) => t.key === 'security')
    if (idx >= 0) {
      setTab(idx)
      setFocusConnections(false)
    }
  }, [focusConnections, tabs])

  const handleConnectProvider = async (provider) => {
    setConnectingProvider(provider)
    try {
      await authService.connectProvider(provider)
      // navigates away on success; nothing further to do here
    } catch (err) {
      setConnectingProvider(null)
      showSnackbar(err?.detail || `Could not connect ${providerLabel(provider)}`)
    }
  }

  const loadMemberRoles = useCallback(async () => {
    const wsId = activeWorkspaceId
    if (!wsId) return
    try {
      const roles = await permissionsService.getRoles(wsId)
      const details = await Promise.all(
        (Array.isArray(roles) ? roles : []).map((r) =>
          permissionsService.getRole(wsId, r.id),
        ),
      )
      if (wsId !== wsRef.current) return
      const map = {}
      for (const role of details) {
        if (!role.users) continue
        for (const userId of role.users) {
          if (!map[userId]) map[userId] = []
          map[userId].push(role.name)
        }
      }
      setMemberRolesMap(map)
    } catch {
      // roles info is supplementary — ignore errors (e.g. no permission)
    }
  }, [activeWorkspaceId])

  // Wipe per-workspace lists the instant the active workspace changes, so the
  // previous workspace's members / owner labels can't flash before the reload.
  useEffect(() => {
    setMembers([])
    setChannels([])
    setMemberRolesMap({})
  }, [activeWorkspaceId])

  useEffect(() => {
    if (tab === 1) {
      loadWorkspaceSettings()
      loadMembers()
      loadMemberRoles()
      loadChannels()
    }
  }, [tab, loadWorkspaceSettings, loadMembers, loadMemberRoles, loadChannels, membersVersion])

  const handleAddMemberFromSearch = async (u) => {
    if (!activeWorkspaceId) return
    setInviteSubmitting(true)
    setInviteError('')
    try {
      await chatService.addMember(activeWorkspaceId, u.username)
      await loadMembers()
      showSnackbar(`Added ${u.name || u.username}`)
    } catch (err) {
      setInviteError(err?.detail || `Could not add ${u.username}`)
    } finally {
      setInviteSubmitting(false)
    }
  }

  const handleRemoveMember = async (memberId) => {
    if (!activeWorkspaceId) return
    setRemovingId(memberId)
    try {
      await chatService.removeMember(activeWorkspaceId, memberId)
      showSnackbar('Member removed')
      setMembers((prev) => prev.filter((m) => m.id !== memberId))
    } catch (err) {
      showSnackbar(err?.detail || 'Could not remove member')
    } finally {
      setRemovingId(null)
    }
  }

  const handleLoadSessions = async (password) => {
    const result = await dispatch(listSessions({ password }))
    if (listSessions.fulfilled.match(result)) {
      setLoadSessionsOpen(false)
      setLoadSessionsPassword('')
      showSnackbar(`Loaded ${result.payload.length} session(s)`)
    }
  }

  const openLoadSessions = () => {
    // Already loaded → refresh silently (no re-prompt needed within the session).
    setLoadSessionsPassword('')
    dispatch(clearSettingsError())
    setLoadSessionsOpen(true)
  }

  const handleRevokeDevice = (group) => {
    setRevokeDialog({ open: true, sessionIds: group.revocableIds, device: group.device })
    setRevokePassword('')
    dispatch(clearSettingsError())
  }

  const handleRevokeConfirm = async () => {
    let ok = true
    for (const id of revokeDialog.sessionIds) {
      const result = await dispatch(revokeSession({ sessionId: id, password: revokePassword }))
      if (!revokeSession.fulfilled.match(result)) { ok = false; break }
    }
    if (ok) {
      setRevokeDialog({ open: false, sessionIds: [], device: '' })
      setRevokePassword('')
      showSnackbar('Signed out of that device')
    }
  }

  const handleRevokeAllConfirm = async () => {
    const result = await dispatch(revokeAllSessions({ password: revokeAllPassword }))
    if (revokeAllSessions.fulfilled.match(result)) {
      setRevokeAllDialog(false)
      setRevokeAllPassword('')
      showSnackbar('Signed out of all other devices')
    }
  }

  const handleViewSession = async (id) => {
    setSessionDetailLoading(true)
    try {
      const detail = await authService.getSession(id)
      setSessionDetail(detail)
    } catch (err) {
      showSnackbar(err.detail || 'Failed to load session details')
    } finally {
      setSessionDetailLoading(false)
    }
  }

  const handleChangePassword = async () => {
    if (newPassword !== confirmPassword) {
      showSnackbar('Passwords do not match')
      return
    }
    if (newPassword.length < 12) {
      showSnackbar('New password must be at least 12 characters')
      return
    }
    const result = await dispatch(changePassword({ currentPassword, newPassword }))
    if (changePassword.fulfilled.match(result)) {
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      showSnackbar('Password updated successfully')
    }
  }

  const handleTwoFaToggle = async (nextEnabled) => {
    if (nextEnabled) {
      setTotpDialogOpen(true)
      setSudoForSetup(true)
      dispatch(clearTotpSetup())
    } else {
      const result = await dispatch(disableTotp())
      if (disableTotp.fulfilled.match(result)) {
        setTwoFaOn(false)
        showSnackbar('Two-factor authentication disabled')
      } else {
        showSnackbar(result.payload || 'Failed to disable TOTP')
      }
    }
  }

  const handleStartTotpSetup = async () => {
    try {
      await authService.sudo(totpPassword)
    } catch {
      showSnackbar('Invalid password')
      return
    }
    setSudoForSetup(false)
    const result = await dispatch(setupTotp())
    if (!setupTotp.fulfilled.match(result)) {
      showSnackbar(result.payload || 'Failed to start TOTP setup')
    }
  }

  const handleConfirmTotp = async () => {
    if (!totpSetup) return
    const result = await dispatch(
      registerTotp({ otp: totpCode, jwt_totp_claims: totpSetup.jwt_totp })
    )
    if (registerTotp.fulfilled.match(result)) {
      setTwoFaOn(true)
      setTotpDialogOpen(false)
      setTotpCode('')
      setTotpPassword('')
      showSnackbar('Two-factor authentication enabled')
    }
  }

  const handleCloseTotpDialog = () => {
    setTotpDialogOpen(false)
    setTotpCode('')
    setTotpPassword('')
    setSudoForSetup(false)
    dispatch(clearTotpSetup())
  }

  const handleDeleteAccount = async () => {
    setDeleting(true)
    dispatch(clearSettingsError())
    const result = await dispatch(deleteAccount({ password: deletePassword }))
    setDeleting(false)
    if (deleteAccount.fulfilled.match(result)) {
      setDeleteDialogOpen(false)
    }
  }

  const handleAddPasskey = async () => {
    dispatch(clearPasskeyError())
    const result = await dispatch(
      registerPasskey({ name: passkeyName || 'My passkey', password: passkeyPassword })
    )
    if (registerPasskey.fulfilled.match(result)) {
      setPasskeyDialogOpen(false)
      setPasskeyName('')
      setPasskeyPassword('')
      showSnackbar('Passkey registered successfully')
      dispatch(listPasskeys())
    }
  }

  const handleAvatarPick = (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) { showSnackbar('Please choose an image file'); return }
    if (file.size > 8 * 1024 * 1024) { showSnackbar('Image is too large (8 MB max)'); return }
    handleAvatarUpload(file)
  }

  const handleAvatarUpload = async (file) => {
    setAvatarUploading(true)
    const result = await dispatch(updateAvatar(file))
    setAvatarUploading(false)
    showSnackbar(updateAvatar.fulfilled.match(result) ? 'Profile photo updated' : (result.payload || 'Failed to upload photo'))
  }

  const handleAvatarRemove = async () => {
    const result = await dispatch(removeAvatar())
    if (removeAvatar.fulfilled.match(result)) showSnackbar('Profile photo removed')
  }

  const handleRemovePasskey = async () => {
    dispatch(clearPasskeyError())
    const result = await dispatch(
      deletePasskey({ passkeyId: removePasskey.id, password: removePasskeyPassword })
    )
    if (deletePasskey.fulfilled.match(result)) {
      setRemovePasskey({ open: false, id: null, name: '' })
      setRemovePasskeyPassword('')
      showSnackbar('Passkey removed')
    }
  }

  return (
    <>
      <header className="h-14 bg-base border-b border-[rgba(28,27,26,0.10)] flex items-center gap-2 px-3 sm:px-6 shrink-0">
        <SidebarToggle />
        <h1 className="text-lg font-semibold text-ink tracking-tight">Settings</h1>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="w-full max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-10 py-8">
          <Tabs value={safeTab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto" allowScrollButtonsMobile sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
            {tabs.map((t) => <Tab key={t.key} label={t.label} />)}
          </Tabs>

          {/* Profile Tab */}
          <TabPanel value={activeKey} index="profile">
            <div className="flex items-center gap-6 mb-8">
              <div className="relative group shrink-0">
                <Avatar
                  src={user?.avatar_url || undefined}
                  sx={{ width: 72, height: 72, bgcolor: 'primary.light', color: 'primary.main', fontSize: 26, fontWeight: 600 }}
                >
                  {getInitials()}
                </Avatar>
                <button
                  type="button"
                  onClick={() => avatarInputRef.current?.click()}
                  disabled={avatarUploading}
                  title="Change photo"
                  className="absolute inset-0 rounded-full flex items-center justify-center bg-black/45 text-white opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-100"
                >
                  {avatarUploading ? <CircularProgress size={18} color="inherit" /> : <Camera size={20} />}
                </button>
                <input ref={avatarInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarPick} />
              </div>
              <div>
                <p className="text-sm font-semibold text-ink">{user?.name || user?.username || '—'}</p>
                <p className="text-xs text-ink-tertiary mb-2">{user?.email || ''}</p>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => avatarInputRef.current?.click()}
                    disabled={avatarUploading}
                    className="text-[13px] font-medium text-amber hover:underline disabled:opacity-50"
                  >
                    {avatarUploading ? 'Uploading…' : user?.avatar_url ? 'Change photo' : 'Upload photo'}
                  </button>
                  {user?.avatar_url && (
                    <button
                      type="button"
                      onClick={handleAvatarRemove}
                      className="text-[13px] font-medium text-ink-tertiary hover:text-ink-secondary"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            </div>

            <h3 className="text-[15px] font-semibold text-ink mb-4">Personal information</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
              <TextField label="Full name" value={user?.name || ''} fullWidth disabled />
              <TextField label="Username" value={user?.username || ''} fullWidth disabled />
              <TextField label="Email" value={user?.email || ''} fullWidth disabled />
            </div>

            <h3 className="text-[15px] font-semibold text-ink mb-4">Change password</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
              <TextField label="Current password" type="password" fullWidth autoComplete="new-password" sx={mutedFieldSx} value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
              <TextField label="New password" type="password" fullWidth autoComplete="new-password" placeholder="Min. 12 characters" sx={mutedFieldSx} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              <TextField label="Confirm new password" type="password" fullWidth autoComplete="new-password" sx={mutedFieldSx} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
            </div>

            {settingsError && (
              <Alert severity="error" sx={{ mb: 2 }} onClose={() => dispatch(clearSettingsError())}>{settingsError}</Alert>
            )}

            <div className="flex justify-end pt-6 border-t border-[rgba(28,27,26,0.06)]">
              <Button
                variant="contained"
                disabled={settingsLoading || !currentPassword || !newPassword}
                startIcon={settingsLoading ? <CircularProgress size={14} color="inherit" /> : null}
                onClick={handleChangePassword}
              >
                Update password
              </Button>
            </div>

            <div className="mt-10">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle size={15} className="text-red-500" />
                <h3 className="text-[15px] font-semibold text-red-600">Danger zone</h3>
              </div>
              <div className="border border-red-200 rounded-xl overflow-hidden">
                <div className="flex items-center justify-between gap-4 px-4 py-4 bg-red-50/40">
                  <div className="flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-red-100 flex items-center justify-center shrink-0 mt-0.5">
                      <Trash2 size={15} className="text-red-500" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-ink">Delete account</p>
                      <p className="text-[12px] text-ink-tertiary mt-0.5 max-w-md">
                        Permanently delete your account and all associated data. This action cannot be undone.
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="outlined"
                    color="error"
                    size="small"
                    sx={{ flexShrink: 0 }}
                    onClick={() => { setDeletePassword(''); setDeleteConfirmText(''); setDeleteDialogOpen(true); dispatch(clearSettingsError()) }}
                  >
                    Delete account
                  </Button>
                </div>
              </div>
            </div>

            <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)} maxWidth="xs" fullWidth>
              <DialogTitle sx={{ color: 'error.main' }}>Delete your account</DialogTitle>
              <DialogContent>
                <Alert severity="warning" sx={{ mb: 3 }}>
                  This will permanently delete your account, remove you from all workspaces, and revoke all sessions. This cannot be undone.
                </Alert>
                {settingsError && (
                  <Alert severity="error" sx={{ mb: 2 }} onClose={() => dispatch(clearSettingsError())}>{settingsError}</Alert>
                )}
                <TextField
                  autoFocus
                  label="Current password"
                  type="password"
                  fullWidth
                  variant="outlined"
                  autoComplete="new-password"
                  value={deletePassword}
                  onChange={(e) => setDeletePassword(e.target.value)}
                  sx={{ mb: 2 }}
                />
                <TextField
                  label='Type "delete my account" to confirm'
                  fullWidth
                  variant="outlined"
                  value={deleteConfirmText}
                  onChange={(e) => setDeleteConfirmText(e.target.value)}
                />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
                <Button
                  variant="contained"
                  color="error"
                  disabled={!deletePassword || deleteConfirmText !== 'delete my account' || deleting}
                  startIcon={deleting ? <CircularProgress size={14} color="inherit" /> : <Trash2 size={14} />}
                  onClick={handleDeleteAccount}
                >
                  Delete permanently
                </Button>
              </DialogActions>
            </Dialog>
          </TabPanel>

          {/* Workspace Tab */}
          <TabPanel value={activeKey} index="workspace">
            {!activeWorkspaceId ? (
              <Alert severity="info">Create or select a workspace to manage its settings.</Alert>
            ) : (
              <>
                {/* Workspace info */}
                <h3 className="text-[15px] font-semibold text-ink mb-4">Workspace settings</h3>
                {wsSettingsLoading ? (
                  <div className="flex justify-center py-6"><CircularProgress size={20} /></div>
                ) : (
                  <div className="mb-8">
                    <div className="grid grid-cols-1 gap-4 mb-4">
                      <TextField
                        label="Workspace name"
                        fullWidth
                        variant="outlined"
                        value={wsName}
                        onChange={(e) => setWsName(e.target.value)}
                      />
                      <TextField
                        label="Description"
                        fullWidth
                        variant="outlined"
                        multiline
                        minRows={2}
                        placeholder="What is this workspace for?"
                        value={wsDescription}
                        onChange={(e) => setWsDescription(e.target.value)}
                      />
                    </div>
                    {isOwner && (
                      <div className="flex justify-end">
                        <Button
                          variant="contained"
                          size="small"
                          disabled={wsSaving || !wsName.trim()}
                          startIcon={wsSaving ? <CircularProgress size={14} color="inherit" /> : null}
                          onClick={handleSaveWorkspace}
                        >
                          Save changes
                        </Button>
                      </div>
                    )}
                  </div>
                )}

                <div className="border-t border-[rgba(28,27,26,0.06)] pt-6 mb-6">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-[15px] font-semibold text-ink">
                      Members{members.length ? ` (${members.length})` : ''}
                    </h3>
                  {isOwner && (
                    <Button variant="contained" size="small" onClick={() => { setInviteError(''); setInviteOpen(true) }}>
                      Add member
                    </Button>
                  )}
                </div>

                {membersLoading && members.length === 0 ? (
                  <div className="flex justify-center py-10"><CircularProgress size={22} /></div>
                ) : members.length === 0 ? (
                  <p className="text-[13px] text-ink-tertiary mb-8">No members yet.</p>
                ) : (
                  <div className="border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden mb-8">
                    {members.map((m, i) => (
                      <div key={m.id} className={`flex items-center p-3 px-4 ${i < members.length - 1 ? 'border-b border-[rgba(28,27,26,0.06)]' : ''}`}>
                        <div className="flex items-center gap-3 flex-1 min-w-0">
                          <Avatar src={m.avatar_url || undefined} sx={{ width: 32, height: 32, fontSize: 12, fontWeight: 600 }}>{initialsOf(m.name)}</Avatar>
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-ink truncate">
                              {m.name}
                              {m.id === user?.id ? <span className="text-ink-tertiary font-normal"> (you)</span> : null}
                            </p>
                            <p className="text-xs text-ink-tertiary truncate">{m.email || `@${m.username}`}</p>
                            {(m.is_owner || memberRolesMap[m.id]?.length > 0) && (
                              <p className="text-xs text-ink-tertiary truncate">
                                {[m.is_owner && 'Owner', ...(memberRolesMap[m.id] || [])].filter(Boolean).join(', ')}
                              </p>
                            )}
                          </div>
                        </div>
                        {isOwner && !m.is_owner && (
                          <Button
                            size="small"
                            color="error"
                            variant="text"
                            disabled={removingId === m.id}
                            startIcon={removingId === m.id ? <CircularProgress size={13} color="inherit" /> : <Trash2 size={14} />}
                            onClick={() => handleRemoveMember(m.id)}
                            sx={{ ml: 1, minWidth: 0 }}
                          >
                            Remove
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {!isOwner && (
                  <p className="text-[12px] text-ink-tertiary">Only the workspace owner can add or remove members.</p>
                )}
                </div>

                <Dialog open={inviteOpen} onClose={() => setInviteOpen(false)} maxWidth="xs" fullWidth>
                  <DialogTitle>Add member</DialogTitle>
                  <DialogContent sx={{ minHeight: 300 }}>
                    <p className="text-sm text-ink-secondary mb-3">
                      Search for an existing account by username or email to add them to this workspace.
                    </p>
                    {inviteError && <Alert severity="error" sx={{ mb: 2 }}>{inviteError}</Alert>}
                    <MemberSearchAutocomplete
                      excludeIds={members.map((m) => m.id)}
                      onSelect={handleAddMemberFromSearch}
                      autoFocus
                    />
                    {inviteSubmitting && (
                      <div className="mt-3 flex items-center gap-2 text-[13px] text-ink-tertiary">
                        <CircularProgress size={14} /> Adding…
                      </div>
                    )}
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={() => setInviteOpen(false)}>Done</Button>
                  </DialogActions>
                </Dialog>

                {/* Channels management — owners only. Non-owners already see the
                    channels they can access in the sidebar, so this adds nothing. */}
                {isOwner && (
                <div className="mt-10 pt-6 border-t border-[rgba(28,27,26,0.06)]">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-[15px] font-semibold text-ink">
                      Channels{channels.length ? ` (${channels.length})` : ''}
                    </h3>
                  </div>

                  {channelsLoading && channels.length === 0 ? (
                    <div className="flex justify-center py-10"><CircularProgress size={22} /></div>
                  ) : channels.length === 0 ? (
                    <p className="text-[13px] text-ink-tertiary mb-4">No channels yet.</p>
                  ) : (
                    <div className="border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden mb-4">
                      {channels.map((ch, i) => (
                        <div key={ch.id} className={`flex items-center p-3 px-4 ${i < channels.length - 1 ? 'border-b border-[rgba(28,27,26,0.06)]' : ''}`}>
                          <div className="flex items-center gap-3 flex-1 min-w-0">
                            <div className="w-8 h-8 rounded-lg bg-surface-1 flex items-center justify-center text-ink-tertiary shrink-0">
                              <Hash size={14} />
                            </div>
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-ink truncate">{ch.name}</p>
                              {ch.description && (
                                <p className="text-xs text-ink-tertiary truncate">{ch.description}</p>
                              )}
                            </div>
                          </div>
                          {isOwner && (
                            <div className="flex items-center gap-0.5">
                              <button
                                className="w-7 h-7 flex items-center justify-center rounded text-ink-tertiary hover:bg-surface-1 hover:text-ink-secondary"
                                onClick={() => { setChannelEditTarget(ch); setChannelEditOpen(true) }}
                              >
                                <Pencil size={13} />
                              </button>
                              <button
                                className="w-7 h-7 flex items-center justify-center rounded text-ink-tertiary hover:bg-red-50 hover:text-red-500"
                                onClick={() => { setDeleteChannelTarget(ch); setDeleteChannelDialog(true) }}
                              >
                                <Trash2 size={13} />
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                )}


                <ChannelSettingsDialog
                  open={channelEditOpen}
                  channel={channelEditTarget}
                  onClose={() => { setChannelEditOpen(false); setChannelEditTarget(null) }}
                  onUpdated={loadChannels}
                />

                <Dialog open={deleteChannelDialog} onClose={() => setDeleteChannelDialog(false)} maxWidth="xs" fullWidth>
                  <DialogTitle sx={{ color: 'error.main' }}>Delete channel</DialogTitle>
                  <DialogContent>
                    <Alert severity="warning" sx={{ mb: 2 }}>
                      This will permanently delete <strong>#{deleteChannelTarget?.name}</strong> and all its messages. This cannot be undone.
                    </Alert>
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={() => setDeleteChannelDialog(false)}>Cancel</Button>
                    <Button
                      variant="contained"
                      color="error"
                      disabled={deletingChannel}
                      startIcon={deletingChannel ? <CircularProgress size={14} color="inherit" /> : <Trash2 size={14} />}
                      onClick={handleDeleteChannel}
                    >
                      Delete permanently
                    </Button>
                  </DialogActions>
                </Dialog>

                {/* Leave / Delete workspace */}
                <div className="mt-10">
                  <div className="flex items-center gap-2 mb-3">
                    <AlertTriangle size={15} className="text-red-500" />
                    <h3 className="text-[15px] font-semibold text-red-600">Danger zone</h3>
                  </div>
                  <div className="border border-red-200 rounded-xl overflow-hidden divide-y divide-red-100">
                    {!isOwner && (
                      <div className="flex items-center justify-between gap-4 px-4 py-4 bg-red-50/40">
                        <div className="flex items-start gap-3">
                          <div className="w-8 h-8 rounded-lg bg-red-100 flex items-center justify-center shrink-0 mt-0.5">
                            <LogOut size={15} className="text-red-500" />
                          </div>
                          <div>
                            <p className="text-sm font-medium text-ink">Leave workspace</p>
                            <p className="text-[12px] text-ink-tertiary mt-0.5 max-w-md">
                              You will lose access to all channels and messages.
                            </p>
                          </div>
                        </div>
                        <Button
                          variant="outlined"
                          color="error"
                          size="small"
                          sx={{ flexShrink: 0 }}
                          onClick={() => setLeaveDialogOpen(true)}
                        >
                          Leave
                        </Button>
                      </div>
                    )}
                    {isOwner && (
                      <div className="flex items-center justify-between gap-4 px-4 py-4 bg-red-50/40">
                        <div className="flex items-start gap-3">
                          <div className="w-8 h-8 rounded-lg bg-red-100 flex items-center justify-center shrink-0 mt-0.5">
                            <Trash2 size={15} className="text-red-500" />
                          </div>
                          <div>
                            <p className="text-sm font-medium text-ink">Delete workspace</p>
                            <p className="text-[12px] text-ink-tertiary mt-0.5 max-w-md">
                              Permanently delete this workspace and all its data.
                            </p>
                          </div>
                        </div>
                        <Button
                          variant="outlined"
                          color="error"
                          size="small"
                          sx={{ flexShrink: 0 }}
                          onClick={() => { setDeleteWsConfirm(''); setDeleteWsDialogOpen(true) }}
                        >
                          Delete
                        </Button>
                      </div>
                    )}
                  </div>
                </div>

                <Dialog open={leaveDialogOpen} onClose={() => setLeaveDialogOpen(false)} maxWidth="xs" fullWidth>
                  <DialogTitle>Leave workspace</DialogTitle>
                  <DialogContent>
                    <Alert severity="warning">
                      You will lose access to <strong>{activeWorkspace?.name}</strong> and all its channels. You can only rejoin if an admin re-invites you.
                    </Alert>
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={() => setLeaveDialogOpen(false)}>Cancel</Button>
                    <Button
                      variant="contained"
                      color="error"
                      disabled={leaving}
                      startIcon={leaving ? <CircularProgress size={14} color="inherit" /> : null}
                      onClick={handleLeaveWorkspace}
                    >
                      Leave workspace
                    </Button>
                  </DialogActions>
                </Dialog>

                <Dialog open={deleteWsDialogOpen} onClose={() => setDeleteWsDialogOpen(false)} maxWidth="xs" fullWidth>
                  <DialogTitle sx={{ color: 'error.main' }}>Delete workspace</DialogTitle>
                  <DialogContent>
                    <Alert severity="warning" sx={{ mb: 2 }}>
                      This will permanently delete <strong>{activeWorkspace?.name}</strong>, all channels, messages, files, and roles. This cannot be undone.
                    </Alert>
                    <TextField
                      autoFocus
                      label={`Type "${activeWorkspace?.name}" to confirm`}
                      fullWidth
                      variant="outlined"
                      value={deleteWsConfirm}
                      onChange={(e) => setDeleteWsConfirm(e.target.value)}
                    />
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={() => setDeleteWsDialogOpen(false)}>Cancel</Button>
                    <Button
                      variant="contained"
                      color="error"
                      disabled={deleteWsConfirm !== activeWorkspace?.name || deletingWs}
                      startIcon={deletingWs ? <CircularProgress size={14} color="inherit" /> : <Trash2 size={14} />}
                      onClick={handleDeleteWorkspace}
                    >
                      Delete permanently
                    </Button>
                  </DialogActions>
                </Dialog>
              </>
            )}
          </TabPanel>

          {/* Access & authorization */}
          {showAccessTab && (
            <TabPanel value={activeKey} index="access">
              <PermissionsManager />
            </TabPanel>
          )}

          {/* Security Tab */}
          <TabPanel value={activeKey} index="security">
            {/* 2FA */}
            <div className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-subtle flex items-center justify-center text-amber">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect width="18" height="11" x="3" y="11" rx="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                </div>
                <div>
                  <p className="text-sm font-semibold text-ink">Two-factor authentication</p>
                  <p className="text-[13px] text-ink-secondary">Use an authenticator app to generate one-time codes</p>
                </div>
              </div>
              <Switch checked={twoFaOn} onChange={(e) => handleTwoFaToggle(e.target.checked)} color="primary" />
            </div>

            {/* Passkeys */}
            <div className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-subtle flex items-center justify-center text-amber">
                  <KeyRound size={20} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-ink">Passkeys</p>
                  <p className="text-[13px] text-ink-secondary">Sign in with Face ID, Touch ID or a security key</p>
                </div>
              </div>
              <Button
                variant="outlined"
                size="small"
                onClick={() => setPasskeyDialogOpen(true)}
                disabled={passkeyLoading}
              >
                Add passkey
              </Button>
            </div>

            {/* Registered passkeys */}
            {passkeysLoading && passkeys.length === 0 ? (
              <div className="flex items-center gap-2 text-[13px] text-ink-tertiary mb-6 px-1">
                <CircularProgress size={14} /> Loading passkeys…
              </div>
            ) : passkeys.length > 0 ? (
              <div className="space-y-2 mb-6">
                {passkeys.map((p) => (
                  <div key={p.id} className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-3 px-4 flex items-center gap-3">
                    <div className="w-8 h-8 rounded-md bg-amber-subtle flex items-center justify-center text-amber shrink-0">
                      <KeyRound size={16} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-ink truncate">{p.name}</p>
                      <p className="text-xs text-ink-tertiary">{describePasskey(p)}</p>
                    </div>
                    <Button
                      variant="text"
                      size="small"
                      startIcon={<Trash2 size={14} />}
                      sx={{ color: 'text.disabled', '&:hover': { color: 'error.main' } }}
                      onClick={() => { setRemovePasskeyPassword(''); setRemovePasskey({ open: true, id: p.id, name: p.name }) }}
                    >
                      Remove
                    </Button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[13px] text-ink-tertiary mb-6 px-1">
                No passkeys yet. Add one to sign in with Face ID, Touch ID, or a security key.
              </p>
            )}

            {passkeyError && (
              <Alert severity="error" sx={{ mb: 3 }} onClose={() => dispatch(clearPasskeyError())}>{passkeyError}</Alert>
            )}

            {/* Sessions */}
            <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
              <h3 className="text-[15px] font-semibold text-ink">Active sessions</h3>
              <div className="flex gap-2 flex-wrap">
                {sessions.length > 1 && (
                  <Button
                    size="small"
                    variant="outlined"
                    color="error"
                    onClick={() => { setRevokeAllPassword(''); setRevokeAllDialog(true) }}
                  >
                    Sign out of all other devices
                  </Button>
                )}
                <Button
                  size="small"
                  variant="outlined"
                  onClick={openLoadSessions}
                  disabled={sessionsLoading}
                >
                  {sessionsLoading ? 'Loading…' : sessions.length ? 'Refresh' : 'Load sessions'}
                </Button>
              </div>
            </div>

            {sessions.length === 0 && !sessionsLoading && (
              <p className="text-[13px] text-ink-tertiary mb-8">
                Click "Load sessions" and enter your password to view devices signed into your account.
              </p>
            )}

            <div className="space-y-2 mb-8">
              {groupSessions(sessions).map((g) => {
                const open = expandedDevice === g.key
                return (
                  <div key={g.key} className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-3 px-4">
                    <div className="flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-ink flex items-center gap-2">
                          {g.device}
                          {g.current && <Chip label="This device" color="primary" size="small" />}
                        </p>
                        <p className="text-xs text-ink-tertiary">
                          {g.logins.length} sign-in{g.logins.length === 1 ? '' : 's'}
                          {g.lastActive ? ` · Last active ${new Date(g.lastActive).toLocaleString()}` : ''}
                        </p>
                      </div>
                      {g.logins.length > 1 && (
                        <Button
                          variant="text"
                          size="small"
                          onClick={() => setExpandedDevice(open ? null : g.key)}
                        >
                          {open ? 'Hide history' : 'History'}
                        </Button>
                      )}
                      {g.revocableIds.length > 0 && (
                        <Button
                          variant="text"
                          size="small"
                          sx={{ color: 'text.disabled', '&:hover': { color: 'error.main' } }}
                          onClick={() => handleRevokeDevice(g)}
                        >
                          {g.current ? 'Revoke others' : 'Revoke'}
                        </Button>
                      )}
                    </div>
                    {open && (
                      <div className="mt-3 pt-3 border-t border-[rgba(28,27,26,0.06)] space-y-1.5">
                        {g.logins.map((s) => (
                          <div key={s.id} className="flex items-center justify-between text-xs gap-2">
                            <span className="text-ink-secondary">
                              Signed in {s.created_at ? new Date(s.created_at).toLocaleString() : '—'}
                            </span>
                            <span className="text-ink-tertiary shrink-0">
                              {s.current ? 'Current session' : `Active ${s.last_used_at ? new Date(s.last_used_at).toLocaleString() : '—'}`}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Load Sessions Dialog */}
            <Dialog open={loadSessionsOpen} onClose={() => setLoadSessionsOpen(false)} maxWidth="xs" fullWidth>
              <DialogTitle>Confirm your password</DialogTitle>
              <DialogContent>
                <p className="text-sm text-ink-secondary mb-3">
                  Enter your password to view the devices signed into your account.
                </p>
                {settingsError && (
                  <Alert severity="error" sx={{ mb: 2 }} onClose={() => dispatch(clearSettingsError())}>{settingsError}</Alert>
                )}
                <TextField
                  autoFocus label="Current password" type="password" fullWidth variant="outlined" autoComplete="new-password"
                  value={loadSessionsPassword} onChange={(e) => setLoadSessionsPassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && loadSessionsPassword && handleLoadSessions(loadSessionsPassword)}
                />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setLoadSessionsOpen(false)}>Cancel</Button>
                <Button
                  variant="contained"
                  disabled={!loadSessionsPassword || sessionsLoading}
                  startIcon={sessionsLoading ? <CircularProgress size={14} color="inherit" /> : null}
                  onClick={() => handleLoadSessions(loadSessionsPassword)}
                >
                  Load sessions
                </Button>
              </DialogActions>
            </Dialog>

            {/* Revoke Session Dialog */}
            <Dialog open={revokeDialog.open} onClose={() => setRevokeDialog({ open: false, sessionIds: [], device: '' })} maxWidth="xs" fullWidth>
              <DialogTitle>Sign out {revokeDialog.device || 'this device'}</DialogTitle>
              <DialogContent>
                <p className="text-sm text-ink-secondary mb-3">
                  Enter your password to revoke {revokeDialog.sessionIds.length > 1 ? `${revokeDialog.sessionIds.length} sessions on this device` : 'this session'}.
                </p>
                {settingsError && (
                  <Alert severity="error" sx={{ mb: 2 }} onClose={() => dispatch(clearSettingsError())}>{settingsError}</Alert>
                )}
                <TextField
                  autoFocus label="Current password" type="password" fullWidth variant="outlined" autoComplete="new-password"
                  value={revokePassword} onChange={(e) => setRevokePassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleRevokeConfirm()}
                />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setRevokeDialog({ open: false, sessionIds: [], device: '' })}>Cancel</Button>
                <Button
                  variant="contained" color="error"
                  disabled={!revokePassword || settingsLoading}
                  startIcon={settingsLoading ? <CircularProgress size={14} color="inherit" /> : null}
                  onClick={handleRevokeConfirm}
                >
                  Revoke
                </Button>
              </DialogActions>
            </Dialog>

            {/* Revoke All Sessions Dialog */}
            <Dialog open={revokeAllDialog} onClose={() => setRevokeAllDialog(false)} maxWidth="xs" fullWidth>
              <DialogTitle>Sign out of all other devices</DialogTitle>
              <DialogContent>
                <p className="text-sm text-ink-secondary mb-3">
                  Enter your password to revoke every session except this one.
                </p>
                {settingsError && (
                  <Alert severity="error" sx={{ mb: 2 }} onClose={() => dispatch(clearSettingsError())}>{settingsError}</Alert>
                )}
                <TextField
                  autoFocus label="Current password" type="password" fullWidth variant="outlined" autoComplete="new-password"
                  value={revokeAllPassword} onChange={(e) => setRevokeAllPassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleRevokeAllConfirm()}
                />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setRevokeAllDialog(false)}>Cancel</Button>
                <Button
                  variant="contained" color="error"
                  disabled={!revokeAllPassword || settingsLoading}
                  startIcon={settingsLoading ? <CircularProgress size={14} color="inherit" /> : null}
                  onClick={handleRevokeAllConfirm}
                >
                  Sign out all
                </Button>
              </DialogActions>
            </Dialog>

            {/* Session Detail Dialog */}
            <Dialog open={Boolean(sessionDetail) || sessionDetailLoading} onClose={() => setSessionDetail(null)} maxWidth="xs" fullWidth>
              <DialogTitle>Session details</DialogTitle>
              <DialogContent>
                {sessionDetailLoading ? (
                  <div className="flex justify-center py-8"><CircularProgress size={24} /></div>
                ) : sessionDetail ? (
                  <div className="space-y-2 text-sm">
                    <div><span className="text-ink-tertiary">ID:</span> <span className="font-mono text-xs">{sessionDetail.id}</span></div>
                    <div><span className="text-ink-tertiary">User agent:</span> {sessionDetail.user_agent || '—'}</div>
                    <div><span className="text-ink-tertiary">Created:</span> {sessionDetail.created_at ? new Date(sessionDetail.created_at).toLocaleString() : '—'}</div>
                    <div><span className="text-ink-tertiary">Last used:</span> {sessionDetail.last_used_at ? new Date(sessionDetail.last_used_at).toLocaleString() : '—'}</div>
                    {sessionDetail.current && <Chip label="Current session" color="primary" size="small" />}
                  </div>
                ) : null}
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setSessionDetail(null)}>Close</Button>
              </DialogActions>
            </Dialog>

            {/* TOTP Setup Dialog */}
            <Dialog open={totpDialogOpen} onClose={handleCloseTotpDialog} maxWidth="xs" fullWidth>
              <DialogTitle>
                {sudoForSetup ? 'Confirm your password' : 'Set up two-factor authentication'}
              </DialogTitle>
              <DialogContent>
                {totpError && <Alert severity="error" sx={{ mb: 2 }}>{totpError}</Alert>}
                {sudoForSetup ? (
                  <>
                    <p className="text-sm text-ink-secondary mb-3">
                      Enter your password to continue.
                    </p>
                    <TextField
                      autoFocus label="Password" type="password" fullWidth autoComplete="new-password"
                      value={totpPassword} onChange={(e) => setTotpPassword(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleStartTotpSetup()}
                    />
                  </>
                ) : totpSetup ? (
                  <>
                    <p className="text-sm text-ink-secondary mb-3">
                      Scan this QR code with your authenticator app and enter the 6-digit code below.
                    </p>
                    <div className="flex justify-center mb-3">
                      <img
                        src={totpSetup.qr}
                        alt="TOTP QR"
                        className="w-40 h-40 rounded border border-[rgba(28,27,26,0.10)]"
                      />
                    </div>
                    <TextField
                      autoFocus label="6-digit code" fullWidth value={totpCode}
                      inputMode="numeric"
                      onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      onKeyDown={(e) => e.key === 'Enter' && totpCode.length === 6 && handleConfirmTotp()}
                      slotProps={{ htmlInput: { maxLength: 6, style: { letterSpacing: '0.5em', textAlign: 'center' } } }}
                    />
                  </>
                ) : (
                  <div className="flex justify-center py-8"><CircularProgress size={24} /></div>
                )}
              </DialogContent>
              <DialogActions>
                <Button onClick={handleCloseTotpDialog}>Cancel</Button>
                {sudoForSetup ? (
                  <Button variant="contained" disabled={!totpPassword} onClick={handleStartTotpSetup}>
                    Continue
                  </Button>
                ) : (
                  <Button
                    variant="contained" disabled={!totpSetup || totpCode.length !== 6}
                    onClick={handleConfirmTotp}
                  >
                    Enable
                  </Button>
                )}
              </DialogActions>
            </Dialog>

            {/* Passkey Registration Dialog */}
            <Dialog open={passkeyDialogOpen} onClose={() => setPasskeyDialogOpen(false)} maxWidth="xs" fullWidth>
              <DialogTitle>Add a passkey</DialogTitle>
              <DialogContent>
                <p className="text-sm text-ink-secondary mb-3">
                  Enter your password, name this passkey, then follow your browser's prompt.
                </p>
                <TextField
                  label="Current password" type="password" fullWidth sx={{ mb: 2 }} autoComplete="new-password"
                  value={passkeyPassword} onChange={(e) => setPasskeyPassword(e.target.value)}
                />
                <TextField
                  label="Passkey name" fullWidth placeholder="e.g. MacBook Pro"
                  value={passkeyName} onChange={(e) => setPasskeyName(e.target.value)}
                />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setPasskeyDialogOpen(false)}>Cancel</Button>
                <Button
                  variant="contained"
                  disabled={!passkeyPassword || passkeyLoading}
                  onClick={handleAddPasskey}
                  startIcon={passkeyLoading ? <CircularProgress size={14} color="inherit" /> : null}
                >
                  Create passkey
                </Button>
              </DialogActions>
            </Dialog>

            {/* Remove Passkey Dialog */}
            <Dialog open={removePasskey.open} onClose={() => setRemovePasskey({ open: false, id: null, name: '' })} maxWidth="xs" fullWidth>
              <DialogTitle>Remove passkey</DialogTitle>
              <DialogContent>
                <p className="text-sm text-ink-secondary mb-3">
                  Enter your password to remove <span className="font-medium text-ink">{removePasskey.name}</span>. You won't be able to sign in with it anymore.
                </p>
                {passkeyError && (
                  <Alert severity="error" sx={{ mb: 2 }} onClose={() => dispatch(clearPasskeyError())}>{passkeyError}</Alert>
                )}
                <TextField
                  autoFocus label="Current password" type="password" fullWidth variant="outlined" autoComplete="new-password"
                  value={removePasskeyPassword} onChange={(e) => setRemovePasskeyPassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && removePasskeyPassword && handleRemovePasskey()}
                />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setRemovePasskey({ open: false, id: null, name: '' })}>Cancel</Button>
                <Button
                  variant="contained" color="error"
                  disabled={!removePasskeyPassword || passkeyLoading}
                  startIcon={passkeyLoading ? <CircularProgress size={14} color="inherit" /> : null}
                  onClick={handleRemovePasskey}
                >
                  Remove
                </Button>
              </DialogActions>
            </Dialog>

            <h3 className="text-[15px] font-semibold text-ink mb-4">Connected accounts</h3>
            <div className="space-y-0">
              {CONNECTABLE_PROVIDERS.map((provider, i) => {
                const isConnected = Boolean(connections[provider.key])
                const isBusy = connectingProvider === provider.key
                return (
                  <div
                    key={provider.key}
                    className={`flex items-center gap-3 py-3 ${
                      i < CONNECTABLE_PROVIDERS.length - 1
                        ? 'border-b border-[rgba(28,27,26,0.06)]'
                        : ''
                    }`}
                  >
                    <div className="w-8 h-8 rounded-md bg-surface-2 flex items-center justify-center text-sm font-bold">
                      {provider.glyph}
                    </div>
                    <div className="flex-1">
                      <p className="text-sm font-medium text-ink">{provider.label}</p>
                      <p className="text-xs text-ink-tertiary">
                        {isConnected ? 'Linked to your account' : 'Not connected'}
                      </p>
                    </div>
                    {isConnected ? (
                      <Chip label="Connected" color="success" size="small" variant="outlined" />
                    ) : (
                      <Button
                        variant="outlined"
                        size="small"
                        color="primary"
                        disabled={isBusy}
                        startIcon={isBusy ? <CircularProgress size={14} color="inherit" /> : null}
                        onClick={() => handleConnectProvider(provider.key)}
                      >
                        {isBusy ? 'Connecting…' : 'Connect'}
                      </Button>
                    )}
                  </div>
                )
              })}
            </div>
          </TabPanel>

          <TabPanel value={activeKey} index="notifications">
            <NotificationsSettingsTab />
          </TabPanel>

          {/* Advanced Tab */}
          <TabPanel value={activeKey} index="advanced">
            <div className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-subtle flex items-center justify-center text-amber">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <polyline points="4 17 10 11 4 5" />
                    <line x1="12" y1="19" x2="20" y2="19" />
                  </svg>
                </div>
                <div>
                  <p className="text-sm font-semibold text-ink">Developer mode</p>
                  <p className="text-[13px] text-ink-secondary max-w-md">
                    Show the full retrieval trace (sources, chunks and the exact prompt) under every
                    Talos AI answer in chat. Useful for debugging RAG results.
                  </p>
                </div>
              </div>
              <Switch
                checked={devMode}
                onChange={(e) => { const on = e.target.checked; setDevMode(on); setDevModeState(on) }}
                color="primary"
              />
            </div>
          </TabPanel>

        </div>
      </div>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={3000}
        onClose={() => setSnackbar({ open: false, message: '' })}
        message={snackbar.message}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      />
    </>
  )
}
