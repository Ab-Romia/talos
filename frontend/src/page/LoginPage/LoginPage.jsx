/**
 * Login Page Component
 *
 * Handles user authentication (login and registration).
 */

import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import styled from 'styled-components';
import { useAuth } from '../../context';

const PageContainer = styled.div`
  min-height: 100vh;
  background: linear-gradient(135deg, #24273a 0%, #363a4f 100%);
  color: #cad3f5;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 20px;
`;

const FormCard = styled.div`
  background: #363a4f;
  border: 1px solid #51536a;
  border-radius: 16px;
  padding: 40px;
  width: 100%;
  max-width: 420px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
`;

const Logo = styled.div`
  text-align: center;
  margin-bottom: 32px;

  i {
    font-size: 3rem;
    color: #c6a0f6;
  }

  h1 {
    font-size: 1.8rem;
    margin-top: 12px;
    color: #cad3f5;
  }
`;

const TabContainer = styled.div`
  display: flex;
  margin-bottom: 24px;
  border-bottom: 1px solid #51536a;
`;

const Tab = styled.button`
  flex: 1;
  padding: 12px;
  background: none;
  border: none;
  color: ${(props) => (props.$active ? '#c6a0f6' : '#a5adcb')};
  font-weight: 600;
  cursor: pointer;
  border-bottom: 2px solid ${(props) => (props.$active ? '#c6a0f6' : 'transparent')};
  transition: all 0.2s ease;

  &:hover {
    color: #c6a0f6;
  }
`;

const Form = styled.form`
  display: flex;
  flex-direction: column;
  gap: 16px;
`;

const FormGroup = styled.div`
  display: flex;
  flex-direction: column;
  gap: 6px;
`;

const Label = styled.label`
  font-size: 0.9rem;
  color: #a5adcb;
`;

const Input = styled.input`
  padding: 12px 16px;
  background: #24273a;
  border: 1px solid #51536a;
  border-radius: 8px;
  color: #cad3f5;
  font-size: 1rem;
  transition: border-color 0.2s ease;

  &:focus {
    outline: none;
    border-color: #c6a0f6;
  }

  &::placeholder {
    color: #6e738d;
  }
`;

const Button = styled.button`
  padding: 14px;
  background: #c6a0f6;
  color: #24273a;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 1rem;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-top: 8px;

  &:hover:not(:disabled) {
    background: #b78bf5;
    transform: translateY(-2px);
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
`;

const ErrorMessage = styled.div`
  background: rgba(237, 135, 150, 0.1);
  border: 1px solid #ed8796;
  color: #ed8796;
  padding: 12px;
  border-radius: 8px;
  font-size: 0.9rem;
  margin-bottom: 16px;
`;

const BackLink = styled.a`
  display: block;
  text-align: center;
  margin-top: 24px;
  color: #a5adcb;
  text-decoration: none;
  font-size: 0.9rem;
  cursor: pointer;

  &:hover {
    color: #c6a0f6;
  }
`;

const LoginPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login, register, isAuthenticated, loading, error, clearError } = useAuth();

  const [isRegister, setIsRegister] = useState(searchParams.get('register') === 'true');
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
    name: '',
  });
  const [validationError, setValidationError] = useState('');

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/chat');
    }
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    clearError();
    setValidationError('');
  }, [isRegister]);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    setValidationError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setValidationError('');

    try {
      if (isRegister) {
        // Validate registration
        if (formData.password !== formData.confirmPassword) {
          setValidationError('Passwords do not match');
          return;
        }
        if (formData.password.length < 8) {
          setValidationError('Password must be at least 8 characters');
          return;
        }

        await register({
          username: formData.username,
          email: formData.email,
          password: formData.password,
          name: formData.name || null,
        });
      } else {
        await login(formData.email, formData.password);
      }
    } catch (err) {
      // Error is handled by context
    }
  };

  const displayError = validationError || error;

  return (
    <PageContainer>
      <FormCard>
        <Logo>
          <i className="bi bi-robot" />
          <h1>Talos</h1>
        </Logo>

        <TabContainer>
          <Tab $active={!isRegister} onClick={() => setIsRegister(false)}>
            Sign In
          </Tab>
          <Tab $active={isRegister} onClick={() => setIsRegister(true)}>
            Register
          </Tab>
        </TabContainer>

        {displayError && <ErrorMessage>{displayError}</ErrorMessage>}

        <Form onSubmit={handleSubmit}>
          {isRegister && (
            <>
              <FormGroup>
                <Label>Username</Label>
                <Input
                  type="text"
                  name="username"
                  value={formData.username}
                  onChange={handleChange}
                  placeholder="Choose a username"
                  required
                  minLength={3}
                />
              </FormGroup>

              <FormGroup>
                <Label>Name (optional)</Label>
                <Input
                  type="text"
                  name="name"
                  value={formData.name}
                  onChange={handleChange}
                  placeholder="Your display name"
                />
              </FormGroup>
            </>
          )}

          <FormGroup>
            <Label>Email</Label>
            <Input
              type="email"
              name="email"
              value={formData.email}
              onChange={handleChange}
              placeholder="Enter your email"
              required
            />
          </FormGroup>

          <FormGroup>
            <Label>Password</Label>
            <Input
              type="password"
              name="password"
              value={formData.password}
              onChange={handleChange}
              placeholder={isRegister ? 'Create a password' : 'Enter your password'}
              required
              minLength={isRegister ? 8 : 1}
            />
          </FormGroup>

          {isRegister && (
            <FormGroup>
              <Label>Confirm Password</Label>
              <Input
                type="password"
                name="confirmPassword"
                value={formData.confirmPassword}
                onChange={handleChange}
                placeholder="Confirm your password"
                required
              />
            </FormGroup>
          )}

          <Button type="submit" disabled={loading}>
            {loading ? 'Please wait...' : isRegister ? 'Create Account' : 'Sign In'}
          </Button>
        </Form>

        <BackLink onClick={() => navigate('/')}>
          <i className="bi bi-arrow-left" style={{ marginRight: '8px' }} />
          Back to Home
        </BackLink>
      </FormCard>
    </PageContainer>
  );
};

export default LoginPage;
