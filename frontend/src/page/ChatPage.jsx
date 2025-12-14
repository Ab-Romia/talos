import React from "react";
import ChatSidebar from "../components/chat-components/chat-sidebar/ChatSidebar";
import ChatContent from "../components/chat-components/chat-content/ChatContent";
import {
  ChatPageLayout,
  ContentLayoutWrapper,
  SidebarLayoutWrapper,
} from "./Layouts-styled";

const ChatPage = () => {
  return (
    <>
      <ChatPageLayout>
        <SidebarLayoutWrapper>
          <ChatSidebar />
        </SidebarLayoutWrapper>
        <ContentLayoutWrapper>
          <ChatContent />
        </ContentLayoutWrapper>
      </ChatPageLayout>
    </>
  );
};

export default ChatPage;
