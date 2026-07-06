import { useOutletContext } from 'react-router-dom'
import Tooltip from '@mui/material/Tooltip'
import { PanelLeft } from 'lucide-react'

// Renders the open/close sidebar button. Reads the toggle from the AppLayout
// outlet context, so any page can drop it into its header.
export default function SidebarToggle({ className = '' }) {
  const ctx = useOutletContext() || {}
  const { toggleSidebar, sidebarOpen } = ctx
  if (!toggleSidebar) return null
  return (
    <Tooltip title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}>
      <button
        type="button"
        onClick={toggleSidebar}
        aria-label="Toggle sidebar"
        className={`w-8 h-8 flex items-center justify-center rounded-lg text-ink-secondary hover:bg-surface-3 transition-colors shrink-0 ${className}`}
      >
        <PanelLeft size={17} />
      </button>
    </Tooltip>
  )
}
