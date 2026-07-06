import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { chatService } from '../services/chat'
import { reconnectSocket } from '../services/socket'

const ACTIVE_WS_KEY = 'talos:activeWorkspaceId'
const ACTIVE_CR_KEY = 'talos:activeChatroomId'

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
    activeWorkspaceId: null,
    activeChatroomId: null,
    unreadChannels: [],
    loading: false,
    error: null,
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
        try {
          localStorage.setItem(ACTIVE_WS_KEY, action.payload.workspaceId)
          if (action.payload.chatroomId)
            localStorage.setItem(ACTIVE_CR_KEY, action.payload.chatroomId)
        } catch {}
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
  },
})

export const { setActiveChatroom, markChannelUnread, clearWorkspaceError } = workspaceSlice.actions
export default workspaceSlice.reducer
