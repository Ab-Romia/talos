# Backend Architecture

## Overview

The backend implements a FastAPI-based REST API with modular components for authentication, workspace management, and AI integration.

## Technology Stack

- **Framework**: FastAPI (Python ASGI)
- **ORM**: SQLAlchemy
- **Database**: PostgreSQL (primary), SQLite (local/testing)
- **Authentication**: JWT tokens with bcrypt password hashing
- **Real-time**: WebSockets for chat functionality

## Core Components

### 1. Application Layer (`modules/app/`)

- FastAPI application with lifespan management
- Router-based API organization
- Dependency injection for database sessions and authentication

### 2. Authentication (`modules/app/auth.py`)

- User registration and login endpoints
- JWT token generation and validation
- Password hashing with bcrypt
- Sudo mode for sensitive operations
- OAuth2 password flow support

### 3. Data Models (`modules/model/`)

#### Identity Models (`identity.py`)
- User: Core user entity with username, email, roles
- UserPassword: Hashed password storage
- OTP: One-time password for verification
- IdentityProvider: External auth provider links
- Session: Active session tracking
- PlatformRole / Permission: RBAC implementation

#### Messaging Models (`messaging.py`)
- Workspace: Container for chatrooms and members
- Chatroom: Communication channel within workspace
- Message: Individual message entity

#### Base (`base.py`)
- SQLAlchemy declarative base
- Database engine and session configuration
- JSONB type annotation mapping

### 4. RAG System (`modules/rag/`)

- **ModularRAG**: Main orchestrator
- **HybridRetriever**: BM25 + dense retrieval with RRF
- **CrossEncoderReranker**: Document reranking
- **QueryProcessor**: Pre-retrieval transformations
- **QueryRouter**: Query classification and routing
- **LLMGenerator**: Response generation
- **ConversationMemory**: Session history management

### 5. Configuration (`modules/config/`)

- YAML-based configuration loading
- RAG component settings
- Environment variable support

## API Structure

```
/api/auth/
  POST /signup          - Create user account
  POST /token           - Get access token
  POST /refresh         - Refresh token
  POST /sudo_token      - Get elevated token
  PUT  /change_password - Change password
  POST /logout          - End session
```

## Database Schema

### Core Tables
- `users` - User accounts
- `user_passwords` - Password hashes
- `sessions` - Active sessions
- `otp` - Verification codes
- `identity_providers` - OAuth links

### RBAC Tables
- `platform_roles` - Role definitions
- `permissions` - Permission definitions
- `users_platform_roles` - User-role mapping
- `platform_role_permissions` - Role-permission mapping

### Workspace Tables
- `workspaces` - Workspace entities
- `chatrooms` - Communication channels
- `messages` - Chat messages

## Key Design Decisions

- **Modular Architecture**: Components are loosely coupled for flexibility
- **Soft Deletion**: Uses `deleted_at` timestamps instead of hard deletes
- **Case-Insensitive Matching**: CITEXT for usernames and emails
- **JSONB for Metadata**: Flexible user data storage
- **Cascade Deletion**: Maintains referential integrity
