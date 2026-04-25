import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { authService } from '../services/auth'
import { webauthn } from '../services/webauthn'

export const login = createAsyncThunk(
  'auth/login',
  async ({ username, password }, { rejectWithValue, dispatch }) => {
    try {
      await authService.login(username, password)
      let me = null
      try {
        me = await authService.me()
      } catch {}
      if (me) {
        dispatch({ type: 'auth/refresh/fulfilled', payload: me })
      }
      return { user: me, requiresOtp: !me }
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

export const changePassword = createAsyncThunk(
  'auth/changePassword',
  async ({ currentPassword, newPassword }, { rejectWithValue }) => {
    try {
      await authService.sudo(currentPassword)
      await authService.changePassword(newPassword)
      return true
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to change password')
    }
  }
)

export const listSessions = createAsyncThunk(
  'auth/listSessions',
  async ({ password } = {}, { rejectWithValue }) => {
    try {
      if (password) await authService.sudo(password)
      const sessions = await authService.listSessions()
      return sessions || []
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to load sessions')
    }
  }
)

export const revokeSession = createAsyncThunk(
  'auth/revokeSession',
  async ({ sessionId, password }, { rejectWithValue }) => {
    try {
      await authService.sudo(password)
      await authService.revokeSession(sessionId)
      return sessionId
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to revoke session')
    }
  }
)

export const revokeAllSessions = createAsyncThunk(
  'auth/revokeAllSessions',
  async ({ password }, { rejectWithValue }) => {
    try {
      await authService.sudo(password)
      await authService.revokeAllSessions()
      return true
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to revoke all sessions')
    }
  }
)

export const setupTotp = createAsyncThunk(
  'auth/setupTotp',
  async (_, { rejectWithValue }) => {
    try {
      const data = await authService.totpCreate()
      return data
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to start TOTP setup')
    }
  }
)

export const registerTotp = createAsyncThunk(
  'auth/registerTotp',
  async ({ otp, jwt_totp_claims, password }, { rejectWithValue }) => {
    try {
      if (password) await authService.sudo(password)
      await authService.totpRegister({ otp, jwt_totp_claims })
      return true
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to register TOTP')
    }
  }
)

export const verifyTotp = createAsyncThunk(
  'auth/verifyTotp',
  async ({ otp }, { rejectWithValue, dispatch }) => {
    try {
      await authService.totpVerify(otp)
      const me = await authService.me()
      dispatch({ type: 'auth/refresh/fulfilled', payload: me })
      return me
    } catch (err) {
      return rejectWithValue(err.detail || 'Invalid verification code')
    }
  }
)

export const disableTotp = createAsyncThunk(
  'auth/disableTotp',
  async (_, { rejectWithValue }) => {
    try {
      await authService.totpDelete()
      return true
    } catch (err) {
      return rejectWithValue(err.detail || 'Failed to disable TOTP')
    }
  }
)

export const registerPasskey = createAsyncThunk(
  'auth/registerPasskey',
  async ({ name, password }, { rejectWithValue }) => {
    try {
      if (!webauthn.isSupported()) {
        return rejectWithValue('Passkeys are not supported in this browser')
      }
      if (password) await authService.sudo(password)
      const { options, jwt_challenge } = await authService.passkeyRegistrationChallenge()
      const credential = await webauthn.createCredential(options)
      await authService.passkeyRegister({ jwt_challenge, credential, name })
      return true
    } catch (err) {
      return rejectWithValue(err?.detail || err?.message || 'Failed to register passkey')
    }
  }
)

export const loginWithPasskey = createAsyncThunk(
  'auth/loginWithPasskey',
  async (_, { rejectWithValue, dispatch }) => {
    try {
      if (!webauthn.isSupported()) {
        return rejectWithValue('Passkeys are not supported in this browser')
      }
      const { options, jwt_challenge } = await authService.passkeyAuthChallenge()
      const credential = await webauthn.getCredential(options)
      await authService.passkeyVerify({ jwt_challenge, credential })
      const me = await authService.me()
      dispatch({ type: 'auth/refresh/fulfilled', payload: me })
      return me
    } catch (err) {
      return rejectWithValue(err?.detail || err?.message || 'Passkey sign-in failed')
    }
  }
)

export const completeOAuthHandoff = createAsyncThunk(
  'auth/oauthHandoff',
  async (token, { rejectWithValue }) => {
    try {
      await authService.oauthHandoff(token)
      return true
    } catch (err) {
      return rejectWithValue(err?.detail || 'Sign-in could not be completed')
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
    settingsLoading: false,
    settingsError: null,
    sessions: [],
    sessionsLoading: false,
    totpSetup: null,
    totpError: null,
    passkeyLoading: false,
    passkeyError: null,
  },
  reducers: {
    clearError(state) {
      state.error = null
    },
    clearSettingsError(state) {
      state.settingsError = null
    },
    clearTotpSetup(state) {
      state.totpSetup = null
      state.totpError = null
    },
    clearPasskeyError(state) {
      state.passkeyError = null
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
        const { user, requiresOtp } = action.payload
        state.requiresOtp = requiresOtp
        state.isAuthenticated = !requiresOtp && !!user
        state.user = user
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
        state.sessions = []
        localStorage.removeItem('talos_auth')
      })
      .addCase(logout.rejected, (state) => {
        state.isAuthenticated = false
        state.user = null
        state.requiresOtp = false
        state.sessionChecked = true
        state.sessions = []
        localStorage.removeItem('talos_auth')
      })
      .addCase(refreshToken.fulfilled, (state, action) => {
        state.isAuthenticated = true
        state.user = action.payload
        state.sessionChecked = true
        state.requiresOtp = false
        localStorage.setItem('talos_auth', 'true')
      })
      .addCase(refreshToken.rejected, (state) => {
        if (localStorage.getItem('talos_auth') !== 'true') {
          state.isAuthenticated = false
        }
        state.sessionChecked = true
      })
      .addCase(changePassword.pending, (state) => {
        state.settingsLoading = true
        state.settingsError = null
      })
      .addCase(changePassword.fulfilled, (state) => {
        state.settingsLoading = false
      })
      .addCase(changePassword.rejected, (state, action) => {
        state.settingsLoading = false
        state.settingsError = action.payload
      })
      .addCase(listSessions.pending, (state) => {
        state.sessionsLoading = true
      })
      .addCase(listSessions.fulfilled, (state, action) => {
        state.sessionsLoading = false
        state.sessions = action.payload
      })
      .addCase(listSessions.rejected, (state, action) => {
        state.sessionsLoading = false
        state.settingsError = action.payload
      })
      .addCase(revokeSession.pending, (state) => {
        state.settingsLoading = true
        state.settingsError = null
      })
      .addCase(revokeSession.fulfilled, (state, action) => {
        state.settingsLoading = false
        state.sessions = state.sessions.filter((s) => s.id !== action.payload)
      })
      .addCase(revokeSession.rejected, (state, action) => {
        state.settingsLoading = false
        state.settingsError = action.payload
      })
      .addCase(revokeAllSessions.fulfilled, (state) => {
        state.sessions = state.sessions.filter((s) => s.current)
        state.settingsLoading = false
      })
      .addCase(revokeAllSessions.rejected, (state, action) => {
        state.settingsLoading = false
        state.settingsError = action.payload
      })
      .addCase(setupTotp.pending, (state) => {
        state.totpError = null
      })
      .addCase(setupTotp.fulfilled, (state, action) => {
        state.totpSetup = action.payload
      })
      .addCase(setupTotp.rejected, (state, action) => {
        state.totpError = action.payload
      })
      .addCase(registerTotp.fulfilled, (state) => {
        state.totpSetup = null
      })
      .addCase(registerTotp.rejected, (state, action) => {
        state.totpError = action.payload
      })
      .addCase(verifyTotp.fulfilled, (state, action) => {
        state.requiresOtp = false
        state.isAuthenticated = true
        state.user = action.payload
        localStorage.setItem('talos_auth', 'true')
      })
      .addCase(verifyTotp.rejected, (state, action) => {
        state.error = action.payload
      })
      .addCase(registerPasskey.pending, (state) => {
        state.passkeyLoading = true
        state.passkeyError = null
      })
      .addCase(registerPasskey.fulfilled, (state) => {
        state.passkeyLoading = false
      })
      .addCase(registerPasskey.rejected, (state, action) => {
        state.passkeyLoading = false
        state.passkeyError = action.payload
      })
      .addCase(loginWithPasskey.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(loginWithPasskey.fulfilled, (state, action) => {
        state.loading = false
        state.isAuthenticated = true
        state.user = action.payload
        state.sessionChecked = true
        state.requiresOtp = false
        localStorage.setItem('talos_auth', 'true')
      })
      .addCase(loginWithPasskey.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
      .addCase(completeOAuthHandoff.rejected, (state, action) => {
        state.error = action.payload
      })
  },
})

export const {
  clearError,
  clearSettingsError,
  clearTotpSetup,
  clearPasskeyError,
  setAuthenticated,
} = authSlice.actions
export default authSlice.reducer
