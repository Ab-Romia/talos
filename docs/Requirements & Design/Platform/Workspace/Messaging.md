# Messaging System

## User Requirements

### Messaging Capabilities

An authorized user shall be able to:

* Send messages to a chatroom, visible to all users with read access to that chatroom.

* Send private messages to users in their contacts or to users with whom they share a mutual workspace.

- Mention one or more users in a message.
    - May require additional permissions.
    - Mentioned users shall have the message visually highlighted and receive a notification.

### Message Formatting

* Messages shall correctly render multiple languages.
* Bidirectional text (e.g., left-to-right and right-to-left languages) shall be fully supported.
* Messages shall support rich text formatting, including but not limited to:
    * Bold, italics, and underline
    * Hyperlinks
    * Inline code blocks
    * Tables and lists
    * Other visual elements to aid effective and efficient communication

### Message Interactions

Authorized users shall be able to:

* Edit their own messages.
    * An indicator is displayed on edited messages.
* Reply to messages, notifying the original author.
* React to messages with emojis.
* Create a "thread" or a "conversation" from successive replies

### Attachments

To facilitate file sharing and planing, users should be able to attach various multimedia documents, including but not
limited to:

- Image/Audio/Video Files (Common file formats shall be supported).
- Interactive forms or polls which other users can submit. The sender can choose to publish the results.
    - The form is dynamically created by the user.
    - Utilizing various controls e.g. textbox, combobox...
- Documents such as PDFs and spreadsheets.

* Other document types (e.g. Diagrams) can be support via extensions.

The above should be rendered in a built-in viewer, to limit requiring external programs.

## System Requirements

### Functional Requirements

#### Message Storage

- Each message shall be stored with a unique identifier (UUID).
- Messages shall reference their workspace and chatroom.
- Messages shall reference the sender (nullable for system messages or deleted users).
- Message content shall be stored as text supporting rich formatting.
- Message creation timestamps shall be recorded.

#### Message Delivery

- Messages shall be delivered in real-time to connected clients via WebSockets. [TODO]
- The system shall maintain message ordering based on creation timestamp.
- Messages shall be persisted before delivery confirmation. [TODO]

#### Message Retrieval

- The system shall support paginated retrieval of message history. [TODO]
- Messages shall be retrievable by chatroom. [TODO]
- The system shall support filtering messages by date range. [TODO]

#### Data Integrity

- Messages shall maintain referential integrity with chatrooms and workspaces.
- When a chatroom is deleted, associated messages shall be cascade deleted.
- When a sender is deleted, the sender reference shall be set to NULL.

### Non-Functional Requirements

#### Performance

- Message sending shall have minimal latency for real-time experience.
- Message history loading shall be optimized for large chatrooms.

#### Scalability

- The system shall handle high message volumes in active chatrooms.
- The database schema shall support efficient indexing on workspace and chatroom.

#### Reliability

- Messages shall not be lost during transmission. [TODO]
- The system shall handle reconnection and message synchronization. [TODO]

### Data Model

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Unique message identifier |
| workspace_id | UUID (FK) | Reference to parent workspace |
| chatroom_id | UUID (FK) | Reference to parent chatroom |
| sender_id | UUID (FK, nullable) | Reference to sender user |
| content | String | Message content |
| created_at | DateTime | Message timestamp |

