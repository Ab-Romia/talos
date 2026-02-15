# Chatroom

Chatrooms are communication channels within a workspace where members can exchange messages in real-time.

## Functional Requirements

### Chatroom Management

- Users with appropriate permissions shall be able to create chatrooms within a workspace. [TODO]
- Each chatroom shall have a unique name within its workspace.
- Chatrooms shall belong to exactly one workspace.
- Workspace owners shall be able to delete chatrooms. [TODO]
- The system shall track chatroom creation timestamps.
- Soft deletion shall be supported via a deleted_at timestamp.

### Membership & Access

- Workspace members shall have access to chatrooms based on their permissions. [TODO]
- The system shall control read access to chatrooms per user. [TODO]
- Users shall only see messages in chatrooms they have access to. [TODO]

### Messaging

- Authorized users shall be able to send messages to a chatroom.
- Messages shall be visible to all users with read access to that chatroom.
- Each message shall be associated with a sender and a chatroom.
- Messages shall be stored with creation timestamps.
- The system shall handle cases where the sender is deleted (SET NULL).

### Real-Time Communication

- Messages shall be delivered to chatroom members in real-time via WebSockets. [TODO]
- Users shall receive notifications for new messages in their chatrooms. [TODO]
- The system shall support multiple concurrent users in a chatroom. [TODO]

## Non-Functional Requirements

### Performance

- Message delivery shall be near-instantaneous for real-time communication.
- The system shall efficiently handle chatrooms with many messages.

### Scalability

- The system shall support multiple chatrooms per workspace.
- The system shall handle concurrent message sending from multiple users.

### Data Integrity

- Messages shall maintain referential integrity with chatrooms and workspaces.
- Cascade deletion shall be applied when a workspace or chatroom is deleted.

## Data Model

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Unique identifier for the chatroom |
| name | String | Display name of the chatroom |
| workspace_id | UUID (FK) | Reference to parent workspace |
| created_at | DateTime | Timestamp of creation |
| deleted_at | DateTime (nullable) | Soft deletion timestamp |
