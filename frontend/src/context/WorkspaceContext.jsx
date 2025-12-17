/**
 * Workspace Context
 *
 * Manages workspace and chatroom state.
 */

import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { workspacesApi, chatroomsApi } from '../services/api';
import { useAuth } from './AuthContext';

const WorkspaceContext = createContext(null);

export const useWorkspace = () => {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error('useWorkspace must be used within a WorkspaceProvider');
  }
  return context;
};

export const WorkspaceProvider = ({ children }) => {
  const { isAuthenticated } = useAuth();
  const [workspaces, setWorkspaces] = useState([]);
  const [currentWorkspace, setCurrentWorkspace] = useState(null);
  const [chatrooms, setChatrooms] = useState([]);
  const [currentChatroom, setCurrentChatroom] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Load workspaces when authenticated
  useEffect(() => {
    if (isAuthenticated) {
      loadWorkspaces();
    } else {
      setWorkspaces([]);
      setCurrentWorkspace(null);
      setChatrooms([]);
      setCurrentChatroom(null);
    }
  }, [isAuthenticated]);

  // Load chatrooms when workspace changes
  useEffect(() => {
    if (currentWorkspace) {
      loadChatrooms(currentWorkspace.id);
    } else {
      setChatrooms([]);
      setCurrentChatroom(null);
    }
  }, [currentWorkspace]);

  const loadWorkspaces = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await workspacesApi.list();
      setWorkspaces(response.workspaces || []);

      // Auto-select first workspace if none selected
      if (!currentWorkspace && response.workspaces?.length > 0) {
        setCurrentWorkspace(response.workspaces[0]);
      }
    } catch (err) {
      setError(err.message || 'Failed to load workspaces');
    } finally {
      setLoading(false);
    }
  }, [currentWorkspace]);

  const loadChatrooms = useCallback(async (workspaceId) => {
    setLoading(true);
    try {
      const response = await chatroomsApi.list(workspaceId);
      setChatrooms(response.chatrooms || []);

      // Auto-select first chatroom
      if (response.chatrooms?.length > 0 && !currentChatroom) {
        setCurrentChatroom(response.chatrooms[0]);
      }
    } catch (err) {
      setError(err.message || 'Failed to load chatrooms');
    } finally {
      setLoading(false);
    }
  }, [currentChatroom]);

  const createWorkspace = useCallback(async (name) => {
    setLoading(true);
    setError(null);
    try {
      const workspace = await workspacesApi.create({ name });
      setWorkspaces((prev) => [...prev, workspace]);
      setCurrentWorkspace(workspace);
      return workspace;
    } catch (err) {
      setError(err.message || 'Failed to create workspace');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const deleteWorkspace = useCallback(async (workspaceId) => {
    setLoading(true);
    setError(null);
    try {
      await workspacesApi.delete(workspaceId);
      setWorkspaces((prev) => prev.filter((w) => w.id !== workspaceId));
      if (currentWorkspace?.id === workspaceId) {
        setCurrentWorkspace(workspaces.find((w) => w.id !== workspaceId) || null);
      }
    } catch (err) {
      setError(err.message || 'Failed to delete workspace');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [currentWorkspace, workspaces]);

  const createChatroom = useCallback(async (name) => {
    if (!currentWorkspace) {
      throw new Error('No workspace selected');
    }
    setLoading(true);
    setError(null);
    try {
      const chatroom = await chatroomsApi.create({
        name,
        workspace_id: currentWorkspace.id,
      });
      setChatrooms((prev) => [...prev, chatroom]);
      setCurrentChatroom(chatroom);
      return chatroom;
    } catch (err) {
      setError(err.message || 'Failed to create chatroom');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [currentWorkspace]);

  const deleteChatroom = useCallback(async (chatroomId) => {
    setLoading(true);
    setError(null);
    try {
      await chatroomsApi.delete(chatroomId);
      setChatrooms((prev) => prev.filter((c) => c.id !== chatroomId));
      if (currentChatroom?.id === chatroomId) {
        setCurrentChatroom(chatrooms.find((c) => c.id !== chatroomId) || null);
      }
    } catch (err) {
      setError(err.message || 'Failed to delete chatroom');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [currentChatroom, chatrooms]);

  const selectWorkspace = useCallback((workspace) => {
    setCurrentWorkspace(workspace);
    setCurrentChatroom(null);
  }, []);

  const selectChatroom = useCallback((chatroom) => {
    setCurrentChatroom(chatroom);
  }, []);

  const value = {
    workspaces,
    currentWorkspace,
    chatrooms,
    currentChatroom,
    loading,
    error,
    loadWorkspaces,
    createWorkspace,
    deleteWorkspace,
    selectWorkspace,
    createChatroom,
    deleteChatroom,
    selectChatroom,
    clearError: () => setError(null),
  };

  return (
    <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
  );
};

export default WorkspaceContext;
