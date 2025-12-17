import React from "react";
import { Container, Row, Col, Button } from "react-bootstrap";
import {
  ChatContentContainer,
  ChatContentInputBar,
  ChatHeaderBar,
  ChatTextField,
  ChatSendButton,
} from "./ChatContent-styled";

const ChatContent = () => {
  return (
    <Container fluid>
      <Row>
        <ChatHeaderBar>
          <i class="bi bi-robot" />
          AI Assistant
        </ChatHeaderBar>
      </Row>
      <Row>
        <ChatContentContainer></ChatContentContainer>
      </Row>
      <Row>
        <ChatContentInputBar fluid>
          <ChatTextField
            type="text"
            id="message"
            placeholder="Message AI Assistant"
          ></ChatTextField>
          <ChatSendButton>
            <i class="bi bi-send" />
          </ChatSendButton>
        </ChatContentInputBar>
      </Row>
    </Container>
  );
};

export default ChatContent;
