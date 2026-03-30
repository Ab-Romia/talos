import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { authService } from '../services/auth'

export const login = createAsyncThunk(
  'auth/login',
  async ({ username, password }, { rejectWithValue }) => {
    try {
      const data = await authService.login(username, password)
      return data
    } catch (err) {
      return rejectWithValue(err.detail || 'Login failed')
    }
  }
)

export const signup = createAsyncThunk(
  'auth/signup',
  async (userData, { rejectWithValue }) => {
    try {
      await authService.signup(userData)
      return true
    } catch (err) {
      return rejectWithValue(err.detail || 'Signup failed')
    }
  }
)

export const logout = createAsyncThunk(
  'auth/logout',
  async (_, { rejectWithValue }) => {
    try {
      await authService.logout()
      return true
    } catch (err) {
      return rejectWithValue(err.detail || 'Logout failed')
    }
  }
)

export const refreshToken = createAsyncThunk(
  'auth/refresh',
  async (_, { rejectWithValue }) => {
    try {
      const data = await authService.me()
      return data
    } catch (err) {
      return rejectWithValue(err.detail || 'Session expired')
    }
  }
)

const savedAuth = localStorage.getItem('talos_auth') === 'true'

const authSlice = createSlice({
  name: 'auth',
  initialState: {
    isAuthenticated: savedAuth,
    user: null,
    loading: false,
    error: null,
    requiresOtp: false,
    sessionChecked: savedAuth,
  },
  reducers: {
    clearError(state) {
      state.error = null
    },
    setAuthenticated(state, action) {
      state.isAuthenticated = action.payload
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(login.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(login.fulfilled, (state, action) => {
        state.loading = false
        state.isAuthenticated = !action.payload.requires_otp
        state.requiresOtp = !!action.payload.requires_otp
        state.sessionChecked = true
        localStorage.setItem('talos_auth', String(state.isAuthenticated))
      })
      .addCase(login.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
      .addCase(signup.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(signup.fulfilled, (state) => {
        state.loading = false
      })
      .addCase(signup.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
      .addCase(logout.fulfilled, (state) => {
        state.isAuthenticated = false
        state.user = null
        state.requiresOtp = false
        state.sessionChecked = true
        localStorage.removeItem('talos_auth')
      })
      .addCase(logout.rejected, (state) => {
        state.isAuthenticated = false
        state.user = null
        state.requiresOtp = false
        state.sessionChecked = true
        localStorage.removeItem('talos_auth')
      })
      .addCase(refreshToken.fulfilled, (state, action) => {
        state.isAuthenticated = true
        state.user = action.payload
        state.sessionChecked = true
        localStorage.setItem('talos_auth', 'true')
      })
      .addCase(refreshToken.rejected, (state) => {
        if (localStorage.getItem('talos_auth') !== 'true') {
          state.isAuthenticated = false
        }
        state.sessionChecked = true
      })
  },
})

export const { clearError, setAuthenticated } = authSlice.actions
export default authSlice.reducer
