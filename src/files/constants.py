MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_MIME_TYPES = {
    # Documents
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    # Images
    "image/png",
    "image/jpeg",
    "image/webp",
}

DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
}

IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
}

THUMBNAIL_SIZE = (300, 300)

STORAGE_KEY_TEMPLATE = "workspaces/{workspace_id}/chatrooms/{chatroom_id}/{file_id}{ext}"
