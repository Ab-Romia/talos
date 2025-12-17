/**
 * API Client Service
 *
 * Provides methods for communicating with the Talos backend API.
 * All API calls go through this service for consistent error handling.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

/**
 * Get stored auth token
 */
const getToken = () => localStorage.getItem('token');

/**
 * Set auth token
 */
const setToken = (token) => localStorage.setItem('token', token);

/**
 * Remove auth token
 */
const removeToken = () => localStorage.removeItem('token');

/**
 * Make an API request
 */
const request = async (endpoint, options = {}) => {
  const url = `${API_BASE_URL}${endpoint}`;
  const token = getToken();

  const headers = {
    'Content-Type': 'application/json',
    ...(token && { Authorization: `Bearer ${token}` }),
    ...options.headers,
  };

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    // Handle non-JSON responses
    const contentType = response.headers.get('content-type');
    const isJson = contentType && contentType.includes('application/json');
    const data = isJson ? await response.json() : await response.text();

    if (!response.ok) {
      const error = new Error(data.detail || data.message || 'Request failed');
      error.status = response.status;
      error.data = data;
      throw error;
    }

    return data;
  } catch (error) {
    if (error.status === 401) {
      removeToken();
      window.dispatchEvent(new CustomEvent('auth:logout'));
    }
    throw error;
  }
};

/**
 * Authentication API
 */
export const authApi = {
  /**
   * Register a new user
   */
  register: async (userData) => {
    const data = await request('/auth/register', {
      method: 'POST',
      body: JSON.stringify(userData),
    });
    if (data.access_token) {
      setToken(data.access_token);
    }
    return data;
  },

  /**
   * Login user
   */
  login: async (credentials) => {
    const data = await request('/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
    if (data.access_token) {
      setToken(data.access_token);
    }
    return data;
  },

  /**
   * Get current user
   */
  getMe: async () => {
    return request('/auth/me');
  },

  /**
   * Logout user
   */
  logout: async () => {
    try {
      await request('/auth/logout', { method: 'POST' });
    } finally {
      removeToken();
    }
  },

  /**
   * Check if user is authenticated
   */
  isAuthenticated: () => !!getToken(),
};

/**
 * Workspaces API
 */
export const workspacesApi = {
  /**
   * List all workspaces
   */
  list: async () => {
    return request('/workspaces');
  },

  /**
   * Get a workspace by ID
   */
  get: async (workspaceId) => {
    return request(`/workspaces/${workspaceId}`);
  },

  /**
   * Create a new workspace
   */
  create: async (data) => {
    return request('/workspaces', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * Update a workspace
   */
  update: async (workspaceId, data) => {
    return request(`/workspaces/${workspaceId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  /**
   * Delete a workspace
   */
  delete: async (workspaceId) => {
    return request(`/workspaces/${workspaceId}`, {
      method: 'DELETE',
    });
  },
};

/**
 * Chatrooms API
 */
export const chatroomsApi = {
  /**
   * List chatrooms in a workspace
   */
  list: async (workspaceId) => {
    return request(`/chatrooms?workspace_id=${workspaceId}`);
  },

  /**
   * Get a chatroom by ID
   */
  get: async (chatroomId) => {
    return request(`/chatrooms/${chatroomId}`);
  },

  /**
   * Create a new chatroom
   */
  create: async (data) => {
    return request('/chatrooms', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * Update a chatroom
   */
  update: async (chatroomId, data) => {
    return request(`/chatrooms/${chatroomId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  /**
   * Delete a chatroom
   */
  delete: async (chatroomId) => {
    return request(`/chatrooms/${chatroomId}`, {
      method: 'DELETE',
    });
  },
};

/**
 * Messages API
 */
export const messagesApi = {
  /**
   * List messages in a chatroom
   */
  list: async (chatroomId, { limit = 50, offset = 0 } = {}) => {
    return request(`/messages?chatroom_id=${chatroomId}&limit=${limit}&offset=${offset}`);
  },

  /**
   * Send a chat message (with RAG)
   */
  sendChat: async (data) => {
    return request('/messages/chat', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * Send a streaming chat message
   */
  sendChatStream: async (data, onChunk) => {
    const url = `${API_BASE_URL}/messages/chat/stream`;
    const token = getToken();

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Stream request failed');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            onChunk(data);
          } catch (e) {
            // Ignore parse errors
          }
        }
      }
    }
  },

  /**
   * Delete a message
   */
  delete: async (messageId) => {
    return request(`/messages/${messageId}`, {
      method: 'DELETE',
    });
  },
};

/**
 * Documents API
 */
export const documentsApi = {
  /**
   * List documents
   */
  list: async (workspaceId = null) => {
    const params = workspaceId ? `?workspace_id=${workspaceId}` : '';
    return request(`/documents${params}`);
  },

  /**
   * Get a document by ID
   */
  get: async (documentId) => {
    return request(`/documents/${documentId}`);
  },

  /**
   * Upload a document
   */
  upload: async (file, workspaceId, description = null) => {
    const token = getToken();
    const formData = new FormData();
    formData.append('file', file);
    formData.append('workspace_id', workspaceId);
    if (description) {
      formData.append('description', description);
    }

    const response = await fetch(`${API_BASE_URL}/documents/upload`, {
      method: 'POST',
      headers: {
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Upload failed');
    }

    return response.json();
  },

  /**
   * Get document status
   */
  getStatus: async (documentId) => {
    return request(`/documents/${documentId}/status`);
  },

  /**
   * Delete a document
   */
  delete: async (documentId) => {
    return request(`/documents/${documentId}`, {
      method: 'DELETE',
    });
  },
};

/**
 * RAG API
 */
export const ragApi = {
  /**
   * Execute a RAG query
   */
  query: async (data) => {
    return request('/rag/query', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * Get RAG configuration
   */
  getConfig: async () => {
    return request('/rag/config');
  },

  /**
   * Check RAG health
   */
  health: async () => {
    return request('/rag/health');
  },

  /**
   * Clear conversation memory
   */
  clearMemory: async (conversationId = null) => {
    const params = conversationId ? `?conversation_id=${conversationId}` : '';
    return request(`/rag/clear-memory${params}`, {
      method: 'POST',
    });
  },
};

export default {
  auth: authApi,
  workspaces: workspacesApi,
  chatrooms: chatroomsApi,
  messages: messagesApi,
  documents: documentsApi,
  rag: ragApi,
};
