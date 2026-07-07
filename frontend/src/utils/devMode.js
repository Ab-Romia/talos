// Persistent "Developer mode" preference. When on, AI answers in chat render
// their full RAG trace (RagTracePanel) under the reply. Toggled from Settings,
// read live by the chat page across tabs.
const KEY = 'talos:devMode'

export function getDevMode() {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function setDevMode(on) {
  try {
    localStorage.setItem(KEY, on ? '1' : '0')
  } catch {
    /* storage unavailable */
  }
  // Notify listeners in THIS tab (the `storage` event only fires in other tabs).
  window.dispatchEvent(new CustomEvent('talos:devmode', { detail: Boolean(on) }))
}

export function onDevModeChange(cb) {
  const local = (e) => cb(Boolean(e.detail))
  const cross = (e) => { if (e.key === KEY) cb(e.newValue === '1') }
  window.addEventListener('talos:devmode', local)
  window.addEventListener('storage', cross)
  return () => {
    window.removeEventListener('talos:devmode', local)
    window.removeEventListener('storage', cross)
  }
}
