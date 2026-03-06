class FileError(Exception):
    """Base exception for file operations."""


class FileTooLarge(FileError):
    def __init__(self, size: int, max_size: int):
        self.size = size
        self.max_size = max_size
        super().__init__(f"File size {size} exceeds maximum {max_size} bytes")


class UnsupportedFileType(FileError):
    def __init__(self, mime_type: str):
        self.mime_type = mime_type
        super().__init__(f"Unsupported file type: {mime_type}")


class FileNotFoundError(FileError):
    def __init__(self, file_id: str):
        self.file_id = file_id
        super().__init__(f"File not found: {file_id}")


class StorageError(FileError):
    def __init__(self, operation: str, detail: str):
        self.operation = operation
        self.detail = detail
        super().__init__(f"Storage error during {operation}: {detail}")
