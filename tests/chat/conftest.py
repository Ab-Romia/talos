"""
Chat test fixtures and utilities.
"""
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import app
from backend.chat.cache import HotColdCache, cache as default_cache
from backend.chat.manager import ChannelConnectionManager, manager as default_manager
from backend.chat.models import WSMessage, MessageRole
from model.identity import User


@pytest.fixture
def test_channel_id() -> UUID:
    """Generate a consistent test channel ID."""
    return uuid4()


@pytest.fixture
def test_channel_ids() -> List[UUID]:
    """Generate multiple distinct test channel IDs."""
    return [uuid4() for _ in range(3)]


@pytest.fixture
def test_users(db_session: Session) -> List[User]:
    """Create 3 test users for multi-user chat scenarios."""
    from faker import Faker
    import sqlalchemy.exc
    from sqlalchemy import select, delete
    
    faker = Faker()
    users = []
    
    for i in range(3):
        user_name = f"chat_test_user_{i}_{faker.user_name()}"
        try:
            user = User(
                username=user_name,
                primary_email=faker.email(),
                email_verified=True,
                name=faker.name(),
                data={},
                roles=[],
            )
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            users.append(user)
        except sqlalchemy.exc.IntegrityError:
            user = db_session.scalar(
                select(User)
                .where(User.username == user_name)
            )
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
