import { useState, useRef } from 'react'
import Tabs from '@mui/material/Tabs'
import Tab from '@mui/material/Tab'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Avatar from '@mui/material/Avatar'
import Switch from '@mui/material/Switch'
import Chip from '@mui/material/Chip'
import Snackbar from '@mui/material/Snackbar'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import { Upload } from 'lucide-react'

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

const INITIAL_SESSIONS = [
  { id: 1, device: 'Chrome on Windows', location: 'New York, US · Active now', current: true },
  { id: 2, device: 'Safari on iPhone', location: 'Cairo, EG · Last active 3 hours ago', current: false },
]

const INITIAL_ACCOUNTS = [
  { name: 'Google', email: 'abdelrahman@gmail.com', connected: true },
  { name: 'GitHub', email: null, connected: false },
]

export default function SettingsPage() {
  const [tab, setTab] = useState(0)


  const [snackbar, setSnackbar] = useState({ open: false, message: '' })
  const showSnackbar = (message) => setSnackbar({ open: true, message })


  const [firstName, setFirstName] = useState('Abdelrahman')
  const [lastName, setLastName] = useState('Mashaal')
  const [email, setEmail] = useState('abdelrahman@alexuni.edu')
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


  const [twoFaEnabled, setTwoFaEnabled] = useState(true)
  const [sessions, setSessions] = useState(INITIAL_SESSIONS)
  const [accounts, setAccounts] = useState(INITIAL_ACCOUNTS)


  const [model, setModel] = useState('gpt-4o')
  const [chunkSize, setChunkSize] = useState(512)
  const [chunkOverlap, setChunkOverlap] = useState(50)
  const [topK, setTopK] = useState(5)


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
    return (f + l).toUpperCase() || 'AA'
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


  const handleRevokeSession = (id) => {
    setSessions((prev) => prev.filter((s) => s.id !== id))
    showSnackbar('Session revoked')
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
          <Tabs
            value={tab}
            onChange={(_, v) => setTab(v)}
            sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}
          >
            <Tab label="Profile" />
            <Tab label="Workspace" />
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

            <div className="flex justify-end pt-6 border-t border-[rgba(28,27,26,0.06)]">
              <Button variant="contained" onClick={() => showSnackbar('Profile updated successfully')}>Save changes</Button>
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

            <Menu
              anchorEl={roleAnchorEl}
              open={Boolean(roleAnchorEl)}
              onClose={() => setRoleAnchorEl(null)}
            >
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

            {/* Invite Dialog */}
            <Dialog open={inviteOpen} onClose={() => setInviteOpen(false)} maxWidth="xs" fullWidth>
              <DialogTitle>Invite member</DialogTitle>
              <DialogContent>
                <TextField
                  autoFocus
                  label="Email address"
                  type="email"
                  fullWidth
                  variant="outlined"
                  sx={{ mt: 1 }}
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setInviteOpen(false)}>Cancel</Button>
                <Button variant="contained" onClick={handleInviteSend}>Send invite</Button>
              </DialogActions>
            </Dialog>

            {/* Delete Confirmation Dialog */}
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

          {/* Security Tab */}
          <TabPanel value={tab} index={2}>
            <div className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-4 flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-subtle flex items-center justify-center text-amber">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                </div>
                <div>
                  <p className="text-sm font-semibold text-ink">Two-factor authentication</p>
                  <p className="text-[13px] text-ink-secondary">Add an extra layer of security to your account</p>
                </div>
              </div>
              <Switch
                checked={twoFaEnabled}
                onChange={(e) => {
                  const enabled = e.target.checked
                  setTwoFaEnabled(enabled)
                  showSnackbar(`Two-factor authentication ${enabled ? 'enabled' : 'disabled'}`)
                }}
                color="primary"
              />
            </div>

            <h3 className="text-[15px] font-semibold text-ink mb-4">Active sessions</h3>
            <div className="space-y-2 mb-8">
              {sessions.map((s) => (
                <div key={s.id} className="bg-surface-1 border border-[rgba(28,27,26,0.06)] rounded-lg p-3 px-4 flex items-center gap-3">
                  <div className="flex-1">
                    <p className="text-sm font-medium text-ink">{s.device}</p>
                    <p className="text-xs text-ink-tertiary">{s.location}</p>
                  </div>
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
              ))}
            </div>

            <h3 className="text-[15px] font-semibold text-ink mb-4">Connected accounts</h3>
            {accounts.map((a) => (
              <div key={a.name} className="flex items-center gap-3 py-3 border-b border-[rgba(28,27,26,0.06)] last:border-b-0">
                <div className="w-8 h-8 rounded-md bg-surface-2 flex items-center justify-center text-sm font-bold">{a.name[0]}</div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-ink">{a.name}</p>
                  {a.email && <p className="text-xs text-ink-tertiary">{a.email}</p>}
                </div>
                {a.connected ? (
                  <Chip label="Connected" color="success" size="small" />
                ) : (
                  <Button
                    variant="text"
                    size="small"
                    color="primary"
                    onClick={() => showSnackbar('GitHub connection coming soon')}
                  >
                    Connect
                  </Button>
                )}
              </div>
            ))}
          </TabPanel>

          {/* Configuration Tab */}
          <TabPanel value={tab} index={3}>
            <h3 className="text-[15px] font-semibold text-ink mb-1">AI Configuration</h3>
            <p className="text-[13px] text-ink-secondary mb-4">Configure how Talos processes and retrieves information</p>

            <div className="grid grid-cols-1 gap-4 mb-8">
              <TextField label="Model" select value={model} onChange={(e) => setModel(e.target.value)} SelectProps={{ native: true }}>
                <option value="gpt-4o">gpt-4o</option>
                <option value="gpt-4o-mini">gpt-4o-mini</option>
                <option value="gpt-3.5-turbo">gpt-3.5-turbo</option>
              </TextField>

              <div className="grid grid-cols-2 gap-4">
                <TextField label="Chunk size (tokens)" type="number" value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))} />
                <TextField label="Chunk overlap" type="number" value={chunkOverlap} onChange={(e) => setChunkOverlap(Number(e.target.value))} />
              </div>

              <TextField label="Top K results" type="number" value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
            </div>

            <div className="flex justify-end pt-6 border-t border-[rgba(28,27,26,0.06)]">
              <Button variant="contained" onClick={() => showSnackbar('Configuration saved successfully')}>Save configuration</Button>
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
