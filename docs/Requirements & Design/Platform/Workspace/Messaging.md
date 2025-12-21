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

# TODO

