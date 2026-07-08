import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import {
  notificationsService,
  enableWebPush,
  disableWebPush,
  getCurrentPushEndpoint,
  isPushSupported,
} from '../services/notifications'

export const loadNotifications = createAsyncThunk(
  'notifications/load',
  async ({ limit = 20, offset = 0, unreadOnly = false } = {}, { rejectWithValue }) => {
    try {
      return await notificationsService.list({ limit, offset, unreadOnly })
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to load notifications')
    }
  },
)

export const loadUnreadCount = createAsyncThunk(
  'notifications/loadUnreadCount',
  async (_, { rejectWithValue }) => {
    try {
      const res = await notificationsService.unreadCount()
      return res?.unread_count ?? 0
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to load unread count')
    }
  },
)

export const markRead = createAsyncThunk(
  'notifications/markRead',
  async (notificationId, { rejectWithValue, dispatch }) => {
    try {
      await notificationsService.markRead(notificationId)
      dispatch(loadUnreadCount())
      return notificationId
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to mark notification as read')
    }
  },
)

export const markAllRead = createAsyncThunk(
  'notifications/markAllRead',
  async (_, { rejectWithValue, dispatch }) => {
    try {
      await notificationsService.markAllRead()
      dispatch(loadUnreadCount())
      return true
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to mark all as read')
    }
  },
)

export const syncPushStatus = createAsyncThunk(
  'notifications/syncPushStatus',
  async () => {
    const supported = isPushSupported()
    const permission = supported ? Notification.permission : 'default'
    const endpoint = supported ? await getCurrentPushEndpoint() : null
    return { supported, permission, endpoint }
  },
)

export const enablePush = createAsyncThunk(
  'notifications/enablePush',
  async (_, { rejectWithValue }) => {
    try {
      const endpoint = await enableWebPush()
      return { endpoint, permission: Notification.permission }
    } catch (err) {
      return rejectWithValue(err?.message || 'Failed to enable push notifications')
    }
  },
)

export const disablePush = createAsyncThunk(
  'notifications/disablePush',
  async (_, { rejectWithValue }) => {
    try {
      await disableWebPush()
      return true
    } catch (err) {
      return rejectWithValue(err?.message || 'Failed to disable push notifications')
    }
  },
)

const notificationsSlice = createSlice({
  name: 'notifications',
  initialState: {
    items: [],
    unreadCount: 0,
    loading: false,
    error: null,
    pushSupported: false,
    pushPermission: 'default',
    pushEndpoint: null,
    pushLoading: false,
    pushError: null,
  },
  reducers: {
    receivedRealtime(state, action) {
      const n = action.payload
      if (!n || !n.id) return
      if (state.items.some((x) => x.id === n.id)) return
      state.items.unshift(n)
      if (!n.read_at) state.unreadCount += 1
    },
    clearNotificationsError(state) {
      state.error = null
    },
    clearPushError(state) {
      state.pushError = null
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadNotifications.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(loadNotifications.fulfilled, (state, action) => {
        state.items = action.payload
        state.loading = false
      })
      .addCase(loadNotifications.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
      .addCase(loadUnreadCount.fulfilled, (state, action) => {
        state.unreadCount = action.payload
      })
      .addCase(markRead.fulfilled, (state, action) => {
        const id = action.payload
        const item = state.items.find((x) => x.id === id)
        if (item && !item.read_at) {
          item.read_at = new Date().toISOString()
          state.unreadCount = Math.max(0, state.unreadCount - 1)
        }
      })
      .addCase(markAllRead.fulfilled, (state) => {
        const now = new Date().toISOString()
        state.items.forEach((x) => {
          if (!x.read_at) x.read_at = now
        })
        state.unreadCount = 0
      })
      .addCase(syncPushStatus.fulfilled, (state, action) => {
        state.pushSupported = action.payload.supported
        state.pushPermission = action.payload.permission
        state.pushEndpoint = action.payload.endpoint
      })
      .addCase(enablePush.pending, (state) => {
        state.pushLoading = true
        state.pushError = null
      })
      .addCase(enablePush.fulfilled, (state, action) => {
        state.pushLoading = false
        state.pushEndpoint = action.payload.endpoint
        state.pushPermission = action.payload.permission
      })
      .addCase(enablePush.rejected, (state, action) => {
        state.pushLoading = false
        state.pushError = action.payload
        if (typeof Notification !== 'undefined') {
          state.pushPermission = Notification.permission
        }
      })
      .addCase(disablePush.pending, (state) => {
        state.pushLoading = true
        state.pushError = null
      })
      .addCase(disablePush.fulfilled, (state) => {
        state.pushLoading = false
        state.pushEndpoint = null
      })
      .addCase(disablePush.rejected, (state, action) => {
        state.pushLoading = false
        state.pushError = action.payload
      })
      // Per-account data must not survive an account switch (push settings are
      // browser-level and stay).
      .addMatcher(
        (action) => ['auth/logout/fulfilled', 'auth/logout/rejected', 'auth/login/fulfilled'].includes(action.type),
        (state) => {
          state.items = []
          state.unreadCount = 0
          state.loading = false
          state.error = null
        },
      )
  },
})

export const {
  receivedRealtime,
  clearNotificationsError,
  clearPushError,
} = notificationsSlice.actions
export default notificationsSlice.reducer
