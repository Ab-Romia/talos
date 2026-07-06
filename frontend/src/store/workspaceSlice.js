import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { chatService } from '../services/chat'
import { reconnectSocket } from '../services/socket'
import { login, logout } from './authSlice'

const ACTIVE_WS_KEY = 'talos:activeWorkspaceId'
const ACTIVE_CR_KEY = 'talos:activeChatroomId'

// Everything here is per-account state; carrying it across an account switch
// leaves the next user "in" a workspace they may not belong to.
function resetToInitial(state) {
  state.workspaces = []
  state.chatrooms = []
  state.dms = []
  state.activeWorkspaceId = null
  state.activeChatroomId = null
  state.unreadChannels = []
  state.loading = false
  state.error = null
  state.membersVersion = 0
  state.permissionsVersion = 0
  state.syncNotice = null
  try {
    localStorage.removeItem(ACTIVE_WS_KEY)
    localStorage.removeItem(ACTIVE_CR_KEY)
  } catch {}
}

// Re-pull the workspace list (each with its channels inline) after a realtime
// change to membership, channels, or permissions made by another user.
export const refreshWorkspaces = createAsyncThunk(
  'workspace/refresh',
  async (_, { rejectWithValue }) => {
    try {
      const workspaces = await chatService.getWorkspaces()
      return Array.isArray(workspaces) ? workspaces : []
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to sync workspaces')
    }
  },
)

// Direct messages for the active workspace.
export const loadDms = createAsyncThunk(
  'workspace/loadDms',
  async (workspaceId, { rejectWithValue }) => {
    try {
      const dms = await chatService.getDms(workspaceId)
      return Array.isArray(dms) ? dms : []
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to load direct messages')
    }
  },
)

// Create-or-get a DM with a member and make it the active conversation.
export const openDm = createAsyncThunk(
  'workspace/openDm',
  async ({ workspaceId, userId }, { rejectWithValue }) => {
    try {
      const dm = await chatService.openDm(workspaceId, userId)
      // The backend joins live sockets into the new room, but reconnecting
      // guarantees membership for this client even after socket hiccups.
      reconnectSocket()
      return dm
    } catch (err) {
      return rejectWithValue(err.detail || 'Could not open the conversation')
    }
  },
)

// Create a group conversation and make it the active conversation.
export const createGroup = createAsyncThunk(
  'workspace/createGroup',
  async ({ workspaceId, name, userIds }, { rejectWithValue }) => {
    try {
      const group = await chatService.createGroup(workspaceId, name, userIds)
      reconnectSocket()
      return group
    } catch (err) {
      return rejectWithValue(err.detail || 'Could not create the group')
    }
  },
)

export const bootstrapWorkspaces = createAsyncThunk(
  'workspace/bootstrap',
  async (_, { rejectWithValue }) => {
    try {
      const workspaces = await chatService.getWorkspaces()
      if (!workspaces.length) {
        return {
          workspaces: [],
          activeWorkspaceId: null,
          chatrooms: [],
          activeChatroomId: null,
        }
      }
      const savedWs = localStorage.getItem(ACTIVE_WS_KEY)
      const activeWs = workspaces.find((w) => w.id === savedWs) || workspaces[0]
      let chatrooms = activeWs.channels || []
      try {
        chatrooms = await chatService.listChannels(activeWs.id)
      } catch {}
      const savedCr = localStorage.getItem(ACTIVE_CR_KEY)
      const activeCr = chatrooms.find((c) => c.id === savedCr) || chatrooms[0] || null
      return {
        workspaces,
        activeWorkspaceId: activeWs.id,
        chatrooms,
        activeChatroomId: activeCr ? activeCr.id : null,
      }
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to load workspaces')
    }
  },
  {
    condition: (_, { getState }) => {
      const { workspace, auth } = getState()
      if (!auth?.isAuthenticated) return false
      if (workspace.loading) return false
      if (workspace.workspaces.length) return false
      return true
    },
  },
)

export const switchWorkspace = createAsyncThunk(
  'workspace/switch',
  async (workspaceId, { getState, rejectWithValue }) => {
    try {
      const { workspace } = getState()
      const ws = workspace.workspaces.find((w) => w.id === workspaceId)
      let chatrooms = ws?.channels || []
      try {
        chatrooms = await chatService.listChannels(workspaceId)
      } catch {}
      const activeCr = chatrooms[0] || null
      return {
        workspaceId,
        chatrooms,
        chatroomId: activeCr ? activeCr.id : null,
      }
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to switch workspace')
    }
  },
)

export const createWorkspace = createAsyncThunk(
  'workspace/create',
  // Accepts a plain name string (quick create) or { name, channels, members }.
  async (arg, { rejectWithValue }) => {
    try {
      const { name, channels, members } = typeof arg === 'string' ? { name: arg } : arg
      const ws = await chatService.createWorkspace(name, { channels, members })
      // New channel rooms are only joined by the socket at connect time.
      reconnectSocket()
      return ws // { id, name, owner_id, channels:[{id,name}] }
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to create workspace')
    }
  },
)

export const createChatroom = createAsyncThunk(
  'workspace/createChatroom',
  async ({ workspaceId, name }, { rejectWithValue }) => {
    try {
      const channel = await chatService.createChannel(workspaceId, name)
      reconnectSocket()
      return channel // { id, name }
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to create channel')
    }
  },
)

const workspaceSlice = createSlice({
  name: 'workspace',
  initialState: {
    workspaces: [],
    chatrooms: [],
    // Hydrate from localStorage so a failed/blocked bootstrap fetch (e.g. the
    // backend restarting) doesn't leave the app with no active workspace —
    // which silently broke document upload and any workspace-scoped action.
    activeWorkspaceId: (() => { try { return localStorage.getItem(ACTIVE_WS_KEY) } catch { return null } })(),
    activeChatroomId: (() => { try { return localStorage.getItem(ACTIVE_CR_KEY) } catch { return null } })(),
    dms: [],
    unreadChannels: [],
    loading: false,
    error: null,
    // Bumped when another user changes this workspace's roster / permissions, so
    // views that fetch members or effective permissions re-run their effects.
    membersVersion: 0,
    permissionsVersion: 0,
    // Transient, user-friendly notice for a sync event that concerns me directly
    // (e.g. "You were removed from X"). Rendered once, then cleared.
    syncNotice: null,
  },
  reducers: {
    setActiveChatroom(state, action) {
      state.activeChatroomId = action.payload
      state.unreadChannels = state.unreadChannels.filter((id) => id !== action.payload)
      try {
        localStorage.setItem(ACTIVE_CR_KEY, action.payload)
      } catch {}
    },
    markChannelUnread(state, action) {
      if (!state.unreadChannels.includes(action.payload)) {
        state.unreadChannels.push(action.payload)
      }
    },
    clearWorkspaceError(state) {
      state.error = null
    },
    bumpMembersVersion(state) {
      state.membersVersion += 1
    },
    bumpPermissionsVersion(state) {
      state.permissionsVersion += 1
    },
    setSyncNotice(state, action) {
      state.syncNotice = action.payload
    },
    clearSyncNotice(state) {
      state.syncNotice = null
    },
    // Another user removed me from (or deleted) this workspace: drop it and fall
    // back to whatever remains so I'm never left "inside" a workspace I can't see.
    workspaceRemoved(state, action) {
      const wsId = action.payload
      state.workspaces = state.workspaces.filter((w) => w.id !== wsId)
      if (state.activeWorkspaceId === wsId) {
        const next = state.workspaces[0] || null
        state.activeWorkspaceId = next ? next.id : null
        state.chatrooms = next ? next.channels || [] : []
        state.activeChatroomId = state.chatrooms[0]?.id ?? null
        state.dms = []
        try {
          if (state.activeWorkspaceId) localStorage.setItem(ACTIVE_WS_KEY, state.activeWorkspaceId)
          else localStorage.removeItem(ACTIVE_WS_KEY)
          if (state.activeChatroomId) localStorage.setItem(ACTIVE_CR_KEY, state.activeChatroomId)
          else localStorage.removeItem(ACTIVE_CR_KEY)
        } catch {}
      }
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(bootstrapWorkspaces.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(bootstrapWorkspaces.fulfilled, (state, action) => {
        state.workspaces = action.payload.workspaces
        state.chatrooms = action.payload.chatrooms
        state.activeWorkspaceId = action.payload.activeWorkspaceId
        state.activeChatroomId = action.payload.activeChatroomId
        state.loading = false
        try {
          if (action.payload.activeWorkspaceId)
            localStorage.setItem(ACTIVE_WS_KEY, action.payload.activeWorkspaceId)
          if (action.payload.activeChatroomId)
            localStorage.setItem(ACTIVE_CR_KEY, action.payload.activeChatroomId)
        } catch {}
      })
      .addCase(bootstrapWorkspaces.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
      .addCase(switchWorkspace.fulfilled, (state, action) => {
        state.activeWorkspaceId = action.payload.workspaceId
        state.chatrooms = action.payload.chatrooms
        state.activeChatroomId = action.payload.chatroomId
        state.dms = []
        try {
          localStorage.setItem(ACTIVE_WS_KEY, action.payload.workspaceId)
          if (action.payload.chatroomId)
            localStorage.setItem(ACTIVE_CR_KEY, action.payload.chatroomId)
        } catch {}
      })
      .addCase(loadDms.fulfilled, (state, action) => {
        state.dms = action.payload
      })
      .addCase(openDm.fulfilled, (state, action) => {
        const dm = action.payload
        if (!state.dms.some((d) => d.id === dm.id)) state.dms.push(dm)
        state.activeChatroomId = dm.id
        state.unreadChannels = state.unreadChannels.filter((id) => id !== dm.id)
        try {
          localStorage.setItem(ACTIVE_CR_KEY, dm.id)
        } catch {}
      })
      .addCase(openDm.rejected, (state, action) => {
        state.error = action.payload
      })
      .addCase(createGroup.fulfilled, (state, action) => {
        const group = action.payload
        if (!state.dms.some((d) => d.id === group.id)) state.dms.push(group)
        state.activeChatroomId = group.id
        state.unreadChannels = state.unreadChannels.filter((id) => id !== group.id)
        try {
          localStorage.setItem(ACTIVE_CR_KEY, group.id)
        } catch {}
      })
      .addCase(createGroup.rejected, (state, action) => {
        state.error = action.payload
      })
      .addCase(createWorkspace.fulfilled, (state, action) => {
        const ws = action.payload
        state.workspaces.push(ws)
        state.activeWorkspaceId = ws.id
        state.chatrooms = ws.channels || []
        state.activeChatroomId = state.chatrooms[0]?.id ?? null
        try {
          localStorage.setItem(ACTIVE_WS_KEY, ws.id)
          if (state.activeChatroomId) localStorage.setItem(ACTIVE_CR_KEY, state.activeChatroomId)
        } catch {}
      })
      .addCase(createWorkspace.rejected, (state, action) => {
        state.error = action.payload
      })
      .addCase(createChatroom.fulfilled, (state, action) => {
        state.chatrooms.push(action.payload)
        state.activeChatroomId = action.payload.id
        // keep it on the active workspace's channel list
        const ws = state.workspaces.find((w) => w.id === state.activeWorkspaceId)
        if (ws) ws.channels = state.chatrooms
        try {
          localStorage.setItem(ACTIVE_CR_KEY, action.payload.id)
        } catch {}
      })
      .addCase(createChatroom.rejected, (state, action) => {
        state.error = action.payload
      })
      .addCase(refreshWorkspaces.fulfilled, (state, action) => {
        const workspaces = action.payload || []
        state.workspaces = workspaces
        let active = workspaces.find((w) => w.id === state.activeWorkspaceId)
        if (!active) {
          // The active workspace vanished (removed/deleted) — fall back gracefully.
          active = workspaces[0] || null
          state.activeWorkspaceId = active ? active.id : null
          state.activeChatroomId = null
          state.dms = []
        }
        if (active) {
          state.chatrooms = active.channels || []
          if (!state.chatrooms.some((c) => c.id === state.activeChatroomId)) {
            state.activeChatroomId = state.chatrooms[0]?.id ?? null
          }
          try {
            localStorage.setItem(ACTIVE_WS_KEY, active.id)
            if (state.activeChatroomId) localStorage.setItem(ACTIVE_CR_KEY, state.activeChatroomId)
          } catch {}
        } else {
          state.chatrooms = []
          state.activeChatroomId = null
        }
      })
      // Account switches: clear on logout (fulfilled OR rejected — the UI
      // treats both as logged out) and on a fresh login, so bootstrap always
      // refetches the NEW account's workspaces instead of reusing the old
      // account's list (which caused "Not a member of this workspace").
      .addCase(logout.fulfilled, resetToInitial)
      .addCase(logout.rejected, resetToInitial)
      .addCase(login.fulfilled, resetToInitial)
  },
})

export const {
  setActiveChatroom,
  markChannelUnread,
  clearWorkspaceError,
  bumpMembersVersion,
  bumpPermissionsVersion,
  setSyncNotice,
  clearSyncNotice,
  workspaceRemoved,
} = workspaceSlice.actions
export default workspaceSlice.reducer
