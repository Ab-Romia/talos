import pytest

from backend.chat.storage import bind_chat_storage, DatabaseStorageBackend, get_storage


@pytest.fixture(autouse=True)
def msg_cache():
    """Provide a fresh cache instance for isolated cache tests."""
    bind_chat_storage(DatabaseStorageBackend())
    return get_storage()
