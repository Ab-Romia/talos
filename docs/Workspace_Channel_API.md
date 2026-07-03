# Workspace & Channel Management API Documentation

This document outlines all the new workspace and channel management endpoints that have been implemented.

## Overview

The workspace and channel management system provides comprehensive endpoints for:
- **Workspace Settings**: Edit name, description, icon
- **Workspace Members**: Add/remove members, manage roles, list members
- **Workspace Operations**: Leave workspace, delete workspace (owner only)
- **Channel Management**: Create/delete channels, list channels
- **Channel Settings**: Rename, edit description, toggle visibility
- **Channel Features**: Mute/unmute, archive/unarchive channels

All endpoints require proper authentication and permission checks.

---

## Workspace Settings Endpoints

### Base Path: `/workspaces/{workspace_id}/settings`

#### 1. Get Workspace Settings
```
GET /workspaces/{workspace_id}/settings
```
**Permissions Required**: `workspace:view`

**Description**: Retrieve workspace settings including name, description, and icon.

**Response**:
```json
{
  "id": "uuid",
  "name": "My Workspace",
  "description": "Workspace description",
  "icon_id": "uuid or null",
  "owner_id": "uuid",
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

#### 2. Edit Workspace Name
```
PUT /workspaces/{workspace_id}/settings/name
```
**Permissions Required**: `workspace:edit`

**Form Parameters**:
- `name` (string, required): New workspace name

**Response**: Updated workspace settings

---

#### 3. Edit Workspace Description
```
PUT /workspaces/{workspace_id}/settings/description
```
**Permissions Required**: `workspace:edit`

**Form Parameters**:
- `description` (string, optional): New description

**Response**: Updated workspace settings

---

#### 4. Edit Workspace Icon
```
PUT /workspaces/{workspace_id}/settings/icon
```
**Permissions Required**: `workspace:edit`

**Form Parameters**:
- `icon_id` (uuid, optional): File ID of the icon image

**Response**: Updated workspace settings

---

#### 5. Get Workspace Members
```
GET /workspaces/{workspace_id}/settings/members
```
**Permissions Required**: `workspace.member:view`

**Description**: List all members in the workspace.

**Response**:
```json
[
  {
    "id": "uuid",
    "username": "john_doe",
    "email": "john@example.com"
  },
  ...
]
```

---

#### 6. Add Workspace Member
```
POST /workspaces/{workspace_id}/settings/members/{user_id}
```
**Permissions Required**: `workspace.member:manage`

**Description**: Add a user to the workspace.

**Response**: The added member details

---

#### 7. Remove Workspace Member
```
DELETE /workspaces/{workspace_id}/settings/members/{user_id}
```
**Permissions Required**: `workspace.member:manage`

**Description**: Remove a user from the workspace.

**Status Code**: 204 No Content

---

#### 8. Leave Workspace
```
POST /workspaces/{workspace_id}/settings/leave
```
**Description**: Leave the workspace as a member.

**Notes**: 
- Workspace owner cannot leave
- Removes current user from workspace members

**Status Code**: 204 No Content

---

#### 9. Delete Workspace
```
DELETE /workspaces/{workspace_id}/settings
```
**Permissions Required**: `workspace:delete`

**Description**: Permanently delete the workspace.

**Notes**: 
- Only workspace owner can delete
- Deletes all channels and messages in the workspace
- Irreversible operation

**Status Code**: 204 No Content

---

## Workspace Channels Endpoints

### Base Path: `/workspaces/{workspace_id}/channels`

#### 1. List Workspace Channels
```
GET /workspaces/{workspace_id}/channels
```
**Permissions Required**: `channel:view`

**Query Parameters**:
- `skip` (integer, default: 0): Number of channels to skip
- `limit` (integer, default: 50, max: 100): Maximum channels to return

**Response**:
```json
[
  {
    "id": "uuid",
    "name": "general",
    "description": "General discussion",
    "is_public": true,
    "is_muted": false,
    "is_archived": false,
    "created_at": "2024-01-15T10:30:00Z"
  },
  ...
]
```

---

#### 2. Create Channel
```
POST /workspaces/{workspace_id}/channels
```
**Permissions Required**: `channel:create`

**Form Parameters**:
- `name` (string, required): Channel name
- `description` (string, optional): Channel description
- `is_public` (boolean, default: true): Public or private channel

**Response**:
```json
{
  "id": "uuid",
  "name": "new-channel",
  "description": "Channel description",
  "workspace_id": "uuid",
  "is_public": true,
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Status Code**: 201 Created

---

#### 3. Delete Channel
```
DELETE /workspaces/{workspace_id}/channels/{channel_id}
```
**Permissions Required**: `channel:delete`

**Description**: Permanently delete a channel.

**Notes**: 
- Deletes all messages in the channel
- Irreversible operation

**Status Code**: 204 No Content

---

## Channel Settings Endpoints

### Base Path: `/channels/{channel_id}/settings`

#### 1. Get Channel Settings
```
GET /channels/{channel_id}/settings
```
**Permissions Required**: `channel:view`

**Response**:
```json
{
  "id": "uuid",
  "name": "general",
  "description": "General discussion",
  "workspace_id": "uuid",
  "is_public": true,
  "is_muted": false,
  "is_archived": false,
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

#### 2. Rename Channel
```
PUT /channels/{channel_id}/settings/name
```
**Permissions Required**: `channel:edit`

**Form Parameters**:
- `name` (string, required): New channel name

**Response**: Updated channel settings

---

#### 3. Edit Channel Description
```
PUT /channels/{channel_id}/settings/description
```
**Permissions Required**: `channel:edit`

**Form Parameters**:
- `description` (string, optional): New description

**Response**: Updated channel settings

---

#### 4. Toggle Channel Visibility
```
PUT /channels/{channel_id}/settings/visibility
```
**Permissions Required**: `channel:edit`

**Form Parameters**:
- `is_public` (boolean, required): True for public, false for private

**Response**: Updated channel settings

---

#### 5. Mute Channel
```
POST /channels/{channel_id}/settings/mute
```
**Permissions Required**: `channel:manage`

**Description**: Mute notifications for this channel.

**Response**: Updated channel settings

---

#### 6. Unmute Channel
```
POST /channels/{channel_id}/settings/unmute
```
**Permissions Required**: `channel:manage`

**Description**: Unmute notifications for this channel.

**Response**: Updated channel settings

---

#### 7. Archive Channel
```
POST /channels/{channel_id}/settings/archive
```
**Permissions Required**: `channel:manage`

**Description**: Archive the channel (hide from view but keep data).

**Response**: Updated channel settings

---

#### 8. Unarchive Channel
```
POST /channels/{channel_id}/settings/unarchive
```
**Permissions Required**: `channel:manage`

**Description**: Restore archived channel.

**Response**: Updated channel settings

---

#### 9. Delete Channel
```
DELETE /channels/{channel_id}/settings
```
**Permissions Required**: `channel:delete`

**Description**: Permanently delete the channel.

**Notes**: 
- Deletes all messages in the channel
- Irreversible operation

**Status Code**: 204 No Content

---

## Channel Members Endpoints

### Base Path: `/channels/{channel_id}/members`

#### 1. List Channel Members
```
GET /channels/{channel_id}/members
```
**Dependencies**: `channel:view`

**Description**: List all members who have access to this channel.

**Notes**: Currently returns all workspace members (per-channel membership tracking can be extended)

**Response**:
```json
[
  {
    "id": "uuid",
    "username": "john_doe",
    "email": "john@example.com"
  },
  ...
]
```

---

#### 2. Add Member to Channel
```
POST /channels/{channel_id}/members/{user_id}
```
**Permissions Required**: `channel.member:manage`

**Description**: Add a user to the channel.

**Notes**: User must already be a workspace member

**Response**: The added member details

**Status Code**: 201 Created

---

#### 3. Remove Member from Channel
```
DELETE /channels/{channel_id}/members/{user_id}
```
**Permissions Required**: `channel.member:manage`

**Description**: Remove a user from the channel.

**Notes**: Requires implementation of per-channel member tracking

**Status Code**: 204 No Content

---

## Role Management

### Workspace Roles - Base Path: `/workspaces/{workspace_id}/roles`

- **GET** `/roles` - List all roles
- **POST** `/roles` - Create new role
- **GET** `/roles/{role_id}` - Get role details
- **PUT** `/roles/{role_id}` - Update role metadata
- **PUT** `/roles/{role_id}/permissions` - Update role permissions
- **PUT** `/roles/{role_id}/members` - Update role members
- **DELETE** `/roles/{role_id}` - Delete role

### Channel Roles - Base Path: `/channels/{channel_id}/roles`

- **GET** `/roles` - Get channel role overrides
- **POST** `/roles/{role_id}` - Create channel role override
- **GET** `/roles/{role_id}` - Get channel role override
- **PUT** `/roles/{role_id}` - Update channel role override
- **DELETE** `/roles/{role_id}` - Delete channel role override

---

## Permission Requirements

The following permissions are used throughout the system:

**Workspace Permissions**:
- `workspace:view` - View workspace
- `workspace:edit` - Edit workspace settings
- `workspace:delete` - Delete workspace
- `workspace.member:view` - View workspace members
- `workspace.member:manage` - Add/remove members
- `workspace.role:view` - View workspace roles
- `workspace.role:manage` - Manage workspace roles

**Channel Permissions**:
- `channel:view` - View channel
- `channel:edit` - Edit channel settings
- `channel:delete` - Delete channel
- `channel:create` - Create channels
- `channel:manage` - Manage channel settings (mute, archive, etc)
- `channel.member:view` - View channel members
- `channel.member:manage` - Manage channel members
- `channel.message:send` - Send messages
- `channel.message:view_history` - View message history

---

## Database Schema Changes

### Workspace Model
Added fields:
- `description: Optional[str]` - Workspace description
- `icon_id: Optional[uuid.UUID]` - Reference to File model for workspace icon

### Channel Model
Added fields:
- `description: Optional[str]` - Channel description
- `is_public: bool` - Public/private channel flag (default: True)
- `is_muted: bool` - Channel mute status (default: False)
- `is_archived: bool` - Channel archived status (default: False)

---

## Error Handling

All endpoints return appropriate HTTP status codes:

- **200 OK** - Successful GET/PUT/POST return
- **201 Created** - Resource created successfully
- **204 No Content** - Successful DELETE or operation with no response body
- **400 Bad Request** - Invalid input
- **404 Not Found** - Resource not found
- **403 Forbidden** - Insufficient permissions
- **500 Internal Server Error** - Server error

---

## Implementation Notes

1. **Permissions**: All operations are protected by permission checks using the workspace permission system
2. **Owner Checks**: Workspace/channel owners have special permissions
3. **Validation**: Input validation is performed on all Form parameters
4. **Database**: All operations use SQLAlchemy ORM with proper transaction handling
5. **Services**: Business logic is separated into service classes (WorkspaceService, ChannelService)
6. **Per-Channel Members**: Current implementation treats all workspace members as channel members. For per-channel member management, a new database relationship table would need to be created.

---

## Usage Examples

### Create a Channel
```bash
curl -X POST "http://localhost:8000/workspaces/{workspace_id}/channels" \
  -H "Authorization: Bearer {token}" \
  -F "name=announcements" \
  -F "description=Important announcements" \
  -F "is_public=true"
```

### Update Channel Name
```bash
curl -X PUT "http://localhost:8000/channels/{channel_id}/settings/name" \
  -H "Authorization: Bearer {token}" \
  -F "name=new-name"
```

### Archive a Channel
```bash
curl -X POST "http://localhost:8000/channels/{channel_id}/settings/archive" \
  -H "Authorization: Bearer {token}"
```

### Add Workspace Member
```bash
curl -X POST "http://localhost:8000/workspaces/{workspace_id}/settings/members/{user_id}" \
  -H "Authorization: Bearer {token}"
```

---

## Future Enhancements

1. **Per-Channel Member Management**: Implement a `channel_members` table for fine-grained access control
2. **Channel Categories**: Add support for organizing channels into categories
3. **Channel Notifications Settings**: Add per-user notification preferences for channels
4. **Activity Logging**: Track all workspace/channel modifications
5. **Audit Trail**: Maintain history of all administrative actions
6. **Channel Templates**: Allow creating channels from templates
7. **Bulk Operations**: Support bulk member additions/removals
8. **Workspace Invitations**: Generate and manage workspace invitations via link

