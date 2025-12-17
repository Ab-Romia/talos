import React from "react";
import { Button } from "react-bootstrap";
import {
  SidebarButtonGroupContainer,
  SidebarContainerWrapper,
  SidebarGroupContainerHeader,
  SidebarButton,
  SidebarDivider,
  SidebarCurrentWorkspace,
} from "./ChatSidebar-styled";

const ChatSidebar = () => {
  return (
    <>
      <SidebarContainerWrapper>
        <SidebarButton className="mt-3">
          <i class="bi bi-arrow-left" />
          Back to Workspaces
        </SidebarButton>

        <SidebarDivider />

        <SidebarCurrentWorkspace>
          <i class="bi bi-briefcase" />
          Work
        </SidebarCurrentWorkspace>

        <SidebarDivider />

        <SidebarButtonGroupContainer>
          <SidebarGroupContainerHeader>
            Channels
            <Button>
              <i class="bi bi-plus" />
            </Button>
          </SidebarGroupContainerHeader>
          <SidebarButton>
            <i class="bi bi-hash" />
            general
          </SidebarButton>
          <SidebarButton>
            <i class="bi bi-hash" />
            announcements
          </SidebarButton>
          <SidebarButton>
            <i class="bi bi-hash" />
            projects
          </SidebarButton>
          <SidebarButton>
            <i class="bi bi-hash" />
            resources
          </SidebarButton>
          <SidebarButton>
            <i class="bi bi-lock" />
            private-notes
          </SidebarButton>
        </SidebarButtonGroupContainer>

        <SidebarDivider />

        <SidebarButtonGroupContainer>
          <SidebarGroupContainerHeader className="pb-2">
            Direct Messages
          </SidebarGroupContainerHeader>
          <SidebarButton>
            <i class="bi bi-person-circle" />
            Team Member 1
          </SidebarButton>
          <SidebarButton>
            <i class="bi bi-person-circle" />
            Team Member 2
          </SidebarButton>
          <SidebarButton>
            <i class="bi bi-person-circle" />
            Team Member 3
          </SidebarButton>
          <SidebarButton>
            <i class="bi bi-robot" />
            AI Assistant
          </SidebarButton>
        </SidebarButtonGroupContainer>
      </SidebarContainerWrapper>
    </>
  );
};

export default ChatSidebar;
