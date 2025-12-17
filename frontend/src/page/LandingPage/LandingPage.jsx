/**
 * Landing Page Component
 *
 * Main entry page for the Talos application.
 */

import { useNavigate } from 'react-router-dom';
import styled from 'styled-components';
import { useAuth } from '../../context';

const PageContainer = styled.div`
  min-height: 100vh;
  background: linear-gradient(135deg, #24273a 0%, #363a4f 100%);
  color: #cad3f5;
  display: flex;
  flex-direction: column;
`;

const Header = styled.header`
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 40px;
  border-bottom: 1px solid #51536a;
`;

const Logo = styled.div`
  font-size: 1.8rem;
  font-weight: 700;
  color: #c6a0f6;
  display: flex;
  align-items: center;
  gap: 10px;

  i {
    font-size: 2rem;
  }
`;

const NavButtons = styled.div`
  display: flex;
  gap: 12px;
`;

const Button = styled.button`
  padding: 10px 24px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;

  ${(props) =>
    props.$primary
      ? `
    background: #c6a0f6;
    color: #24273a;
    &:hover {
      background: #b78bf5;
      transform: translateY(-2px);
    }
  `
      : `
    background: transparent;
    color: #cad3f5;
    border: 1px solid #51536a;
    &:hover {
      background: rgba(198, 160, 246, 0.1);
      border-color: #c6a0f6;
    }
  `}
`;

const HeroSection = styled.main`
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  text-align: center;
  padding: 40px;
`;

const HeroTitle = styled.h1`
  font-size: 3.5rem;
  font-weight: 700;
  margin-bottom: 20px;
  background: linear-gradient(135deg, #c6a0f6, #8aadf4);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;

  @media (max-width: 768px) {
    font-size: 2.5rem;
  }
`;

const HeroSubtitle = styled.p`
  font-size: 1.3rem;
  color: #a5adcb;
  max-width: 600px;
  margin-bottom: 40px;
  line-height: 1.6;
`;

const FeatureGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px;
  max-width: 1000px;
  margin-top: 60px;
  padding: 0 20px;
`;

const FeatureCard = styled.div`
  background: rgba(54, 58, 79, 0.5);
  border: 1px solid #51536a;
  border-radius: 12px;
  padding: 24px;
  text-align: left;
  transition: all 0.2s ease;

  &:hover {
    border-color: #c6a0f6;
    transform: translateY(-4px);
  }

  i {
    font-size: 2rem;
    color: #c6a0f6;
    margin-bottom: 16px;
  }

  h3 {
    font-size: 1.2rem;
    margin-bottom: 8px;
    color: #cad3f5;
  }

  p {
    color: #a5adcb;
    font-size: 0.95rem;
    line-height: 1.5;
  }
`;

const Footer = styled.footer`
  padding: 20px 40px;
  text-align: center;
  color: #6e738d;
  border-top: 1px solid #51536a;
`;

const LandingPage = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const handleGetStarted = () => {
    if (isAuthenticated) {
      navigate('/chat');
    } else {
      navigate('/login');
    }
  };

  return (
    <PageContainer>
      <Header>
        <Logo>
          <i className="bi bi-robot" />
          Talos
        </Logo>
        <NavButtons>
          {isAuthenticated ? (
            <Button $primary onClick={() => navigate('/chat')}>
              Go to Chat
            </Button>
          ) : (
            <>
              <Button onClick={() => navigate('/login')}>Sign In</Button>
              <Button $primary onClick={() => navigate('/login?register=true')}>
                Get Started
              </Button>
            </>
          )}
        </NavButtons>
      </Header>

      <HeroSection>
        <HeroTitle>AI-Powered Knowledge Assistant</HeroTitle>
        <HeroSubtitle>
          Transform your documents into intelligent conversations. Upload your files,
          ask questions, and get accurate answers with source citations.
        </HeroSubtitle>
        <Button $primary onClick={handleGetStarted} style={{ fontSize: '1.1rem', padding: '14px 32px' }}>
          <i className="bi bi-lightning-charge" style={{ marginRight: '8px' }} />
          Start Chatting
        </Button>

        <FeatureGrid>
          <FeatureCard>
            <i className="bi bi-file-earmark-text" />
            <h3>Document Ingestion</h3>
            <p>Upload PDFs, text files, and more. Our system automatically processes and indexes your content.</p>
          </FeatureCard>

          <FeatureCard>
            <i className="bi bi-search" />
            <h3>Intelligent Retrieval</h3>
            <p>Advanced hybrid search combines semantic understanding with keyword matching for precise results.</p>
          </FeatureCard>

          <FeatureCard>
            <i className="bi bi-chat-dots" />
            <h3>Natural Conversations</h3>
            <p>Ask questions naturally and get contextual answers that reference your documents.</p>
          </FeatureCard>

          <FeatureCard>
            <i className="bi bi-bookmark-check" />
            <h3>Source Citations</h3>
            <p>Every answer includes citations back to the original source documents for verification.</p>
          </FeatureCard>

          <FeatureCard>
            <i className="bi bi-people" />
            <h3>Workspaces</h3>
            <p>Organize your knowledge into separate workspaces for different projects or teams.</p>
          </FeatureCard>

          <FeatureCard>
            <i className="bi bi-shield-lock" />
            <h3>Secure & Private</h3>
            <p>Your data stays private. Full control over what you share and who can access it.</p>
          </FeatureCard>
        </FeatureGrid>
      </HeroSection>

      <Footer>
        <p>Talos RAG System - Graduation Project 2025</p>
      </Footer>
    </PageContainer>
  );
};

export default LandingPage;
