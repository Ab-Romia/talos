# Chat Search Implementation (Updated Branch)

## Overview
A comprehensive chat message search system has been implemented supporting advanced filtering, pagination, and text search capabilities for channels.

## Features Implemented

### 1. **Search Filters**
- **text**: Full-text case-insensitive search in message content
- **author_id**: Filter messages by sender/author ID
- **start_date**: Filter messages from this date onwards (sent_at >= start_date)
- **end_date**: Filter messages up to this date (sent_at <= end_date)

### 2. **Pagination**
- **page**: Page number (1-indexed, minimum 1)
- **page_size**: Items per page (1-100, default 20)
- Response includes pagination metadata (total_pages, has_next, has_previous)

### 3. **Response Format**
```json
{
  "messages": [
    {
      "id": "uuid",
      "channel_id": "uuid",
      "sender_id": "uuid or null",
      "role": "user, assistant, or system",
      "content": "message text",
      "sent_at": "ISO 8601 datetime"
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "total_pages": 5,
  "has_next": true,
  "has_previous": false
}
```

## API Endpoint

### Search Messages
**Endpoint:** `GET /channels/{channel_id}/messages/search`

**Query Parameters:**
- `text` (optional): Search text
- `author_id` (optional): Author/sender UUID
- `start_date` (optional): ISO 8601 datetime
- `end_date` (optional): ISO 8601 datetime
- `page` (optional): Page number, default 1
- `page_size` (optional): Items per page, default 20

**Permissions Required:**
- `channel:view`
- `channel.message:view_history`

**Example Request:**
```
GET /channels/550e8400-e29b-41d4-a716-446655440000/messages/search?
  text=hello&
  author_id=123e4567-e89b-12d3-a456-426614174000&
  start_date=2024-01-01T00:00:00&
  end_date=2024-12-31T23:59:59&
  page=1&
  page_size=20
```

## File Structure

### New Files Created:
1. **`src/chat/search.py`** - Chat search service
   - `search_messages()` async function for querying and filtering

### Modified Files:
1. **`src/chat/router.py`**
   - Added `ChatMessageResponse` schema
   - Added `ChatSearchResponse` schema
   - Added `/messages/search` endpoint
   - Imported `search_messages` function

## Implementation Details

### Search Service (`search_messages()`)
- Async function for efficient database queries
- Handles construction of SQLAlchemy queries with dynamic filters
- Case-insensitive text search using SQL ILIKE operator
- Efficient pagination with offset/limit
- Returns tuple of (messages, total_count)

### Database Query Optimization
- Single query for fetching paginated results
- Separate count query for accurate pagination
- Filters apply only to relevant fields
- Results ordered by sent_at descending (newest first)

### Authorization
- Uses existing `require_perms` decorator to verify permissions
- Users can only search messages in channels they have access to

## Usage Examples

### Search messages by text
```
GET /channels/{id}/messages/search?text=report
```

### Search messages from specific author
```
GET /channels/{id}/messages/search?author_id=550e8400-e29b-41d4-a716-446655440000
```

### Search by date range
```
GET /channels/{id}/messages/search?start_date=2024-06-01T00:00:00&end_date=2024-06-30T23:59:59
```

### Combined filters with pagination
```
GET /channels/{id}/messages/search?
  text=meeting&
  author_id=550e8400-e29b-41d4-a716-446655440000&
  start_date=2024-06-01T00:00:00&
  page=2&
  page_size=50
```

## Query Performance
- Text search uses SQL ILIKE (index-friendly on supported databases)
- Pagination is efficient (no N+1 queries)
- Results are ordered consistently (by sent_at DESC)
- Async operations prevent blocking

## Differences from Previous Branch

1. **Async/Await Pattern**: Uses async functions consistent with the codebase
2. **Channel-based**: Uses channels instead of workspace/chatroom
3. **Message Role**: Includes role field (user, assistant, system)
4. **Sent Timestamp**: Uses `sent_at` instead of `created_at`
5. **Storage Backend**: Queries database directly instead of through storage layer

## Future Enhancements
- Full-text search with stemming (if using PostgreSQL)
- Relevance scoring/ranking
- Saved searches/filters
- Search analytics
- Advanced query syntax (AND, OR, NOT)
- Real-time search results via WebSocket

