import { useState, useEffect, useCallback } from 'react'
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
import { KeyRound, Trash2, ShieldCheck } from 'lucide-react'
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
import { chatService } from '../../services/chat'
import { authorizationService } from '../../services/authorization'

function TabPanel({ value, index, children }) {
  if (value !== index) return null
  return <div>{children}</div>
}

function initialsOf(name) {
  return (name || '?')
    .split(' ')
    .map((n) => n[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

const SCOPE_LABEL = { 0: 'any', 1: 'own' }

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

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const { activeWorkspaceId, workspaces } = useSelector((s) => s.workspace)
  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId) || null
  const isOwner = Boolean(activeWorkspace && user && activeWorkspace.owner_id === user.id)

  const [members, setMembers] = useState([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteIdentifier, setInviteIdentifier] = useState('')
  const [inviteSubmitting, setInviteSubmitting] = useState(false)
  const [inviteError, setInviteError] = useState('')
  const [removingId, setRemovingId] = useState(null)

  const [perms, setPerms] = useState([])
  const [permsLoading, setPermsLoading] = useState(false)
  const [permsError, setPermsError] = useState('')

  const [twoFaOn, setTwoFaOn] = useState(false)
  const [totpDialogOpen, setTotpDialogOpen] = useState(false)
  const [totpPassword, setTotpPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [sudoForSetup, setSudoForSetup] = useState(false)

  const [passkeyDialogOpen, setPasskeyDialogOpen] = useState(false)
  const [passkeyName, setPasskeyName] = useState('')
  const [passkeyPassword, setPasskeyPassword] = useState('')

  const getInitials = () => {
    const name = user?.name || user?.username || 'U'
    return name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()
  }

  const loadMembers = useCallback(async () => {
    if (!activeWorkspaceId) {
      setMembers([])
      return
    }
    setMembersLoading(true)
    try {
      const list = await chatService.getMembers(activeWorkspaceId)
      setMembers(Array.isArray(list) ? list : [])
    } catch (err) {
      showSnackbar(err?.detail || 'Could not load members')
    } finally {
      setMembersLoading(false)
    }
  }, [activeWorkspaceId])

  const loadPermissions = useCallback(async () => {
    if (!activeWorkspaceId) {
      setPerms([])
      return
    }
    setPermsLoading(true)
    setPermsError('')
    try {
      const list = await authorizationService.myPermissions(activeWorkspaceId)
      setPerms(Array.isArray(list) ? list : [])
    } catch (err) {
      setPermsError(err?.detail || 'Could not load your permissions')
    } finally {
      setPermsLoading(false)
    }
  }, [activeWorkspaceId])

  useEffect(() => {
    if (tab === 1) loadMembers()
    if (tab === 2) loadPermissions()
  }, [tab, loadMembers, loadPermissions])

  const handleInviteSend = async () => {
    const identifier = inviteIdentifier.trim()
    if (!identifier || !activeWorkspaceId) return
    setInviteSubmitting(true)
    setInviteError('')
    try {
      await chatService.addMember(activeWorkspaceId, identifier)
      setInviteOpen(false)
      setInviteIdentifier('')
      showSnackbar('Member added')
      loadMembers()
    } catch (err) {
      setInviteError(err?.detail || 'Could not add member')
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

  return (
    <>
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
          </Tabs>

          {/* Profile Tab */}
          <TabPanel value={tab} index={0}>
            <div className="flex items-center gap-6 mb-8">
              <Avatar sx={{ width: 56, height: 56, bgcolor: 'primary.light', color: 'primary.main', fontSize: 22, fontWeight: 600 }}>
                {getInitials()}
              </Avatar>
              <div>
                <p className="text-sm font-semibold text-ink">{user?.name || user?.username || '—'}</p>
                <p className="text-xs text-ink-tertiary">{user?.email || ''}</p>
              </div>
            </div>

            <h3 className="text-[15px] font-semibold text-ink mb-4">Personal information</h3>
            <div className="grid grid-cols-2 gap-4 mb-8">
              <div className="col-span-2">
                <TextField label="Full name" value={user?.name || ''} fullWidth disabled />
              </div>
              <TextField label="Username" value={user?.username || ''} disabled />
              <TextField label="Email" value={user?.email || ''} disabled />
            </div>

            <h3 className="text-[15px] font-semibold text-ink mb-4">Change password</h3>
            <div className="grid grid-cols-1 gap-4 mb-6">
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
                disabled={settingsLoading || !currentPassword || !newPassword}
                startIcon={settingsLoading ? <CircularProgress size={14} color="inherit" /> : null}
                onClick={handleChangePassword}
              >
                Update password
              </Button>
            </div>
          </TabPanel>

          {/* Workspace Tab */}
          <TabPanel value={tab} index={1}>
            {!activeWorkspaceId ? (
              <Alert severity="info">Create or select a workspace to manage its members.</Alert>
            ) : (
              <>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-[15px] font-semibold text-ink">
                    Members{members.length ? ` (${members.length})` : ''}
                    {activeWorkspace?.name ? <span className="text-ink-tertiary font-normal"> · {activeWorkspace.name}</span> : null}
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
                          <Avatar sx={{ width: 32, height: 32, fontSize: 12, fontWeight: 600 }}>{initialsOf(m.name)}</Avatar>
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-ink truncate">
                              {m.name}
                              {m.id === user?.id ? <span className="text-ink-tertiary font-normal"> (you)</span> : null}
                            </p>
                            <p className="text-xs text-ink-tertiary truncate">{m.email || `@${m.username}`}</p>
                          </div>
                        </div>
                        {m.is_owner ? (
                          <Chip label="Owner" size="small" sx={{ color: 'var(--amber)', bgcolor: 'rgba(196,145,58,0.10)', fontWeight: 600 }} />
                        ) : (
                          <Chip label="Member" size="small" variant="outlined" />
                        )}
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

                <Dialog open={inviteOpen} onClose={() => setInviteOpen(false)} maxWidth="xs" fullWidth>
                  <DialogTitle>Add member</DialogTitle>
                  <DialogContent>
                    <p className="text-sm text-ink-secondary mb-3">
                      Enter the email address or username of an existing account to add them to this workspace.
                    </p>
                    {inviteError && <Alert severity="error" sx={{ mb: 2 }}>{inviteError}</Alert>}
                    <TextField
                      autoFocus label="Email or username" fullWidth variant="outlined"
                      value={inviteIdentifier} onChange={(e) => setInviteIdentifier(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && inviteIdentifier.trim() && handleInviteSend()}
                    />
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={() => setInviteOpen(false)}>Cancel</Button>
                    <Button
                      variant="contained"
                      disabled={!inviteIdentifier.trim() || inviteSubmitting}
                      startIcon={inviteSubmitting ? <CircularProgress size={14} color="inherit" /> : null}
                      onClick={handleInviteSend}
                    >
                      Add
                    </Button>
                  </DialogActions>
                </Dialog>
              </>
            )}
          </TabPanel>

          {/* Access & authorization */}
          <TabPanel value={tab} index={2}>
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-[15px] font-semibold text-ink">Access &amp; roles</h3>
              {isOwner && <Chip label="Owner" size="small" sx={{ color: 'var(--amber)', bgcolor: 'rgba(196,145,58,0.10)', fontWeight: 600 }} />}
            </div>
            <p className="text-[13px] text-ink-secondary mb-4">
              Your effective permissions{activeWorkspace?.name ? ` in ${activeWorkspace.name}` : ''}. These are enforced server-side on every request.
            </p>

            {!activeWorkspaceId ? (
              <Alert severity="info">Create or select a workspace to view your access.</Alert>
            ) : permsLoading ? (
              <div className="flex justify-center py-10"><CircularProgress size={22} /></div>
            ) : permsError ? (
              <Alert severity="error">{permsError}</Alert>
            ) : perms.length === 0 ? (
              <p className="text-[13px] text-ink-tertiary">No permissions granted in this workspace.</p>
            ) : (
              <div className="border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden">
                {perms.map((p, i) => (
                  <div key={`${p.resource}:${p.action}:${p.scope}`} className={`flex items-center gap-3 p-3 px-4 ${i < perms.length - 1 ? 'border-b border-[rgba(28,27,26,0.06)]' : ''}`}>
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
