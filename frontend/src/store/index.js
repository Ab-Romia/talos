import { configureStore } from '@reduxjs/toolkit'
import authReducer from './authSlice'
import workspaceReducer from './workspaceSlice'

export const store = configureStore({
  reducer: {
    auth: authReducer,
    workspace: workspaceReducer,
  },
})
