/**
 * Chat Context
 *
 * Manages chat messages and AI interactions.
 */

import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { messagesApi } from '../services/api';
import { useWorkspace } from './WorkspaceContext';

const ChatContext = createContext(null);

export const useChat = () => {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return context;
};

export const ChatProvider = ({ children }) => {
  const { currentChatroom } = useWorkspace();
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [error, setError] = useState(null);
  const [hasMore, setHasMore] = useState(true);
  const abortControllerRef = useRef(null);

  // Load messages when chatroom changes
  useEffect(() => {
    if (currentChatroom) {
      loadMessages();
    } else {
      setMessages([]);
      setHasMore(true);
    }
  }, [currentChatroom]);

  const loadMessages = useCallback(async (append = false) => {
    if (!currentChatroom) return;

    setLoading(true);
    setError(null);
    try {
      const offset = append ? messages.length : 0;
      const response = await messagesApi.list(currentChatroom.id, {
        limit: 50,
        offset,
      });

      if (append) {
        setMessages((prev) => [...response.messages, ...prev]);
      } else {
        setMessages(response.messages || []);
      }
      setHasMore(response.has_more);
    } catch (err) {
      setError(err.message || 'Failed to load messages');
    } finally {
      setLoading(false);
    }
  }, [currentChatroom, messages.length]);

  const sendMessage = useCallback(async (content, useStreaming = false) => {
    if (!currentChatroom || !content.trim()) return;

    setSending(true);
    setError(null);

    // Add optimistic user message
    const tempUserMessage = {
      id: `temp-${Date.now()}`,
      content: content.trim(),
      role: 'user',
      sender_name: 'You',
      created_at: new Date().toISOString(),
      chatroom_id: currentChatroom.id,
    };
    setMessages((prev) => [...prev, tempUserMessage]);

    try {
      if (useStreaming) {
        setStreaming(true);
        setStreamingContent('');

        // Add temporary AI message for streaming
        const tempAiMessage = {
          id: `temp-ai-${Date.now()}`,
          content: '',
          role: 'assistant',
          sender_name: 'AI Assistant',
          created_at: new Date().toISOString(),
          chatroom_id: currentChatroom.id,
          isStreaming: true,
        };
        setMessages((prev) => [...prev, tempAiMessage]);

        await messagesApi.sendChatStream(
          {
            message: content.trim(),
            chatroom_id: currentChatroom.id,
            include_sources: true,
            stream: true,
          },
          (chunk) => {
            if (chunk.content) {
              setStreamingContent((prev) => prev + chunk.content);
              setMessages((prev) =>
                prev.map((m) =>
                  m.isStreaming
                    ? { ...m, content: m.content + chunk.content }
                    : m
                )
              );
            }
            if (chunk.done) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.isStreaming
                    ? {
                        ...m,
                        id: chunk.message_id || m.id,
                        isStreaming: false,
                        sources: chunk.sources,
                      }
                    : m
                )
              );
              setStreaming(false);
              setStreamingContent('');
            }
          }
        );
      } else {
        const response = await messagesApi.sendChat({
          message: content.trim(),
          chatroom_id: currentChatroom.id,
          include_sources: true,
          stream: false,
        });

        // Add AI response
        setMessages((prev) => [
          ...prev.filter((m) => !m.id.startsWith('temp-')),
          {
            ...tempUserMessage,
            id: `user-${Date.now()}`, // Real message doesn't have ID returned
          },
          {
            id: response.message.id,
            content: response.message.content,
            role: 'assistant',
            sender_name: 'AI Assistant',
            created_at: response.message.created_at,
            chatroom_id: currentChatroom.id,
            sources: response.sources,
          },
        ]);
      }
    } catch (err) {
      setError(err.message || 'Failed to send message');
      // Remove optimistic message on error
      setMessages((prev) =>
        prev.filter(
          (m) => !m.id.startsWith('temp-') && !m.isStreaming
        )
      );
    } finally {
      setSending(false);
      setStreaming(false);
    }
  }, [currentChatroom]);

  const deleteMessage = useCallback(async (messageId) => {
    try {
      await messagesApi.delete(messageId);
      setMessages((prev) => prev.filter((m) => m.id !== messageId));
    } catch (err) {
      setError(err.message || 'Failed to delete message');
    }
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setHasMore(true);
  }, []);

  const cancelStreaming = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStreaming(false);
    setStreamingContent('');
    setMessages((prev) => prev.filter((m) => !m.isStreaming));
  }, []);

  const value = {
    messages,
    loading,
    sending,
    streaming,
    streamingContent,
    error,
    hasMore,
    loadMessages,
    sendMessage,
    deleteMessage,
    clearMessages,
    cancelStreaming,
    clearError: () => setError(null),
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
};

export default ChatContext;
