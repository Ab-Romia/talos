# Threads

Threads provide focused discussions branching from a parent message, keeping main chatroom conversations organized.

## Functional Requirements

### Thread Creation [TODO]

- Users shall be able to create a thread by replying to any message.
- A thread shall be associated with its parent message.
- The system shall recursively find all replies to a message and group them together.

### Thread Navigation [TODO]

- Users shall be able to view all replies in a thread.
- Threads shall be accessible from the parent message.
- The system shall indicate when a message has thread replies.

### Thread Messaging [TODO]

- Users shall be able to send messages within a thread.
- Thread messages shall support the same formatting as regular messages.
- Thread participants shall receive notifications for new replies.

### Thread Display [TODO]

- Threads shall be displayed separately from the main chatroom feed.
- Thread replies shall maintain chronological ordering.
- The parent message shall be visible at the top of the thread.

## Non-Functional Requirements

### Performance

- Thread loading shall be efficient for threads with many replies.
- The system shall efficiently query nested reply structures.

### Usability

- Threads shall provide clear visual distinction from main chat.
- Navigation between thread and main chat shall be intuitive.
