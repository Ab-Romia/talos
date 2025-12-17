/**
 * Chat Sidebar Component
 *
 * Displays workspaces, chatrooms, and navigation.
 */

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Modal, Form } from "react-bootstrap";
import {
  SidebarButtonGroupContainer,
  SidebarContainerWrapper,
  SidebarGroupContainerHeader,
  SidebarButton,
  SidebarDivider,
  SidebarCurrentWorkspace,
} from "./ChatSidebar-styled";
import { useAuth, useWorkspace } from "../../../context";

const ChatSidebar = () => {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const {
    workspaces,
    currentWorkspace,
    chatrooms,
    currentChatroom,
    selectWorkspace,
    selectChatroom,
    createWorkspace,
    createChatroom,
    loading,
  } = useWorkspace();

  const [showWorkspaceModal, setShowWorkspaceModal] = useState(false);
  const [showChatroomModal, setShowChatroomModal] = useState(false);
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [newChatroomName, setNewChatroomName] = useState("");
  const [showWorkspaceList, setShowWorkspaceList] = useState(false);

  const handleCreateWorkspace = async (e) => {
    e.preventDefault();
    if (newWorkspaceName.trim()) {
      try {
        await createWorkspace(newWorkspaceName.trim());
        setNewWorkspaceName("");
        setShowWorkspaceModal(false);
      } catch (err) {
        // Error handled by context
      }
    }
  };

  const handleCreateChatroom = async (e) => {
    e.preventDefault();
    if (newChatroomName.trim()) {
      try {
        await createChatroom(newChatroomName.trim());
        setNewChatroomName("");
        setShowChatroomModal(false);
      } catch (err) {
        // Error handled by context
      }
    }
  };

  const handleLogout = async () => {
    await logout();
    navigate("/");
  };

  if (showWorkspaceList) {
    return (
      <SidebarContainerWrapper>
        <SidebarButton className="mt-3" onClick={() => setShowWorkspaceList(false)}>
          <i className="bi bi-arrow-left" />
          Back
        </SidebarButton>

        <SidebarDivider />

        <SidebarButtonGroupContainer>
          <SidebarGroupContainerHeader>
            Your Workspaces
            <Button onClick={() => setShowWorkspaceModal(true)}>
              <i className="bi bi-plus" />
            </Button>
          </SidebarGroupContainerHeader>

          {workspaces.length === 0 ? (
            <SidebarButton style={{ opacity: 0.6 }}>
              <i className="bi bi-info-circle" />
              No workspaces yet
            </SidebarButton>
          ) : (
            workspaces.map((workspace) => (
              <SidebarButton
                key={workspace.id}
                onClick={() => {
                  selectWorkspace(workspace);
                  setShowWorkspaceList(false);
                }}
                style={{
                  background:
                    currentWorkspace?.id === workspace.id
                      ? "rgba(198, 160, 246, 0.2)"
                      : "transparent",
                }}
              >
                <i className="bi bi-briefcase" />
                {workspace.name}
              </SidebarButton>
            ))
          )}
        </SidebarButtonGroupContainer>

        <SidebarDivider />

        <SidebarButton onClick={handleLogout} style={{ color: "#ed8796" }}>
          <i className="bi bi-box-arrow-left" />
          Sign Out
        </SidebarButton>

        {/* Create Workspace Modal */}
        <Modal show={showWorkspaceModal} onHide={() => setShowWorkspaceModal(false)} centered>
          <Modal.Header closeButton style={{ background: "#363a4f", borderColor: "#51536a" }}>
            <Modal.Title style={{ color: "#cad3f5" }}>Create Workspace</Modal.Title>
          </Modal.Header>
          <Modal.Body style={{ background: "#363a4f" }}>
            <Form onSubmit={handleCreateWorkspace}>
              <Form.Group>
                <Form.Control
                  type="text"
                  placeholder="Workspace name"
                  value={newWorkspaceName}
                  onChange={(e) => setNewWorkspaceName(e.target.value)}
                  style={{
                    background: "#24273a",
                    border: "1px solid #51536a",
                    color: "#cad3f5",
                  }}
                  autoFocus
                />
              </Form.Group>
            </Form>
          </Modal.Body>
          <Modal.Footer style={{ background: "#363a4f", borderColor: "#51536a" }}>
            <Button variant="secondary" onClick={() => setShowWorkspaceModal(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleCreateWorkspace}
              disabled={!newWorkspaceName.trim() || loading}
              style={{ background: "#c6a0f6", borderColor: "#c6a0f6" }}
            >
              Create
            </Button>
          </Modal.Footer>
        </Modal>
      </SidebarContainerWrapper>
    );
  }

  return (
    <SidebarContainerWrapper>
      <SidebarButton className="mt-3" onClick={() => setShowWorkspaceList(true)}>
        <i className="bi bi-arrow-left" />
        Back to Workspaces
      </SidebarButton>

      <SidebarDivider />

      {currentWorkspace ? (
        <>
          <SidebarCurrentWorkspace>
            <i className="bi bi-briefcase" />
            {currentWorkspace.name}
          </SidebarCurrentWorkspace>

          <SidebarDivider />

          <SidebarButtonGroupContainer>
            <SidebarGroupContainerHeader>
              Chatrooms
              <Button onClick={() => setShowChatroomModal(true)}>
                <i className="bi bi-plus" />
              </Button>
            </SidebarGroupContainerHeader>

            {chatrooms.length === 0 ? (
              <SidebarButton style={{ opacity: 0.6 }}>
                <i className="bi bi-info-circle" />
                No chatrooms yet
              </SidebarButton>
            ) : (
              chatrooms.map((chatroom) => (
                <SidebarButton
                  key={chatroom.id}
                  onClick={() => selectChatroom(chatroom)}
                  style={{
                    background:
                      currentChatroom?.id === chatroom.id
                        ? "rgba(198, 160, 246, 0.2)"
                        : "transparent",
                  }}
                >
                  <i className="bi bi-chat" />
                  {chatroom.name}
                </SidebarButton>
              ))
            )}
          </SidebarButtonGroupContainer>

          <SidebarDivider />

          <SidebarButtonGroupContainer>
            <SidebarGroupContainerHeader className="pb-2">
              Quick Actions
            </SidebarGroupContainerHeader>
            <SidebarButton>
              <i className="bi bi-robot" />
              AI Assistant
            </SidebarButton>
            <SidebarButton>
              <i className="bi bi-file-earmark-plus" />
              Upload Document
            </SidebarButton>
          </SidebarButtonGroupContainer>
        </>
      ) : (
        <SidebarButton style={{ opacity: 0.6 }}>
          <i className="bi bi-info-circle" />
          Select a workspace
        </SidebarButton>
      )}

      <SidebarDivider />

      <SidebarButtonGroupContainer style={{ marginTop: "auto" }}>
        <SidebarButton style={{ opacity: 0.8 }}>
          <i className="bi bi-person-circle" />
          {user?.name || user?.username || "User"}
        </SidebarButton>
      </SidebarButtonGroupContainer>

      {/* Create Chatroom Modal */}
      <Modal show={showChatroomModal} onHide={() => setShowChatroomModal(false)} centered>
        <Modal.Header closeButton style={{ background: "#363a4f", borderColor: "#51536a" }}>
          <Modal.Title style={{ color: "#cad3f5" }}>Create Chatroom</Modal.Title>
        </Modal.Header>
        <Modal.Body style={{ background: "#363a4f" }}>
          <Form onSubmit={handleCreateChatroom}>
            <Form.Group>
              <Form.Control
                type="text"
                placeholder="Chatroom name"
                value={newChatroomName}
                onChange={(e) => setNewChatroomName(e.target.value)}
                style={{
                  background: "#24273a",
                  border: "1px solid #51536a",
                  color: "#cad3f5",
                }}
                autoFocus
              />
            </Form.Group>
          </Form>
        </Modal.Body>
        <Modal.Footer style={{ background: "#363a4f", borderColor: "#51536a" }}>
          <Button variant="secondary" onClick={() => setShowChatroomModal(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleCreateChatroom}
            disabled={!newChatroomName.trim() || loading}
            style={{ background: "#c6a0f6", borderColor: "#c6a0f6" }}
          >
            Create
          </Button>
        </Modal.Footer>
      </Modal>
    </SidebarContainerWrapper>
  );
};

export default ChatSidebar;
