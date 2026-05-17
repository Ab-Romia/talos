"""
Chat test fixtures and utilities.
"""
from typing import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from backend.auth.model import User
from backend.chat.cache import HotColdCache, cache as default_cache
from backend.chat.manager import ChannelConnectionManager, manager as default_manager
from backend.chat.models import WSMessage, MessageRole
from model.messaging import Workspace, Channel


# TODO: use existing fixtures for test_workspace that actually exists in DB
@pytest.fixture
def test_workspace(db_session, test_users):
    """Create a test workspace in the database."""
    workspace = Workspace(
        name="Test Workspace",
        owner_id=test_users[0].id,
    )
    workspace.members.extend(test_users)
    db_session.add(workspace)
    db_session.commit()
    db_session.refresh(workspace)
    return workspace


# TODO: use existing fixtures for test_channel that actually exists in DB
@pytest.fixture
def test_channel(db_session, test_workspace, test_users):
    """Create a test chat channel in the database."""

    channel = Channel(
        workspace_id=test_workspace.id,
        name="Test Channel",
    )
    # TODO: Join all test users to the channel via roles
    db_session.add(channel)
    db_session.commit()
    db_session.refresh(channel)
    return channel


@pytest.fixture
def test_channel_ids() -> list[UUID]:
    """Generate multiple distinct test channel IDs."""
    return [uuid4() for _ in range(3)]


@pytest.fixture
def test_users(db_session: Session) -> Generator[list[User]]:
    """Create 3 test users for multi-user chat scenarios."""
    from faker import Faker
    from sqlalchemy import delete

    faker = Faker()
    users = []

    for i in range(3):
        user = User(
            username="test-" + faker.user_name(),
            primary_email=faker.email(),
            name=faker.name(),
            signup_complete=True,
            data={},
            roles=[],
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        users.append(user)

    yield users

    # Cleanup
    for user in users:
        db_session.execute(delete(User).where(User.id == user.id))
    db_session.commit()


@pytest.fixture
def fresh_cache():
    """Provide a fresh cache instance for isolated cache tests."""
    return HotColdCache()


@pytest.fixture
def fresh_manager():
    """Provide a fresh connection manager for isolated WebSocket tests."""
    return ChannelConnectionManager()


@pytest.fixture(autouse=True)
def clear_default_cache():
    """Clear the default cache before each test to prevent cross-test contamination."""
    default_cache._hot.clear()
    default_cache._cold.clear()
    yield
    default_cache._hot.clear()
    default_cache._cold.clear()


@pytest.fixture(autouse=True)
def clear_default_manager():
    """Clear the default manager before each test to prevent connection leaks."""
    default_manager._connections.clear()
    yield
    default_manager._connections.clear()


def create_test_message(
        channel_id: UUID,
        sender_id: UUID,
        text: str = "Test message",
        role: MessageRole = MessageRole.USER,
) -> WSMessage:
    """Helper to create a test message."""
    return WSMessage(
        channel_id=channel_id,
        sender_id=sender_id,
        text=text,
        role=role,
    )


@pytest.fixture
def message_factory():
    """Factory to create test messages with default values."""
    return create_test_message
