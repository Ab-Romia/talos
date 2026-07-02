import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import Avatar from '@mui/material/Avatar'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import TextField from '@mui/material/TextField'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import MuiButton from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import {
  Hash, Plus, Search, ChevronDown, Settings, MessageSquare, FileText, LogOut, Layers,
} from 'lucide-react'
import { logout } from '../../store/authSlice'
import {
  createWorkspace,
  createChatroom,
  switchWorkspace,
  setActiveChatroom,
  clearWorkspaceError,
} from '../../store/workspaceSlice'
import * as R from '../../constants/Routes'

export default function Sidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const currentPath = location.pathname

  const {
    workspaces, chatrooms, activeWorkspaceId, activeChatroomId, loading, error,
  } = useSelector((s) => s.workspace)
  const user = useSelector((s) => s.auth.user)

  const [searchQuery, setSearchQuery] = useState('')
  const [workspaceAnchor, setWorkspaceAnchor] = useState(null)
  const [createChannelOpen, setCreateChannelOpen] = useState(false)
  const [createWorkspaceOpen, setCreateWorkspaceOpen] = useState(false)
  const [channelName, setChannelName] = useState('')
  const [newWorkspaceName, setNewWorkspaceName] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId)
  const query = searchQuery.toLowerCase()
  const filteredChannels = chatrooms.filter((ch) =>
    (ch.name || '').toLowerCase().includes(query),
  )

  const handleWorkspaceClick = (e) => setWorkspaceAnchor(e.currentTarget)
  const handleWorkspaceClose = () => setWorkspaceAnchor(null)

  const handleSignOut = () => {
    handleWorkspaceClose()
    dispatch(logout())
  }

  const handleSelectWorkspace = async (id) => {
    handleWorkspaceClose()
    if (id === activeWorkspaceId) return
    await dispatch(switchWorkspace(id))
  }

  const handleCreateChannel = async () => {
    if (!channelName.trim() || !activeWorkspaceId) return
    setSubmitting(true)
    const res = await dispatch(createChatroom({ workspaceId: activeWorkspaceId, name: channelName.trim() }))
    setSubmitting(false)
    if (createChatroom.fulfilled.match(res)) {
      setChannelName('')
      setCreateChannelOpen(false)
      navigate(R.CHAT_PAGE)
    }
  }

  const handleCreateWorkspace = async () => {
    if (!newWorkspaceName.trim()) return
    setSubmitting(true)
    const res = await dispatch(createWorkspace(newWorkspaceName.trim()))
    setSubmitting(false)
    if (createWorkspace.fulfilled.match(res)) {
      setNewWorkspaceName('')
      setCreateWorkspaceOpen(false)
      navigate(R.CHAT_PAGE)
    }
  }

  const handleSelectChatroom = (id) => {
    dispatch(setActiveChatroom(id))
    navigate(R.CHAT_PAGE)
  }

  const navItems = [
    { label: 'Chat', path: R.CHAT_PAGE, icon: MessageSquare },
    { label: 'Documents', path: R.DOCUMENTS, icon: FileText },
    { label: 'Settings', path: R.SETTINGS, icon: Settings },
  ]

  const workspaceInitial = (activeWorkspace?.name || 'W').charAt(0).toUpperCase()
  const userName = user?.name || user?.username || ''
  const userInitials = userName
    ? userName.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()
    : 'U'

  return (
    <aside className="w-[260px] bg-surface-2 border-r border-[rgba(28,27,26,0.08)] flex flex-col shrink-0">
      {/* Workspace selector */}
      <button
        className="flex items-center justify-between px-4 py-3 mx-3 mt-3 rounded-lg hover:bg-surface-3 transition-colors"
        onClick={handleWorkspaceClick}
      >
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-amber rounded-lg flex items-center justify-center text-white text-sm font-bold shadow-sm">
            {workspaceInitial}
          </div>
          <div className="text-left">
            <span className="text-sm font-semibold text-ink block leading-tight">
              {activeWorkspace?.name || (loading ? 'Loading…' : 'No workspace')}
            </span>
            <span className="text-[11px] text-ink-tertiary">
              {workspaces.length} workspace{workspaces.length === 1 ? '' : 's'}
            </span>
          </div>
        </div>
        <ChevronDown size={14} className="text-ink-tertiary" />
      </button>

      <Menu anchorEl={workspaceAnchor} open={Boolean(workspaceAnchor)} onClose={handleWorkspaceClose}>
        {workspaces.map((ws) => (
          <MenuItem
            key={ws.id}
            selected={ws.id === activeWorkspaceId}
            onClick={() => handleSelectWorkspace(ws.id)}
          >
            <Layers size={14} style={{ marginRight: 8 }} /> {ws.name}
          </MenuItem>
        ))}
        <MenuItem onClick={() => { handleWorkspaceClose(); setCreateWorkspaceOpen(true) }}>
          <Plus size={14} style={{ marginRight: 8 }} /> Create workspace
        </MenuItem>
        <MenuItem onClick={handleSignOut}>
          <LogOut size={14} style={{ marginRight: 8 }} /> Sign out
        </MenuItem>
      </Menu>

      {error && (
        <Alert
          severity="error"
          onClose={() => dispatch(clearWorkspaceError())}
          sx={{ mx: 1.5, mb: 1, fontSize: 12 }}
        >
          {error}
        </Alert>
      )}

      {/* Search */}
      <div className="mx-3 mt-3 mb-4">
        <div className="flex items-center gap-2 h-8 bg-base border border-[rgba(28,27,26,0.08)] rounded-lg px-2.5">
          <Search size={14} className="text-ink-muted shrink-0" />
          <input
            type="text"
            placeholder="Search channels..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-transparent border-none text-[13px] text-ink outline-none w-full placeholder:text-ink-muted"
          />
        </div>
      </div>

      {/* Scrollable nav area */}
      <div className="flex-1 overflow-y-auto px-3">
        {/* Channels */}
        <SectionHeader label="Channels" onAdd={() => setCreateChannelOpen(true)} />
        <ul className="list-none mb-4">
          {loading && !chatrooms.length && (
            <li className="px-2.5 py-2 text-[12px] text-ink-tertiary flex items-center gap-2">
              <CircularProgress size={12} /> Loading…
            </li>
          )}
          {!loading && filteredChannels.length === 0 && (
            <li className="px-2.5 py-2 text-[12px] text-ink-tertiary">
              {chatrooms.length === 0 ? 'No channels yet' : 'No matches'}
            </li>
          )}
          {filteredChannels.map((ch) => (
            <NavItem
              key={ch.id}
              icon={<Hash size={15} />}
              label={ch.name}
              active={ch.id === activeChatroomId && currentPath === R.CHAT_PAGE}
              onClick={() => handleSelectChatroom(ch.id)}
            />
          ))}
        </ul>
      </div>

      {/* Quick nav - pinned to bottom */}
      <div className="px-3 py-2 border-t border-[rgba(28,27,26,0.06)]">
        {navItems.map((item) => (
          <button
            key={item.path}
            onClick={() => navigate(item.path)}
            className={`flex items-center gap-2.5 w-full h-9 px-2.5 rounded-lg text-[13px] font-medium transition-colors mb-0.5 ${
              currentPath === item.path
                ? 'bg-amber-subtle text-amber'
                : 'text-ink-secondary hover:bg-surface-3'
            }`}
          >
            <item.icon size={16} />
            {item.label}
          </button>
        ))}
      </div>

      {/* User footer */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-[rgba(28,27,26,0.06)]">
        <div className="flex items-center gap-2.5">
          <Avatar sx={{ width: 30, height: 30, bgcolor: 'primary.light', color: 'primary.main', fontSize: 12, fontWeight: 600 }}>
            {userInitials}
          </Avatar>
          <span className="text-[13px] font-medium text-ink truncate max-w-[140px]">
            {userName || 'Signed in'}
          </span>
        </div>
        <Tooltip title="Settings">
          <IconButton size="small" onClick={() => navigate(R.SETTINGS)} sx={{ color: 'text.secondary' }}>
            <Settings size={15} />
          </IconButton>
        </Tooltip>
      </div>

      {/* Create Channel Dialog */}
      <Dialog open={createChannelOpen} onClose={() => setCreateChannelOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Create channel</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Channel name"
            placeholder="e.g. team-updates"
            fullWidth
            variant="outlined"
            value={channelName}
            onChange={(e) => setChannelName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreateChannel()}
          />
        </DialogContent>
        <DialogActions>
          <MuiButton onClick={() => setCreateChannelOpen(false)}>Cancel</MuiButton>
          <MuiButton
            onClick={handleCreateChannel}
            variant="contained"
            disabled={!channelName.trim() || submitting}
            startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : null}
          >
            Create
          </MuiButton>
        </DialogActions>
      </Dialog>

      {/* Create Workspace Dialog */}
      <Dialog open={createWorkspaceOpen} onClose={() => setCreateWorkspaceOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Create workspace</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Workspace name"
            placeholder="e.g. Alex Uni"
            fullWidth
            variant="outlined"
            value={newWorkspaceName}
            onChange={(e) => setNewWorkspaceName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreateWorkspace()}
          />
        </DialogContent>
        <DialogActions>
          <MuiButton onClick={() => setCreateWorkspaceOpen(false)}>Cancel</MuiButton>
          <MuiButton
            onClick={handleCreateWorkspace}
            variant="contained"
            disabled={!newWorkspaceName.trim() || submitting}
            startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : null}
          >
            Create
          </MuiButton>
        </DialogActions>
      </Dialog>
    </aside>
  )
}

function SectionHeader({ label, onAdd }) {
  return (
    <div className="flex items-center justify-between mb-1 px-2.5">
      <span className="text-[11px] font-semibold text-ink-tertiary uppercase tracking-[0.06em]">{label}</span>
      <button
        onClick={onAdd}
        className="w-5 h-5 flex items-center justify-center rounded text-ink-tertiary hover:bg-surface-3 hover:text-ink-secondary transition-colors"
      >
        <Plus size={13} />
      </button>
    </div>
  )
}

function NavItem({ icon, label, active, onClick }) {
  return (
    <li
      className={`flex items-center gap-2.5 h-8 px-2.5 rounded-lg cursor-pointer transition-colors mb-0.5 ${
        active ? 'bg-amber-subtle text-amber' : 'text-ink-secondary hover:bg-surface-3'
      }`}
      onClick={onClick}
    >
      <span className="text-ink-tertiary w-4 text-center shrink-0">{icon}</span>
      <span className="text-[13px] font-medium flex-1 truncate">{label}</span>
    </li>
  )
}
