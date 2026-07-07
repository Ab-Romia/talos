import { useState, useRef, useEffect, useCallback } from 'react'
import TextField from '@mui/material/TextField'
import CircularProgress from '@mui/material/CircularProgress'
import { chatService } from '../../services/chat'

// Shared user-search autocomplete used by both workspace onboarding and workspace
// settings so "add members" behaves identically in both places (debounced search,
// keyboard nav, excludes already-added users). Calls onSelect(user) on pick.
export default function MemberSearchAutocomplete({
  excludeIds = [],
  onSelect,
  placeholder = 'Search by username or email',
  autoFocus = false,
}) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [loading, setLoading] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState(-1)
  const [showDropdown, setShowDropdown] = useState(false)

  const debounceRef = useRef(null)
  const dropdownRef = useRef(null)
  const rootRef = useRef(null)
  const excludeRef = useRef(excludeIds)
  excludeRef.current = excludeIds

  const search = useCallback((q) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (q.length < 2) {
      setSuggestions([])
      setShowDropdown(false)
      return
    }
    setLoading(true)
    debounceRef.current = setTimeout(async () => {
      try {
        const results = await chatService.searchUsers(q)
        const excluded = new Set((excludeRef.current || []).map(String))
        setSuggestions((results || []).filter((u) => !excluded.has(String(u.id))))
        setShowDropdown(true)
        setHighlightIdx(-1)
      } catch {
        setSuggestions([])
      } finally {
        setLoading(false)
      }
    }, 250)
  }, [])

  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current) }, [])

  useEffect(() => {
    const onDoc = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setShowDropdown(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const pick = (u) => {
    onSelect?.(u)
    setQuery('')
    setSuggestions([])
    setShowDropdown(false)
    setHighlightIdx(-1)
    rootRef.current?.querySelector('input')?.focus()
  }

  const onKeyDown = (e) => {
    if (!showDropdown || !suggestions.length) {
      if (e.key === 'Escape') setShowDropdown(false)
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIdx((p) => (p + 1) % suggestions.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIdx((p) => (p <= 0 ? suggestions.length - 1 : p - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (highlightIdx >= 0 && highlightIdx < suggestions.length) pick(suggestions[highlightIdx])
    } else if (e.key === 'Escape') {
      setShowDropdown(false)
    }
  }

  return (
    <div className="relative" ref={rootRef}>
      <TextField
        autoFocus={autoFocus}
        fullWidth
        size="small"
        placeholder={placeholder}
        value={query}
        onChange={(e) => { setQuery(e.target.value); search(e.target.value) }}
        onFocus={() => { if (suggestions.length) setShowDropdown(true) }}
        onKeyDown={onKeyDown}
        InputProps={{ endAdornment: loading ? <CircularProgress size={16} /> : null }}
      />

      {showDropdown && suggestions.length > 0 && (
        <div
          ref={dropdownRef}
          className="absolute z-[1400] left-0 right-0 mt-1 bg-surface-1 border border-[rgba(28,27,26,0.12)] rounded-lg shadow-lg overflow-hidden max-h-[200px] overflow-y-auto"
        >
          {suggestions.map((u, i) => (
            <button
              key={u.id}
              type="button"
              className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                i === highlightIdx ? 'bg-amber/10' : 'hover:bg-surface-2'
              }`}
              onMouseDown={(e) => { e.preventDefault(); pick(u) }}
              onMouseEnter={() => setHighlightIdx(i)}
            >
              <div className="w-7 h-7 rounded-full bg-surface-2 flex items-center justify-center text-[12px] font-semibold text-ink-secondary shrink-0">
                {(u.name || u.username)[0].toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="text-[13px] font-medium text-ink truncate">{u.name || u.username}</p>
                <p className="text-[11px] text-ink-tertiary truncate">@{u.username} &middot; {u.email}</p>
              </div>
            </button>
          ))}
        </div>
      )}

      {showDropdown && !loading && query.length >= 2 && suggestions.length === 0 && (
        <div className="absolute z-[1400] left-0 right-0 mt-1 bg-surface-1 border border-[rgba(28,27,26,0.12)] rounded-lg shadow-lg px-3 py-3">
          <p className="text-[13px] text-ink-tertiary">No users found matching &ldquo;{query}&rdquo;</p>
        </div>
      )}
    </div>
  )
}
