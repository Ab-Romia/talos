import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useDispatch } from 'react-redux'
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
import {
  Hash, Lock, Plus, Search, ChevronDown, Settings, MessageSquare, FileText, Bot,
} from 'lucide-react'
import { logout } from '../../store/authSlice'
import * as R from '../../constants/Routes'

const channels = [
  { name: 'general', icon: Hash },
  { name: 'announcements', icon: Hash },
  { name: 'projects', icon: Hash },
  { name: 'resources', icon: Hash },
  { name: 'private-notes', icon: Lock },
]

const directMessages = [
  { name: 'Mohab Sherif', initials: 'MS', online: true },
  { name: 'Kyrollos Youssef', initials: 'KY', online: false },
  { name: 'Talos AI', initials: 'T', isAI: true, online: true },
]

export default function Sidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const currentPath = location.pathname

  const [searchQuery, setSearchQuery] = useState('')
  const [workspaceAnchor, setWorkspaceAnchor] = useState(null)
  const [createChannelOpen, setCreateChannelOpen] = useState(false)
  const [newMessageOpen, setNewMessageOpen] = useState(false)
  const [channelName, setChannelName] = useState('')
  const [messageText, setMessageText] = useState('')
  const [messageRecipient, setMessageRecipient] = useState('')

  const navItems = [
    { label: 'Chat', path: R.CHAT_PAGE, icon: MessageSquare },
    { label: 'Documents', path: R.DOCUMENTS, icon: FileText },
    { label: 'Settings', path: R.SETTINGS, icon: Settings },
  ]

  const query = searchQuery.toLowerCase()
  const filteredChannels = channels.filter((ch) => ch.name.toLowerCase().includes(query))
  const filteredDMs = directMessages.filter((dm) => dm.name.toLowerCase().includes(query))

  const handleWorkspaceClick = (e) => setWorkspaceAnchor(e.currentTarget)
  const handleWorkspaceClose = () => setWorkspaceAnchor(null)

  const handleSignOut = () => {
    handleWorkspaceClose()
    dispatch(logout())
  }

  const handleCreateChannel = () => {
    setChannelName('')
    setCreateChannelOpen(false)
  }

  const handleSendMessage = () => {
    setMessageText('')
    setMessageRecipient('')
    setNewMessageOpen(false)
  }

  return (
    <aside className="w-[260px] bg-surface-2 border-r border-[rgba(28,27,26,0.08)] flex flex-col shrink-0">
      {/* Workspace selector */}
      <button
        className="flex items-center justify-between px-4 py-3 mx-3 mt-3 rounded-lg hover:bg-surface-3 transition-colors"
        onClick={handleWorkspaceClick}
      >
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-amber rounded-lg flex items-center justify-center text-white text-sm font-bold shadow-sm">A</div>
          <div className="text-left">
            <span className="text-sm font-semibold text-ink block leading-tight">Alex Uni</span>
            <span className="text-[11px] text-ink-tertiary">7 members</span>
          </div>
        </div>
        <ChevronDown size={14} className="text-ink-tertiary" />
      </button>

      <Menu anchorEl={workspaceAnchor} open={Boolean(workspaceAnchor)} onClose={handleWorkspaceClose}>
        <MenuItem selected onClick={handleWorkspaceClose}>Alex Uni</MenuItem>
        <MenuItem onClick={handleWorkspaceClose}>Create workspace</MenuItem>
        <MenuItem onClick={handleSignOut}>Sign out</MenuItem>
      </Menu>

      {/* Search */}
      <div className="mx-3 mt-3 mb-4">
        <div className="flex items-center gap-2 h-8 bg-base border border-[rgba(28,27,26,0.08)] rounded-lg px-2.5">
          <Search size={14} className="text-ink-muted shrink-0" />
          <input
            type="text"
            placeholder="Search..."
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
          {filteredChannels.map((ch) => (
            <NavItem key={ch.name} icon={<ch.icon size={15} />} label={ch.name} onClick={() => navigate(R.CHAT_PAGE)} />
          ))}
        </ul>

        {/* Direct Messages */}
        <SectionHeader label="Direct Messages" onAdd={() => setNewMessageOpen(true)} />
        <ul className="list-none mb-4">
          {filteredDMs.map((dm) => (
            <li
              key={dm.name}
              className={`flex items-center gap-2.5 h-9 px-2.5 rounded-lg cursor-pointer transition-colors mb-0.5 ${
                dm.isAI && currentPath === R.CHAT_PAGE
                  ? 'bg-amber-subtle text-amber'
                  : 'hover:bg-surface-3 text-ink-secondary'
              }`}
              onClick={() => navigate(R.CHAT_PAGE)}
            >
              <div className="relative">
                <Avatar
                  sx={{
                    width: 24, height: 24, fontSize: 11,
                    bgcolor: dm.isAI ? 'primary.light' : '#EEEDEA',
                    color: dm.isAI ? 'primary.main' : 'text.secondary',
                    border: dm.isAI ? '1.5px solid' : 'none',
                    borderColor: dm.isAI ? 'rgba(196,145,58,0.4)' : 'transparent',
                  }}
                >
                  {dm.initials}
                </Avatar>
                {dm.online && (
                  <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 bg-success rounded-full border-2 border-surface-2" />
                )}
              </div>
              <span className={`text-[13px] ${dm.isAI && currentPath === R.CHAT_PAGE ? 'font-semibold' : 'font-medium'}`}>
                {dm.name}
              </span>
            </li>
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
            AM
          </Avatar>
          <span className="text-[13px] font-medium text-ink">Abdelrahman Mashaal</span>
        </div>
        <Tooltip title="Settings">
          <IconButton size="small" onClick={() => navigate(R.SETTINGS)} sx={{ color: 'text.secondary' }}>
            <Settings size={15} />
          </IconButton>
        </Tooltip>
      </div>

      {/* Create Channel Dialog */}
      <Dialog open={createChannelOpen} onClose={() => setCreateChannelOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Create Channel</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Channel name"
            fullWidth
            variant="outlined"
            value={channelName}
            onChange={(e) => setChannelName(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <MuiButton onClick={() => setCreateChannelOpen(false)}>Cancel</MuiButton>
          <MuiButton onClick={handleCreateChannel} variant="contained">Create</MuiButton>
        </DialogActions>
      </Dialog>

      {/* New Message Dialog */}
      <Dialog open={newMessageOpen} onClose={() => setNewMessageOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>New Message</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="To"
            placeholder="e.g. Mohab Sherif"
            fullWidth
            variant="outlined"
            value={messageRecipient}
            onChange={(e) => setMessageRecipient(e.target.value)}
          />
          <TextField
            margin="dense"
            label="Message"
            fullWidth
            variant="outlined"
            multiline
            rows={3}
            value={messageText}
            onChange={(e) => setMessageText(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <MuiButton onClick={() => setNewMessageOpen(false)}>Cancel</MuiButton>
          <MuiButton onClick={handleSendMessage} variant="contained">Send</MuiButton>
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

function NavItem({ icon, label, active, badge, onClick }) {
  return (
    <li
      className={`flex items-center gap-2.5 h-8 px-2.5 rounded-lg cursor-pointer transition-colors mb-0.5 ${
        active ? 'bg-amber-subtle text-amber' : 'text-ink-secondary hover:bg-surface-3'
      }`}
      onClick={onClick}
    >
      <span className="text-ink-tertiary w-4 text-center shrink-0">{icon}</span>
      <span className="text-[13px] font-medium flex-1 truncate">{label}</span>
      {badge && (
        <span className="text-[11px] font-semibold bg-amber text-white px-1.5 rounded-full min-w-[18px] text-center">
          {badge}
        </span>
      )}
    </li>
  )
}
