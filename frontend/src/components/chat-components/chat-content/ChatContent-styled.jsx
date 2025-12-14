import { Container } from "react-bootstrap";
import styled from "styled-components";

export const ChatHeaderBar = styled(Container)`
  background-color: #363a4f;
  height: 60px;
  width: 100%;
  padding: 0px;
  border: 1px solid #51536aff;
  color: #a5adcb;
  display: flex;
  align-items: center;
  padding-left: 32px;

  i {
    padding-right: 16px;
  }
`;

export const ChatContentContainer = styled(Container)`
  background-color: #24273a;
  height: calc(100vh - 140px);
`;

export const ChatContentInputBar = styled(Container)`
  height: 80px;
  background-color: #363a4f;
  border: 1px solid #51536aff;
  display: flex;
  align-items: center;
  gap: 8px;
`;

export const ChatTextField = styled.input`
  background-color: #3f435a;
  border: 1px solid #51536aff;
  border-radius: 8px;
  color: #a5adcb;
  width: calc(100% - 60px);
  margin: 8px;
  padding-left: 16px;
  height: 40px;

  outline: none;
  box-shadow: none;

  &:focus,
  &:active {
    border: 1px solid #51536aff;
    outline: none;
    box-shadow: none;
  }
`;

export const ChatSendButton = styled.div`
  background-color: #c6a0f6;
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
`;
