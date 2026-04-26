DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_FILES_ENDPOINT = f"{DRIVE_API_BASE}/files"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

GOOGLE_DOC_EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "text/csv",
        ".csv",
    ),
    "application/vnd.google-apps.presentation": (
        "application/pdf",
        ".pdf",
    ),
}

DEFAULT_LIST_PAGE_SIZE = 25
MAX_LIST_PAGE_SIZE = 100
