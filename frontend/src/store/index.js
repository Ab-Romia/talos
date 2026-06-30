import { configureStore } from '@reduxjs/toolkit'
import authReducer from './authSlice'
import workspaceReducer from './workspaceSlice'
import notificationsReducer from './notificationsSlice'

export const store = configureStore({
  reducer: {
    auth: authReducer,
    workspace: workspaceReducer,
    notifications: notificationsReducer,
  },
})
