import { useState, useRef, useEffect, useCallback } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import IconButton from '@mui/material/IconButton'
import CircularProgress from '@mui/material/CircularProgress'
import { Hash, Plus, X, ArrowLeft } from 'lucide-react'
import { createWorkspace } from '../../store/workspaceSlice'
import { chatService } from '../../services/chat'
import * as R from '../../constants/Routes'

const STEPS = [
  { title: 'Name your workspace', subtitle: 'A home for your team’s channels, conversations and documents.' },
  { title: 'Set up your channels', subtitle: 'Channels keep conversations organized by topic. Start with our defaults or make your own.' },
  { title: 'Invite your team', subtitle: 'Search for teammates by username or email. You can also do this later from workspace settings.' },
]
const DEFAULT_CHANNELS = ['general', 'random']

export default function OnboardingPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const user = useSelector((s) => s.auth.user)
  const workspaces = useSelector((s) => s.workspace.workspaces)

  const firstName = (user?.name || user?.username || '').split(' ')[0]
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [channels, setChannels] = useState(DEFAULT_CHANNELS)
  const [channelInput, setChannelInput] = useState('')
  const [members, setMembers] = useState([])
  const [memberQuery, setMemberQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState(-1)
  const [showDropdown, setShowDropdown] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const debounceRef = useRef(null)
  const dropdownRef = useRef(null)
  const inputRef = useRef(null)

  const clearError = () => { if (error) setError('') }

  const searchUsers = useCallback((query) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.length < 2) {
      setSuggestions([])
      setShowDropdown(false)
      return
    }
    setSuggestionsLoading(true)
    debounceRef.current = setTimeout(async () => {
      try {
        const results = await chatService.searchUsers(query)
        const alreadyAdded = new Set(members.map((m) => m.id))
        setSuggestions(results.filter((u) => !alreadyAdded.has(u.id)))
        setShowDropdown(true)
        setHighlightIdx(-1)
      } catch {
        setSuggestions([])
      } finally {
        setSuggestionsLoading(false)
      }
    }, 250)
  }, [members])

  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [])

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target) &&
          inputRef.current && !inputRef.current.contains(e.target)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const selectUser = (userObj) => {
    if (members.some((m) => m.id === userObj.id)) return
    setMembers([...members, userObj])
    setMemberQuery('')
    setSuggestions([])
    setShowDropdown(false)
    setHighlightIdx(-1)
    clearError()
    inputRef.current?.focus()
  }

  const removeMember = (id) => {
    setMembers(members.filter((m) => m.id !== id))
    clearError()
  }

  const handleMemberKeyDown = (e) => {
    if (!showDropdown || !suggestions.length) {
      if (e.key === 'Escape') setShowDropdown(false)
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIdx((prev) => (prev + 1) % suggestions.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIdx((prev) => (prev <= 0 ? suggestions.length - 1 : prev - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (highlightIdx >= 0 && highlightIdx < suggestions.length) {
        selectUser(suggestions[highlightIdx])
      }
    } else if (e.key === 'Escape') {
      setShowDropdown(false)
    }
  }

  const goToChannels = (e) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Give your workspace a name.')
      return
    }
    setError('')
    setStep(1)
  }

  const addChannel = () => {
    const cleaned = channelInput.trim().replace(/^#/, '')
    if (!cleaned) return
    if (channels.some((c) => c.toLowerCase() === cleaned.toLowerCase())) {
      setError(`#${cleaned} is already on the list.`)
      return
    }
    setChannels([...channels, cleaned])
    setChannelInput('')
    setError('')
  }

  const removeChannel = (channel) => {
    setChannels(channels.filter((c) => c !== channel))
    clearError()
  }

  const handleCreate = async () => {
    setSubmitting(true)
    setError('')
    const memberUsernames = members.map((m) => m.username)
    const result = await dispatch(createWorkspace({ name: name.trim(), channels, members: memberUsernames }))
    setSubmitting(false)
    if (createWorkspace.fulfilled.match(result)) {
      navigate(R.CHAT_PAGE, { replace: true })
    } else {
      setError(result.payload || 'Could not create workspace. Try a different name.')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-base p-6">
      <div className="w-full max-w-[460px]">
        <div className="flex items-center gap-3 mb-8 justify-center">
          <div className="w-9 h-9 bg-amber rounded-lg flex items-center justify-center text-white text-xl font-bold">T</div>
          <span className="text-3xl font-bold text-ink tracking-tight">Talos</span>
        </div>

        <div className="bg-surface-1 border border-[rgba(28,27,26,0.08)] rounded-2xl p-8 shadow-sm">
          {/* Step indicator */}
          <div className="flex items-center gap-2 mb-6">
            {STEPS.map((_, i) => (
              <div
                key={i}
                className={`h-1.5 flex-1 rounded-full transition-colors ${
                  i <= step ? 'bg-amber' : 'bg-surface-2'
                }`}
              />
            ))}
          </div>
          <p className="text-[12px] font-medium text-ink-tertiary uppercase tracking-wide mb-1">
            Step {step + 1} of {STEPS.length}
          </p>
          <h1 className="text-[22px] font-semibold text-ink tracking-tight mb-1">
            {step === 0 && firstName ? `Welcome, ${firstName}!` : STEPS[step].title}
          </h1>
          <p className="text-sm text-ink-secondary mb-6">{STEPS[step].subtitle}</p>

          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {/* Step 1: workspace name */}
          {step === 0 && (
            <form onSubmit={goToChannels}>
              <TextField
                autoFocus
                fullWidth
                label="Workspace name"
                placeholder="e.g. Acme Inc, Alex Uni, My Team"
                value={name}
                onChange={(e) => { setName(e.target.value); clearError() }}
                sx={{ mb: 3 }}
              />
              <Button type="submit" variant="contained" fullWidth disabled={!name.trim()}>
                Next: Channels
              </Button>
            </form>
          )}

          {/* Step 2: channels */}
          {step === 1 && (
            <>
              <div className="border border-[rgba(28,27,26,0.08)] rounded-lg overflow-hidden mb-3">
                {channels.map((channel, i) => (
                  <div
                    key={channel}
                    className={`flex items-center justify-between pl-3 pr-1.5 py-1.5 ${
                      i < channels.length - 1 ? 'border-b border-[rgba(28,27,26,0.06)]' : ''
                    }`}
                  >
                    <span className="flex items-center gap-2 text-sm text-ink">
                      <Hash size={14} className="text-ink-tertiary" /> {channel}
                    </span>
                    <IconButton
                      size="small"
                      aria-label={`Remove ${channel}`}
                      disabled={channels.length <= 1}
                      onClick={() => removeChannel(channel)}
                    >
                      <X size={15} />
                    </IconButton>
                  </div>
                ))}
              </div>

              <div className="flex gap-2 mb-1">
                <TextField
                  fullWidth
                  size="small"
                  placeholder="Add a channel, e.g. announcements"
                  value={channelInput}
                  onChange={(e) => { setChannelInput(e.target.value); clearError() }}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addChannel() } }}
                />
                <Button
                  variant="outlined"
                  onClick={addChannel}
                  disabled={!channelInput.trim()}
                  startIcon={<Plus size={15} />}
                  sx={{ flexShrink: 0 }}
                >
                  Add
                </Button>
              </div>
              <p className="text-[12px] text-ink-tertiary mb-5">
                You need at least one channel to get started.
              </p>

              <div className="flex gap-2">
                <Button variant="text" onClick={() => { setStep(0); setError('') }} startIcon={<ArrowLeft size={15} />}>
                  Back
                </Button>
                <Button variant="contained" fullWidth onClick={() => { setStep(2); setError('') }}>
                  Next: Invite people
                </Button>
              </div>
            </>
          )}

          {/* Step 3: invite members with autocomplete */}
          {step === 2 && (
            <>
              <div className="relative mb-3">
                <TextField
                  ref={inputRef}
                  autoFocus
                  fullWidth
                  size="small"
                  placeholder="Search by username or email"
                  value={memberQuery}
                  onChange={(e) => {
                    setMemberQuery(e.target.value)
                    searchUsers(e.target.value)
                    clearError()
                  }}
                  onFocus={() => { if (suggestions.length) setShowDropdown(true) }}
                  onKeyDown={handleMemberKeyDown}
                  InputProps={{
                    endAdornment: suggestionsLoading ? <CircularProgress size={16} /> : null,
                  }}
                />

                {showDropdown && suggestions.length > 0 && (
                  <div
                    ref={dropdownRef}
                    className="absolute z-50 left-0 right-0 mt-1 bg-surface-1 border border-[rgba(28,27,26,0.12)] rounded-lg shadow-lg overflow-hidden max-h-[200px] overflow-y-auto"
                  >
                    {suggestions.map((u, i) => (
                      <button
                        key={u.id}
                        type="button"
                        className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                          i === highlightIdx ? 'bg-amber/10' : 'hover:bg-surface-2'
                        }`}
                        onMouseDown={(e) => { e.preventDefault(); selectUser(u) }}
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

                {showDropdown && !suggestionsLoading && memberQuery.length >= 2 && suggestions.length === 0 && (
                  <div className="absolute z-50 left-0 right-0 mt-1 bg-surface-1 border border-[rgba(28,27,26,0.12)] rounded-lg shadow-lg px-3 py-3">
                    <p className="text-[13px] text-ink-tertiary">No users found matching &ldquo;{memberQuery}&rdquo;</p>
                  </div>
                )}
              </div>

              {members.length > 0 ? (
                <div className="border border-[rgba(28,27,26,0.08)] rounded-lg overflow-hidden mb-5">
                  {members.map((member, i) => (
                    <div
                      key={member.id}
                      className={`flex items-center justify-between pl-3 pr-1.5 py-2 ${
                        i < members.length - 1 ? 'border-b border-[rgba(28,27,26,0.06)]' : ''
                      }`}
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="w-7 h-7 rounded-full bg-surface-2 flex items-center justify-center text-[12px] font-semibold text-ink-secondary shrink-0">
                          {(member.name || member.username)[0].toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="text-[13px] font-medium text-ink truncate">{member.name || member.username}</p>
                          <p className="text-[11px] text-ink-tertiary truncate">@{member.username}</p>
                        </div>
                      </div>
                      <IconButton size="small" aria-label={`Remove ${member.username}`} onClick={() => removeMember(member.id)}>
                        <X size={15} />
                      </IconButton>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[12px] text-ink-tertiary mb-5">
                  No one added yet — this step is optional.
                </p>
              )}

              <div className="flex gap-2">
                <Button variant="text" onClick={() => { setStep(1); setError(''); setShowDropdown(false) }} startIcon={<ArrowLeft size={15} />} disabled={submitting}>
                  Back
                </Button>
                <Button
                  variant="contained"
                  fullWidth
                  onClick={handleCreate}
                  disabled={submitting}
                  startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : null}
                >
                  {submitting ? 'Creating…' : members.length ? 'Create workspace & invite' : 'Create workspace'}
                </Button>
              </div>
            </>
          )}

          {workspaces.length > 0 && (
            <button
              onClick={() => navigate(R.CHAT_PAGE, { replace: true })}
              className="w-full text-center text-sm text-ink-tertiary hover:text-ink-secondary mt-4"
            >
              Skip — go to my existing workspace
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
