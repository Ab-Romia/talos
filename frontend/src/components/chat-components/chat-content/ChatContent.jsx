/**
 * Chat Content Component
 *
 * Main chat area with messages and input.
 */

import React, { useState, useRef, useEffect } from "react";
import { Container, Row, Spinner } from "react-bootstrap";
import styled from "styled-components";
import {
  ChatContentContainer,
  ChatContentInputBar,
  ChatHeaderBar,
  ChatTextField,
  ChatSendButton,
} from "./ChatContent-styled";
import { useWorkspace, useChat } from "../../../context";

const MessageContainer = styled.div`
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  overflow-y: auto;
  height: 100%;
`;

const MessageBubble = styled.div`
  max-width: 80%;
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.5;
  ${(props) =>
    props.$isUser
      ? `
    align-self: flex-end;
    background: #c6a0f6;
    color: #24273a;
    border-bottom-right-radius: 4px;
  `
      : `
    align-self: flex-start;
    background: #3f435a;
    color: #cad3f5;
    border-bottom-left-radius: 4px;
  `}
`;

const MessageMeta = styled.div`
  font-size: 0.75rem;
  color: #6e738d;
  margin-top: 4px;
  ${(props) => (props.$isUser ? "text-align: right;" : "text-align: left;")}
`;

const SourcesContainer = styled.div`
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
`;

const SourcesTitle = styled.div`
  font-size: 0.8rem;
  color: #a5adcb;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
`;

const SourceItem = styled.div`
  font-size: 0.75rem;
  color: #8aadf4;
  padding: 6px 10px;
  background: rgba(138, 173, 244, 0.1);
  border-radius: 6px;
  margin-bottom: 4px;
  cursor: pointer;

  &:hover {
    background: rgba(138, 173, 244, 0.2);
  }
`;

const EmptyState = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #6e738d;
  text-align: center;
  padding: 40px;

  i {
    font-size: 4rem;
    margin-bottom: 16px;
    color: #51536a;
  }

  h3 {
    color: #a5adcb;
    margin-bottom: 8px;
  }
`;

const LoadingIndicator = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  color: #a5adcb;
  font-size: 0.9rem;
`;

const StreamingIndicator = styled.span`
  display: inline-block;
  width: 8px;
  height: 8px;
  background: #c6a0f6;
  border-radius: 50%;
  animation: pulse 1s infinite;

  @keyframes pulse {
    0%, 100% {
      opacity: 1;
    }
    50% {
      opacity: 0.4;
    }
  }
`;

const ChatContent = () => {
  const { currentChatroom, currentWorkspace } = useWorkspace();
  const {
    messages,
    loading,
    sending,
    streaming,
    sendMessage,
    error,
  } = useChat();

  const [inputValue, setInputValue] = useState("");
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  // Focus input when chatroom changes
  useEffect(() => {
    if (currentChatroom && inputRef.current) {
      inputRef.current.focus();
    }
  }, [currentChatroom]);

  const handleSend = async () => {
    if (inputValue.trim() && !sending && !streaming) {
      const message = inputValue;
      setInputValue("");
      await sendMessage(message, false); // Set to true for streaming
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const formatTime = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  if (!currentWorkspace) {
    return (
      <Container fluid style={{ height: "100%" }}>
        <EmptyState>
          <i className="bi bi-briefcase" />
          <h3>No Workspace Selected</h3>
          <p>Create or select a workspace from the sidebar to get started.</p>
        </EmptyState>
      </Container>
    );
  }

  if (!currentChatroom) {
    return (
      <Container fluid style={{ height: "100%" }}>
        <EmptyState>
          <i className="bi bi-chat-dots" />
          <h3>No Chatroom Selected</h3>
          <p>Create or select a chatroom from the sidebar to start chatting.</p>
        </EmptyState>
      </Container>
    );
  }

  return (
    <Container fluid style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <Row>
        <ChatHeaderBar>
          <i className="bi bi-chat" />
          {currentChatroom.name}
        </ChatHeaderBar>
      </Row>

      <Row style={{ flex: 1, overflow: "hidden" }}>
        <ChatContentContainer>
          {loading && messages.length === 0 ? (
            <LoadingIndicator>
              <Spinner animation="border" size="sm" />
              Loading messages...
            </LoadingIndicator>
          ) : messages.length === 0 ? (
            <EmptyState>
              <i className="bi bi-chat-square-text" />
              <h3>Start a Conversation</h3>
              <p>Send a message to start chatting with the AI assistant.</p>
            </EmptyState>
          ) : (
            <MessageContainer>
              {messages.map((message) => (
                <div key={message.id}>
                  <MessageBubble $isUser={message.role === "user"}>
                    {message.content}
                    {message.isStreaming && <StreamingIndicator />}

                    {message.sources && message.sources.length > 0 && (
                      <SourcesContainer>
                        <SourcesTitle>
                          <i className="bi bi-bookmark" />
                          Sources ({message.sources.length})
                        </SourcesTitle>
                        {message.sources.slice(0, 3).map((source, idx) => (
                          <SourceItem key={idx}>
                            {source.document_name || `Source ${idx + 1}`}
                            {source.page && ` (Page ${source.page})`}
                          </SourceItem>
                        ))}
                      </SourcesContainer>
                    )}
                  </MessageBubble>
                  <MessageMeta $isUser={message.role === "user"}>
                    {message.sender_name} • {formatTime(message.created_at)}
                  </MessageMeta>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </MessageContainer>
          )}
        </ChatContentContainer>
      </Row>

      {error && (
        <Row>
          <div
            style={{
              padding: "8px 16px",
              background: "rgba(237, 135, 150, 0.1)",
              color: "#ed8796",
              fontSize: "0.85rem",
            }}
          >
            {error}
          </div>
        </Row>
      )}

      <Row>
        <ChatContentInputBar fluid>
          <ChatTextField
            ref={inputRef}
            type="text"
            id="message"
            placeholder={`Message ${currentChatroom.name}...`}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={sending || streaming}
          />
          <ChatSendButton
            onClick={handleSend}
            disabled={!inputValue.trim() || sending || streaming}
          >
            {sending || streaming ? (
              <Spinner animation="border" size="sm" />
            ) : (
              <i className="bi bi-send" />
            )}
          </ChatSendButton>
        </ChatContentInputBar>
      </Row>
    </Container>
  );
};

export default ChatContent;
