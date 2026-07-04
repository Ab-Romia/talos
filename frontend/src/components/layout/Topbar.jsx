import NotificationsBell from './NotificationsBell'

export default function Topbar() {
  return (
    <header className="h-12 shrink-0 border-b border-[rgba(28,27,26,0.08)] bg-surface-2 flex items-center justify-end px-4 gap-2">
      <NotificationsBell />
    </header>
  )
}
