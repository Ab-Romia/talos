import pytest


@pytest.fixture(autouse=True)
def db_session():
    """Override root conftest's autouse db_session for unit tests (no DB needed)."""
    yield None
