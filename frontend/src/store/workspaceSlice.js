import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { chatService } from '../services/chat'

const ACTIVE_WS_KEY = 'talos:activeWorkspaceId'
const ACTIVE_CR_KEY = 'talos:activeChatroomId'

export const bootstrapWorkspaces = createAsyncThunk(
  'workspace/bootstrap',
  async (_, { rejectWithValue, dispatch }) => {
    try {
      let workspaces = await chatService.getWorkspaces()
      if (!workspaces.length) {
        const created = await chatService.createWorkspace('My Workspace')
        workspaces = [created]
      }
      const savedWs = localStorage.getItem(ACTIVE_WS_KEY)
      const activeWs = workspaces.find((w) => w.id === savedWs) || workspaces[0]

      const chatrooms = await dispatch(loadChatrooms(activeWs.id)).unwrap()
      const savedCr = localStorage.getItem(ACTIVE_CR_KEY)
      let activeCr = chatrooms.find((c) => c.id === savedCr) || chatrooms[0]
      if (!activeCr) {
        activeCr = await dispatch(
          createChatroom({ workspaceId: activeWs.id, name: 'general' }),
        ).unwrap()
      }
      return {
        workspaces,
        activeWorkspaceId: activeWs.id,
        activeChatroomId: activeCr.id,
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

export const loadChatrooms = createAsyncThunk(
  'workspace/loadChatrooms',
  async (workspaceId, { rejectWithValue }) => {
    try {
      return await chatService.getChatrooms(workspaceId)
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to load chatrooms')
    }
  },
)

export const createWorkspace = createAsyncThunk(
  'workspace/create',
  async (name, { rejectWithValue, dispatch }) => {
    try {
      const ws = await chatService.createWorkspace(name)
      await dispatch(loadChatrooms(ws.id))
      return ws
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to create workspace')
    }
  },
)

export const createChatroom = createAsyncThunk(
  'workspace/createChatroom',
  async ({ workspaceId, name }, { rejectWithValue }) => {
    try {
      return await chatService.createChatroom(workspaceId, name)
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to create channel')
    }
  },
)

export const switchWorkspace = createAsyncThunk(
  'workspace/switch',
  async (workspaceId, { dispatch, rejectWithValue }) => {
    try {
      const chatrooms = await dispatch(loadChatrooms(workspaceId)).unwrap()
      let activeCr = chatrooms[0]
      if (!activeCr) {
        activeCr = await dispatch(
          createChatroom({ workspaceId, name: 'general' }),
        ).unwrap()
      }
      return { workspaceId, chatroomId: activeCr.id }
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to switch workspace')
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
    loading: false,
    error: null,
  },
  reducers: {
    setActiveChatroom(state, action) {
      state.activeChatroomId = action.payload
      try {
        localStorage.setItem(ACTIVE_CR_KEY, action.payload)
      } catch {}
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
        state.activeWorkspaceId = action.payload.activeWorkspaceId
        state.activeChatroomId = action.payload.activeChatroomId
        state.loading = false
        try {
          localStorage.setItem(ACTIVE_WS_KEY, action.payload.activeWorkspaceId)
          localStorage.setItem(ACTIVE_CR_KEY, action.payload.activeChatroomId)
        } catch {}
      })
      .addCase(bootstrapWorkspaces.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
      .addCase(loadChatrooms.fulfilled, (state, action) => {
        state.chatrooms = action.payload
      })
      .addCase(createWorkspace.fulfilled, (state, action) => {
        state.workspaces.push(action.payload)
        state.activeWorkspaceId = action.payload.id
        try {
          localStorage.setItem(ACTIVE_WS_KEY, action.payload.id)
        } catch {}
      })
      .addCase(createChatroom.fulfilled, (state, action) => {
        state.chatrooms.push(action.payload)
        state.activeChatroomId = action.payload.id
        try {
          localStorage.setItem(ACTIVE_CR_KEY, action.payload.id)
        } catch {}
      })
      .addCase(switchWorkspace.fulfilled, (state, action) => {
        state.activeWorkspaceId = action.payload.workspaceId
        state.activeChatroomId = action.payload.chatroomId
        try {
          localStorage.setItem(ACTIVE_WS_KEY, action.payload.workspaceId)
          localStorage.setItem(ACTIVE_CR_KEY, action.payload.chatroomId)
        } catch {}
      })
  },
})

export const { setActiveChatroom, clearWorkspaceError } = workspaceSlice.actions
export default workspaceSlice.reducer
