import { useState, useRef, useEffect } from 'react'
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
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import { Upload, KeyRound } from 'lucide-react'
import {
  changePassword,
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
} from '../../store/authSlice'
import { authService } from '../../services/auth'
import { aiSettingsService } from '../../services/aiSettings'
import { authorizationService } from '../../services/authorization'

function TabPanel({ value, index, children }) {
  if (value !== index) return null
  return <div>{children}</div>
}

const INITIAL_MEMBERS = [
  { name: 'Abdelrahman Abouromia', email: 'abdelrahman@alexuni.edu', initials: 'AA', role: 'Owner' },
  { name: 'Mohab Sherif', email: 'mohab@alexuni.edu', initials: 'MS', role: 'Admin' },
  { name: 'Kyrollos Youssef', email: 'kyrollos@alexuni.edu', initials: 'KY', role: 'Member' },
  { name: 'Kyria Dawod', email: 'kyria@alexuni.edu', initials: 'KD', role: 'Member' },
  { name: 'Nourhane Tarek', email: 'nourhane@alexuni.edu', initials: 'NT', role: 'Member' },
  { name: 'Abdullah Elsalmy', email: 'abdullah@alexuni.edu', initials: 'AE', role: 'Member' },
  { name: 'Dr. Mervat Mikhail', email: 'mervat@alexuni.edu', initials: 'MM', role: 'Supervisor' },
]

function describeSession(s) {
  const ua = s.user_agent || 'Unknown device'
  let device = ua
  if (/iPhone|iPad/i.test(ua)) device = 'Safari on iPhone'
  else if (/Android/i.test(ua)) device = 'Browser on Android'
  else if (/Chrome/i.test(ua)) device = 'Chrome on ' + (/Windows/i.test(ua) ? 'Windows' : /Mac/i.test(ua) ? 'macOS' : 'Linux')
  else if (/Firefox/i.test(ua)) device = 'Firefox on ' + (/Windows/i.test(ua) ? 'Windows' : /Mac/i.test(ua) ? 'macOS' : 'Linux')
  else if (/Safari/i.test(ua)) device = 'Safari on macOS'
  const last = s.last_used_at ? new Date(s.last_used_at).toLocaleString() : 'Unknown'
  return { device, location: `Last active ${last}` }
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
  } = useSelector((s) => s.auth)

  const [tab, setTab] = useState(0)
  const [snackbar, setSnackbar] = useState({ open: false, message: '' })
  const showSnackbar = (message) => setSnackbar({ open: true, message })

  const [revokeDialog, setRevokeDialog] = useState({ open: false, sessionId: null })
  const [revokePassword, setRevokePassword] = useState('')
  const [revokeAllDialog, setRevokeAllDialog] = useState(false)
  const [revokeAllPassword, setRevokeAllPassword] = useState('')
  const [sessionDetail, setSessionDetail] = useState(null)
  const [sessionDetailLoading, setSessionDetailLoading] = useState(false)

  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [avatarSrc, setAvatarSrc] = useState(null)
  const fileInputRef = useRef(null)

  const [workspaceName, setWorkspaceName] = useState('Alex Uni')
  const [members, setMembers] = useState(INITIAL_MEMBERS)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [roleAnchorEl, setRoleAnchorEl] = useState(null)
  const [roleMenuIndex, setRoleMenuIndex] = useState(null)

  const [twoFaOn, setTwoFaOn] = useState(false)
  const [totpDialogOpen, setTotpDialogOpen] = useState(false)
  const [totpPassword, setTotpPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [sudoForSetup, setSudoForSetup] = useState(false)

  const [passkeyDialogOpen, setPasskeyDialogOpen] = useState(false)
  const [passkeyName, setPasskeyName] = useState('')
  const [passkeyPassword, setPasskeyPassword] = useState('')

  const [authSummary, setAuthSummary] = useState(null)
  const [authSummaryLoading, setAuthSummaryLoading] = useState(false)
  const [authSummaryError, setAuthSummaryError] = useState('')

  const [aiConfigLoading, setAiConfigLoading] = useState(false)
  const [aiSaveLoading, setAiSaveLoading] = useState(false)
  const [model, setModel] = useState('gpt-4o-mini')
  const [embeddingModel, setEmbeddingModel] = useState('text-embedding-3-small')
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(200)
  const [topK, setTopK] = useState(5)
  const [llmTemperature, setLlmTemperature] = useState(0)
  const [memK, setMemK] = useState(3)

  useEffect(() => {
    if (!user) return
    const parts = (user.name || '').split(' ')
    setFirstName(parts[0] || '')
    setLastName(parts.slice(1).join(' ') || '')
    setEmail(user.email || '')
  }, [user])

  const handleUploadPhoto = () => fileInputRef.current?.click()
  const handleFileChange = (e) => {
    const file = e.target.files?.[0]
    if (file) {
      const reader = new FileReader()
      reader.onload = (ev) => setAvatarSrc(ev.target.result)
      reader.readAsDataURL(file)
    }
  }
  const handleRemovePhoto = () => setAvatarSrc(null)

  const getInitials = () => {
    const f = firstName.trim()?.[0] || ''
    const l = lastName.trim()?.[0] || ''
    return (f + l).toUpperCase() || (user?.username?.slice(0, 2).toUpperCase() ?? 'U')
  }

  const handleInviteSend = () => {
    setInviteOpen(false)
    setInviteEmail('')
    showSnackbar('Invitation sent')
  }

  const handleRoleClick = (event, index) => {
    setRoleAnchorEl(event.currentTarget)
    setRoleMenuIndex(index)
  }

  const handleRoleChange = (newRole) => {
    setMembers((prev) =>
      prev.map((m, i) => (i === roleMenuIndex ? { ...m, role: newRole } : m))
    )
    setRoleAnchorEl(null)
    setRoleMenuIndex(null)
  }

  const handleLoadSessions = async (password) => {
    const result = await dispatch(listSessions({ password }))
    if (listSessions.fulfilled.match(result)) {
      showSnackbar(`Loaded ${result.payload.length} session(s)`)
    }
  }

  const handleRevokeSession = (id) => {
    setRevokeDialog({ open: true, sessionId: id })
    setRevokePassword('')
    dispatch(clearSettingsError())
  }

  const handleRevokeConfirm = async () => {
    const result = await dispatch(revokeSession({ sessionId: revokeDialog.sessionId, password: revokePassword }))
    if (revokeSession.fulfilled.match(result)) {
      setRevokeDialog({ open: false, sessionId: null })
      setRevokePassword('')
      showSnackbar('Session revoked')
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
    if (newPassword.length < 8) {
      showSnackbar('New password must be at least 8 characters')
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
    }
  }

  useEffect(() => {
    if (tab !== 2) return
    let cancelled = false
    setAuthSummaryLoading(true)
    setAuthSummaryError('')
    authorizationService
      .summary()
      .then((d) => {
        if (!cancelled) setAuthSummary(d)
      })
      .catch((e) => {
        if (!cancelled) setAuthSummaryError(e?.detail || 'Failed to load access data')
      })
      .finally(() => {
        if (!cancelled) setAuthSummaryLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tab])

  useEffect(() => {
    if (tab !== 4) return
    let cancelled = false
    setAiConfigLoading(true)
    aiSettingsService
      .getConfig()
      .then((d) => {
        if (cancelled || !d) return
        if (d.openai_model) setModel(d.openai_model)
        if (d.embedding_model) setEmbeddingModel(d.embedding_model)
        if (d.chunk_size != null) setChunkSize(d.chunk_size)
        if (d.chunk_overlap != null) setChunkOverlap(d.chunk_overlap)
        if (d.retrieval_top_k != null) setTopK(d.retrieval_top_k)
        if (d.llm_temperature != null) setLlmTemperature(d.llm_temperature)
        if (d.conversation_memory_k != null) setMemK(d.conversation_memory_k)
      })
      .catch(() => {
        if (!cancelled) showSnackbar('Could not load AI configuration')
      })
      .finally(() => {
        if (!cancelled) setAiConfigLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tab])

  const formatApiError = (e) => {
    const d = e?.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d) && d.length) {
      return d
        .map((x) => (x && (x.msg || x.message)) || String(x))
        .filter(Boolean)
        .join(' ')
    }
    return e?.message || 'Request failed'
  }

  const handleSaveAiConfig = async () => {
    setAiSaveLoading(true)
    try {
      const toNum = (v, min, max) => {
        const n = Number(v)
        if (Number.isNaN(n)) return min
        return Math.min(max, Math.max(min, n))
      }
      const updated = await aiSettingsService.patchConfig({
        openai_model: model,
        embedding_model: embeddingModel,
        chunk_size: toNum(chunkSize, 100, 32_000),
        chunk_overlap: toNum(chunkOverlap, 0, 4000),
        retrieval_top_k: toNum(topK, 1, 50),
        llm_temperature: toNum(llmTemperature, 0, 2),
        conversation_memory_k: toNum(memK, 0, 100),
      })
      if (updated?.openai_model) setModel(updated.openai_model)
      if (updated?.embedding_model) setEmbeddingModel(updated.embedding_model)
      if (updated?.chunk_size != null) setChunkSize(updated.chunk_size)
      if (updated?.chunk_overlap != null) setChunkOverlap(updated.chunk_overlap)
      if (updated?.retrieval_top_k != null) setTopK(updated.retrieval_top_k)
      if (updated?.llm_temperature != null) setLlmTemperature(updated.llm_temperature)
      if (updated?.conversation_memory_k != null) setMemK(updated.conversation_memory_k)
      showSnackbar('AI configuration saved')
    } catch (e) {
      showSnackbar(formatApiError(e) || 'Failed to save AI configuration')
    } finally {
      setAiSaveLoading(false)
    }
  }

  return (
    <>
      <input
        type="file"
        accept="image/jpeg,image/png,image/gif"
        ref={fileInputRef}
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />

      <header className="h-14 bg-base border-b border-[rgba(28,27,26,0.10)] flex items-center px-6 shrink-0">
        <h1 className="text-lg font-semibold text-ink tracking-tight">Settings</h1>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[680px] mx-auto px-6 py-8 w-full">
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
            <Tab label="Profile" />
            <Tab label="Workspace" />
            <Tab label="Access" />
            <Tab label="Security" />
            <Tab label="Configuration" />
          </Tabs>

          {/* Profile Tab */}
          <TabPanel value={tab} index={0}>
            <div className="flex items-center gap-6 mb-8">
              <Avatar
                src={avatarSrc || undefined}
                sx={{ width: 56, height: 56, bgcolor: 'primary.light', color: 'primary.main', fontSize: 22, fontWeight: 600 }}
              >
                {!avatarSrc && getInitials()}
              </Avatar>
              <div>
                <div className="flex gap-2 mb-1">
                  <Button variant="outlined" size="small" startIcon={<Upload size={14} />} onClick={handleUploadPhoto}>Upload photo</Button>
                  <Button variant="text" size="small" sx={{ color: 'text.disabled' }} onClick={handleRemovePhoto}>Remove</Button>
                </div>
                <p className="text-xs text-ink-muted">JPG, PNG or GIF. Max 2MB.</p>
              </div>
            </div>

            <h3 className="text-[15px] font-semibold text-ink mb-4">Personal information</h3>
            <div className="grid grid-cols-2 gap-4 mb-8">
              <TextField label="First name" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
              <TextField label="Last name" value={lastName} onChange={(e) => setLastName(e.target.value)} />
              <div className="col-span-2 relative">
                <TextField label="Email" value={email} onChange={(e) => setEmail(e.target.value)} fullWidth />
              </div>
            </div>

            <h3 className="text-[15px] font-semibold text-ink mb-4">Change password</h3>
            <div className="grid grid-cols-1 gap-4 mb-8">
              <TextField label="Current password" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
              <TextField label="New password" type="password" placeholder="Min. 8 characters" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              <TextField label="Confirm new password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
            </div>

            {settingsError && (
              <Alert severity="error" sx={{ mb: 2 }} onClose={() => dispatch(clearSettingsError())}>{settingsError}</Alert>
            )}

            <div className="flex justify-end pt-6 border-t border-[rgba(28,27,26,0.06)]">
              <Button
                variant="contained"
                disabled={settingsLoading}
                startIcon={settingsLoading ? <CircularProgress size={14} color="inherit" /> : null}
                onClick={currentPassword ? handleChangePassword : () => showSnackbar('Profile updates are not supported yet')}
              >
                Save changes
              </Button>
            </div>
          </TabPanel>

          {/* Workspace Tab */}
          <TabPanel value={tab} index={1}>
            <h3 className="text-[15px] font-semibold text-ink mb-4">Workspace settings</h3>
            <TextField label="Workspace name" value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} fullWidth sx={{ mb: 4 }} />

            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[15px] font-semibold text-ink">Members ({members.length})</h3>
              <Button variant="contained" size="small" onClick={() => setInviteOpen(true)}>Invite</Button>
            </div>

            <div className="border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden mb-8">
              {members.map((m, i) => (
                <div key={m.name} className={`flex items-center p-3 px-4 ${i < members.length - 1 ? 'border-b border-[rgba(28,27,26,0.06)]' : ''}`}>
                  <div className="flex items-center gap-3 flex-1">
                    <Avatar sx={{ width: 32, height: 32, fontSize: 12, fontWeight: 600 }}>{m.initials}</Avatar>
                    <div>
                      <p className="text-sm font-medium text-ink">{m.name}</p>
                      <p className="text-xs text-ink-tertiary">{m.email}</p>
                    </div>
                  </div>
                  <Button
                    size="small"
                    onClick={(e) => handleRoleClick(e, i)}
                    sx={{
                      textTransform: 'none',
                      fontSize: 13,
                      fontWeight: 500,
                      color: m.role === 'Owner' ? 'var(--amber)' : 'text.secondary',
                    }}
                  >
                    {m.role}
                  </Button>
                </div>
              ))}
            </div>

            <Menu anchorEl={roleAnchorEl} open={Boolean(roleAnchorEl)} onClose={() => setRoleAnchorEl(null)}>
              {['Owner', 'Admin', 'Member', 'Supervisor'].map((role) => (
                <MenuItem key={role} onClick={() => handleRoleChange(role)}>{role}</MenuItem>
              ))}
            </Menu>

            <div className="bg-error-subtle border border-[rgba(196,70,42,0.2)] rounded-lg p-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold" style={{ color: '#A33820' }}>Delete workspace</p>
                <p className="text-[13px] text-ink-secondary">This action is irreversible. All data will be permanently deleted.</p>
              </div>
              <Button variant="outlined" color="error" size="small" onClick={() => setDeleteOpen(true)}>Delete</Button>
            </div>

            <Dialog open={inviteOpen} onClose={() => setInviteOpen(false)} maxWidth="xs" fullWidth>
              <DialogTitle>Invite member</DialogTitle>
              <DialogContent>
                <TextField
                  autoFocus label="Email address" type="email" fullWidth variant="outlined" sx={{ mt: 1 }}
                  value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)}
                />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setInviteOpen(false)}>Cancel</Button>
                <Button variant="contained" onClick={handleInviteSend}>Send invite</Button>
              </DialogActions>
            </Dialog>

            <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)}>
              <DialogTitle>Are you sure?</DialogTitle>
              <DialogContent>
                <p className="text-sm text-ink-secondary">This action is irreversible. All workspace data will be permanently deleted.</p>
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setDeleteOpen(false)}>Cancel</Button>
                <Button variant="contained" color="error" onClick={() => { setDeleteOpen(false); showSnackbar('Workspace deleted') }}>Delete</Button>
              </DialogActions>
            </Dialog>
          </TabPanel>

          {/* Access & authorization */}
          <TabPanel value={tab} index={2}>
            <h3 className="text-[15px] font-semibold text-ink mb-1">Access &amp; roles</h3>
            <p className="text-[13px] text-ink-secondary mb-4">
              Your platform roles, the permissions they grant, workspace scope, and how those map to
              key product areas.
            </p>

            {authSummaryError && (
              <Alert severity="error" sx={{ mb: 2 }} onClose={() => setAuthSummaryError('')}>
                {authSummaryError}
              </Alert>
            )}

            {authSummaryLoading ? (
              <div className="flex justify-center py-10">
                <CircularProgress size={28} />
              </div>
            ) : (
              <>
                <div className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-4 mb-6">
                  <h4 className="text-sm font-semibold text-ink mb-2">Your platform roles</h4>
                  {authSummary?.roles?.length ? (
                    <div className="flex flex-wrap gap-2">
                      {authSummary.roles.map((r) => (
                        <Chip key={r.id} label={r.name} size="small" color="primary" variant="outlined" />
                      ))}
                    </div>
                  ) : (
                    <p className="text-[13px] text-ink-tertiary">No platform roles are assigned to your account yet.</p>
                  )}
                </div>

                <div className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-4 mb-6">
                  <h4 className="text-sm font-semibold text-ink mb-2">Permissions from those roles</h4>
                  {authSummary?.permissions?.length ? (
                    <ul className="list-disc pl-5 text-sm text-ink-secondary space-y-1">
                      {authSummary.permissions.map((p) => (
                        <li key={p.id || p.name}>
                          <span className="text-ink font-medium">{p.name}</span>
                          {p.description ? <span> — {p.description}</span> : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-[13px] text-ink-tertiary">
                      No named permissions on your account yet. They appear here when a role
                      includes specific grants.
                    </p>
                  )}
                </div>

                <div className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-4 mb-6">
                  <h4 className="text-sm font-semibold text-ink mb-3">Workspace scope</h4>
                  {authSummary?.workspace_scopes?.length ? (
                    <ul className="space-y-2">
                      {authSummary.workspace_scopes.map((s) => (
                        <li
                          key={s.label + (s.workspace_id || '')}
                          className="flex items-start justify-between gap-3 text-[13px] border border-[rgba(28,27,26,0.06)] rounded-md px-3 py-2"
                        >
                          <span className="text-ink font-medium leading-snug">{s.label}</span>
                          {s.access ? (
                            <Chip
                              size="small"
                              label={String(s.access).replace(/_/g, ' ')}
                              variant="outlined"
                              sx={{ height: 24, textTransform: 'none', fontSize: 11 }}
                            />
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-[13px] text-ink-tertiary">
                      Workspace-level access is determined by your membership and role in each
                      workspace.
                    </p>
                  )}
                </div>

                <h4 className="text-sm font-semibold text-ink mb-1">Resource access</h4>
                <p className="text-[12px] text-ink-tertiary mb-3">
                  How platform permissions apply to major areas of the product.
                </p>
                <div className="border border-[rgba(28,27,26,0.08)] rounded-lg overflow-hidden text-sm">
                  <div className="grid grid-cols-12 gap-0 bg-surface-2/80 text-[11px] font-semibold text-ink-tertiary uppercase tracking-wide px-3 py-2 border-b border-[rgba(28,27,26,0.08)]">
                    <div className="col-span-3">Resource</div>
                    <div className="col-span-4">Actions</div>
                    <div className="col-span-5">Description</div>
                  </div>
                  {(
                    authSummary?.resource_matrix?.rows
                    || authSummary?.resource_matrix_stub?.rows
                    || []
                  ).map((row) => (
                    <div
                      key={row.resource}
                      className="grid grid-cols-12 gap-0 px-3 py-2.5 border-b border-[rgba(28,27,26,0.06)] last:border-0 text-[13px] items-start"
                    >
                      <div className="col-span-3 font-medium text-ink">{row.resource}</div>
                      <div className="col-span-4 text-ink-secondary">
                        <div className="flex flex-wrap gap-1">
                          {(row.actions || []).map((a) => (
                            <Chip
                              key={a}
                              size="small"
                              label={a}
                              variant="outlined"
                              sx={{ height: 22, fontSize: 11, textTransform: 'lowercase' }}
                            />
                          ))}
                        </div>
                      </div>
                      <div className="col-span-5 text-ink-tertiary text-[12px] leading-relaxed">
                        {row.note}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </TabPanel>

          {/* Security Tab */}
          <TabPanel value={tab} index={3}>
            {/* 2FA */}
            <div className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-4 flex items-center justify-between mb-6">
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
            <div className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-4 flex items-center justify-between mb-6">
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

            {passkeyError && (
              <Alert severity="error" sx={{ mb: 3 }} onClose={() => dispatch(clearPasskeyError())}>{passkeyError}</Alert>
            )}

            {/* Sessions */}
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[15px] font-semibold text-ink">Active sessions</h3>
              <div className="flex gap-2">
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
                  onClick={() => {
                    const pw = window.prompt('Enter your password to load active sessions:') || ''
                    if (pw) handleLoadSessions(pw)
                  }}
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
              {sessions.map((s) => {
                const { device, location } = describeSession(s)
                return (
                  <div key={s.id} className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-3 px-4 flex items-center gap-3">
                    <div className="flex-1 cursor-pointer" onClick={() => handleViewSession(s.id)}>
                      <p className="text-sm font-medium text-ink">{device}</p>
                      <p className="text-xs text-ink-tertiary">{location}</p>
                    </div>
                    <Button
                      variant="text"
                      size="small"
                      onClick={() => handleViewSession(s.id)}
                    >
                      View
                    </Button>
                    {s.current ? (
                      <Chip label="Current" color="primary" size="small" />
                    ) : (
                      <Button
                        variant="text"
                        size="small"
                        sx={{ color: 'text.disabled', '&:hover': { color: 'error.main' } }}
                        onClick={() => handleRevokeSession(s.id)}
                      >
                        Revoke
                      </Button>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Revoke Session Dialog */}
            <Dialog open={revokeDialog.open} onClose={() => setRevokeDialog({ open: false, sessionId: null })} maxWidth="xs" fullWidth>
              <DialogTitle>Confirm session revoke</DialogTitle>
              <DialogContent>
                <p className="text-sm text-ink-secondary mb-3">Enter your password to revoke this session.</p>
                {settingsError && (
                  <Alert severity="error" sx={{ mb: 2 }} onClose={() => dispatch(clearSettingsError())}>{settingsError}</Alert>
                )}
                <TextField
                  autoFocus label="Current password" type="password" fullWidth variant="outlined"
                  value={revokePassword} onChange={(e) => setRevokePassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleRevokeConfirm()}
                />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setRevokeDialog({ open: false, sessionId: null })}>Cancel</Button>
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
                  autoFocus label="Current password" type="password" fullWidth variant="outlined"
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
                      autoFocus label="Password" type="password" fullWidth
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
                        src={`data:image/png;base64,${totpSetup.qr}`}
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
                  label="Current password" type="password" fullWidth sx={{ mb: 2 }}
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

            <h3 className="text-[15px] font-semibold text-ink mb-4">Connected accounts</h3>
            <div className="space-y-0">
              <div className="flex items-center gap-3 py-3 border-b border-[rgba(28,27,26,0.06)]">
                <div className="w-8 h-8 rounded-md bg-surface-2 flex items-center justify-center text-sm font-bold">G</div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-ink">Google</p>
                </div>
                <Button variant="text" size="small" color="primary" onClick={() => authService.googleLogin()}>
                  Connect
                </Button>
              </div>
              <div className="flex items-center gap-3 py-3">
                <div className="w-8 h-8 rounded-md bg-surface-2 flex items-center justify-center text-sm font-bold">G</div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-ink">GitHub</p>
                </div>
                <Button variant="text" size="small" color="primary" onClick={() => authService.githubLogin()}>
                  Connect
                </Button>
              </div>
            </div>
          </TabPanel>

          {/* Configuration Tab */}
          <TabPanel value={tab} index={4}>
            <h3 className="text-[15px] font-semibold text-ink mb-1">AI configuration</h3>
            <p className="text-[13px] text-ink-secondary mb-4">
              Model names, chunking, retrieval, and memory settings are saved on the server and
              used for the next requests. The OpenAI key is only read from the server environment,
              not from this page.
            </p>

            {aiConfigLoading ? (
              <div className="flex justify-center py-10">
                <CircularProgress size={28} />
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 mb-8">
                <TextField
                  label="Chat / generation model"
                  select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  SelectProps={{ native: true }}
                >
                  <option value="gpt-4o">gpt-4o</option>
                  <option value="gpt-4o-mini">gpt-4o-mini</option>
                  <option value="gpt-3.5-turbo">gpt-3.5-turbo</option>
                </TextField>
                <TextField
                  label="Embedding model"
                  value={embeddingModel}
                  onChange={(e) => setEmbeddingModel(e.target.value)}
                  helperText="OpenAI text-embedding-* id, e.g. text-embedding-3-small"
                />
                <div className="grid grid-cols-2 gap-4">
                  <TextField label="Chunk size" type="number" value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))} />
                  <TextField label="Chunk overlap" type="number" value={chunkOverlap} onChange={(e) => setChunkOverlap(Number(e.target.value))} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <TextField
                    label="Top K (retrieval)"
                    type="number"
                    value={topK}
                    onChange={(e) => setTopK(Number(e.target.value))}
                  />
                  <TextField
                    label="Memory turns (K)"
                    type="number"
                    value={memK}
                    onChange={(e) => setMemK(Number(e.target.value))}
                  />
                </div>
                <TextField
                  label="LLM temperature"
                  type="number"
                  inputProps={{ step: 0.1, min: 0, max: 2 }}
                  value={llmTemperature}
                  onChange={(e) => setLlmTemperature(Number(e.target.value))}
                />
              </div>
            )}

            <div className="flex justify-end pt-6 border-t border-[rgba(28,27,26,0.06)]">
              <Button
                variant="contained"
                disabled={aiSaveLoading || aiConfigLoading}
                startIcon={aiSaveLoading ? <CircularProgress size={14} color="inherit" /> : null}
                onClick={handleSaveAiConfig}
              >
                Save configuration
              </Button>
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
