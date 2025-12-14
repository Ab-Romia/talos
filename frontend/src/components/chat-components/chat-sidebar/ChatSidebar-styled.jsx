import { Button } from "react-bootstrap";
import styled from "styled-components";

export const SidebarContainerWrapper = styled.div`
  background-color: #363a4f;
  color: #a5adcb;
  min-height: 100vh;
  min-width: 200px;
  padding: 8px;
  padding-left: 16px;
  padding-right: 16px;
  font-size: 14px;
  margin-left: 0;

  @media (max-width: 1300px) {
    position: relative;
    width: 100%;
    min-width: 170px;
  }
`;

export const SidebarButtonGroupContainer = styled.div`
  display: flex;
  flex-direction: column;
  padding: 0;
  gap: 0.5rem;

  button {
    background-color: #363a4f;
    color: #a5adcb;
    padding-left: 8px;
    border: none;
    font-size: inherit;
    &:hover {
      background-color: #534e70;
    }
  }
`;

export const SidebarGroupContainerHeader = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

export const SidebarButton = styled(Button)`
  display: flex;
  align-items: center;
  justify-content: left;
  padding: 4px;
  padding-left: 2px;
  padding-vertical: 4;

  background-color: #363a4f;
  color: #a5adcb;
  border: none;
  width: 100%;
  font-size: inherit;
  &:hover {
    background-color: #534e70;
  }

  i {
    padding-right: 8px;
  }
`;

export const SidebarDivider = styled.hr`
  padding: 0;
  margin-top: 16px;
  margin-bottom: 16px;
`;

export const SidebarCurrentWorkspace = styled.div`
  background-color: #51536aff;
  box-shadow: 0 4px 4px rgba(0, 0, 0, 0.08);
  padding: 8px;
  border-radius: 8px;
  font-size: 16px;
  padding-left: 16px;

  i {
    padding-right: 12px;
  }
`;
