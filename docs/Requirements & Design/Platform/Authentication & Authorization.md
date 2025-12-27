# Authentication & Authorization

This document outlines the authentication and authorization requirements for the platform.

## Functional Requirements

### User Registration

- Users shall be able to create an account with username, email, password, and name.
- Usernames shall be unique (case-insensitive).
- Email addresses shall be unique (case-insensitive).
- Passwords shall be securely hashed using bcrypt before storage.
- The system shall support email verification for new accounts. [TODO]

### Authentication Methods

- The system shall support password-based authentication.
- The system shall support OTP (One-Time Password) authentication. [TODO]
- The system shall support OAuth providers (e.g., Google). [TODO]
- Users may have multiple identity providers linked to their account.

### Session Management

- Upon successful authentication, the system shall issue a JWT access token.
- Access tokens shall contain user ID and username.
- Access tokens shall have a configurable expiration time (default: 20 minutes).
- The system shall support token refresh for active sessions.
- Sessions shall be tracked with creation and expiration timestamps.
- The system shall support session invalidation (logout). [TODO]

### Password Management

- Users shall be able to change their password.
- Password changes shall require current password verification.
- Password changes shall require elevated (sudo) token verification.
- The system shall support password reset functionality. [TODO]

### Sudo Mode

- Sensitive operations shall require sudo token authentication.
- Sudo tokens shall have a shorter expiration (5 minutes).
- Sudo tokens shall require re-authentication with current password.

## Authorization

### Role-Based Access Control

- The system shall support platform-level roles.
- Roles shall be assigned sets of permissions.
- Users may have multiple roles.
- Permissions shall be granular and composable.

### Permission Model

- Platform roles define what users can do across the system. [TODO]
- Workspace-level permissions control access to workspace resources. [TODO]
- Users shall only access resources they are authorized to view. [TODO]

## Non-Functional Requirements

### Security

- Passwords shall never be stored in plaintext.
- JWT tokens shall be signed with a secret key using HS256 algorithm.
- Failed authentication attempts shall not reveal whether username or password is incorrect.
- Deleted or unverified users shall not be able to authenticate.

### Performance

- Authentication shall be fast and not block user experience.
- Token validation shall be efficient for every protected request.

### Auditability

- User creation timestamps shall be tracked.
- Session creation and expiration shall be logged.

## Data Model

### User
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Unique identifier |
| username | CITEXT | Case-insensitive username |
| primary_email | CITEXT | Case-insensitive email |
| email_verified | Boolean | Email verification status |
| name | String | Display name |
| created_at | DateTime | Account creation timestamp |
| deleted_at | DateTime (nullable) | Soft deletion timestamp |
| data | JSONB | Additional user data |

### Session
| Field | Type | Description |
|-------|------|-------------|
| token | UUID | Session token |
| user_id | UUID (FK) | Reference to user |
| created_at | DateTime | Session start |
| expires_at | DateTime | Planned expiration |
| expired_at | DateTime (nullable) | Actual expiration |

### Platform Role
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Unique identifier |
| name | String | Role name |
| description | String | Role description |

### Permission
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Unique identifier |
| name | String | Permission name |
| description | String | Permission description |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| /api/auth/signup | POST | Create new user account |
| /api/auth/token | POST | Authenticate and get access token |
| /api/auth/refresh | POST | Refresh access token |
| /api/auth/sudo_token | POST | Get elevated sudo token |
| /api/auth/change_password | PUT | Change user password |
| /api/auth/logout | POST | Invalidate session |
