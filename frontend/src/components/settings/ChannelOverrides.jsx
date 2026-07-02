import { useState, useEffect, useCallback } from 'react'
import Button from '@mui/material/Button'
import ButtonGroup from '@mui/material/ButtonGroup'
import CircularProgress from '@mui/material/CircularProgress'
import { ChevronDown, ChevronRight, Hash } from 'lucide-react'
import { permissionsService } from '../../services/permissions'

const CHANNEL_PERMISSIONS = [
  { resource: 'channel', action: 'view', label: 'View channel' },
  { resource: 'channel.message', action: 'view_history', label: 'View history' },
  { resource: 'channel.message', action: 'send', label: 'Send messages' },
  { resource: 'channel.member', action: 'view_presence', label: 'View presence' },
]

function permKey(resource, action) {
  return `${resource}:${action}`
}

function permToApiStr(resource, action, scope = 0) {
  return `${resource}:${action}:${scope === 1 ? 'own' : '*'}`
}

function overrideStateFromList(overrides) {
  const states = {}
  for (const perm of CHANNEL_PERMISSIONS) {
    states[permKey(perm.resource, perm.action)] = 'inherit'
  }
  if (!overrides?.permission_overrides) return states

  for (const po of overrides.permission_overrides) {
    const p = po.permission || po
    const key = permKey(p.resource, p.action)
    if (key in states) {
      states[key] = po.is_deny ? 'deny' : 'allow'
    }
  }
  return states
}

export default function ChannelOverrides({ roleId, channels = [], workspaceId, onError }) {
  const [expanded, setExpanded] = useState(false)
  const [expandedChannelId, setExpandedChannelId] = useState(null)
  const [overrideData, setOverrideData] = useState(null)
  const [states, setStates] = useState({})
  const [loadingOverride, setLoadingOverride] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  const loadOverride = useCallback(async (channelId) => {
    setLoadingOverride(true)
    setDirty(false)
    try {
      const override = await permissionsService.getChannelOverride(channelId, roleId)
      setOverrideData(override)
      setStates(overrideStateFromList(override))
    } catch (err) {
      if (err?.status === 404) {
        setOverrideData(null)
        const defaults = {}
        for (const p of CHANNEL_PERMISSIONS) defaults[permKey(p.resource, p.action)] = 'inherit'
        setStates(defaults)
      } else {
        onError(err?.detail || 'Failed to load channel override')
      }
    } finally {
      setLoadingOverride(false)
    }
  }, [roleId, onError])

  useEffect(() => {
    if (expandedChannelId) loadOverride(expandedChannelId)
  }, [expandedChannelId, loadOverride])

  const handleStateChange = (key, newState) => {
    setStates((prev) => ({ ...prev, [key]: newState }))
    setDirty(true)
  }

  const handleSave = async () => {
    if (!expandedChannelId) return
    setSaving(true)
    try {
      const allow = []
      const deny = []
      for (const perm of CHANNEL_PERMISSIONS) {
        const key = permKey(perm.resource, perm.action)
        const state = states[key]
        if (state === 'inherit' || !state) continue
        const str = permToApiStr(perm.resource, perm.action)
        if (state === 'allow') allow.push(str)
        else deny.push(str)
      }

      if (!overrideData) {
        await permissionsService.createChannelOverride(expandedChannelId, roleId)
      }
      await permissionsService.updateChannelOverride(expandedChannelId, roleId, { allow, deny })

      await loadOverride(expandedChannelId)
    } catch (err) {
      onError(err?.detail || 'Failed to save channel overrides')
      await loadOverride(expandedChannelId)
    } finally {
      setSaving(false)
    }
  }

  const toggleChannel = (channelId) => {
    setExpandedChannelId((prev) => (prev === channelId ? null : channelId))
  }

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-[13px] font-semibold text-ink hover:text-amber transition-colors mb-2"
      >
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        Channel overrides
      </button>

      {expanded && (
        <div className="border border-[rgba(28,27,26,0.06)] rounded-lg overflow-hidden">
          {channels.length === 0 ? (
            <p className="text-[13px] text-ink-tertiary p-3">No channels in this workspace.</p>
          ) : (
            channels.map((ch) => (
              <div key={ch.id} className="border-b border-[rgba(28,27,26,0.04)] last:border-b-0">
                <button
                  onClick={() => toggleChannel(ch.id)}
                  className="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-surface-2 transition-colors"
                >
                  {expandedChannelId === ch.id ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  <Hash size={13} className="text-ink-tertiary" />
                  <span className="text-[13px] text-ink">{ch.name}</span>
                </button>

                {expandedChannelId === ch.id && (
                  <div className="px-3 pb-3">
                    {loadingOverride ? (
                      <div className="flex justify-center py-4"><CircularProgress size={18} /></div>
                    ) : (
                      <>
                        {CHANNEL_PERMISSIONS.map((perm) => {
                          const key = permKey(perm.resource, perm.action)
                          const state = states[key] || 'inherit'
                          return (
                            <div key={key} className="flex items-center justify-between py-1.5">
                              <span className="text-[12px] text-ink-secondary">{perm.label}</span>
                              <ButtonGroup size="small" variant="outlined">
                                {['allow', 'inherit', 'deny'].map((s) => (
                                  <Button
                                    key={s}
                                    onClick={() => handleStateChange(key, s)}
                                    variant={state === s ? 'contained' : 'outlined'}
                                    color={s === 'allow' ? 'success' : s === 'deny' ? 'error' : 'inherit'}
                                    sx={{ textTransform: 'capitalize', fontSize: 11, px: 1, minWidth: 0 }}
                                  >
                                    {s}
                                  </Button>
                                ))}
                              </ButtonGroup>
                            </div>
                          )
                        })}

                        {dirty && (
                          <div className="flex justify-end mt-2">
                            <Button
                              size="small"
                              variant="contained"
                              onClick={handleSave}
                              disabled={saving}
                              startIcon={saving ? <CircularProgress size={14} color="inherit" /> : null}
                            >
                              Save overrides
                            </Button>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
