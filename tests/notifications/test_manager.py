# python
import pytest
from unittest.mock import AsyncMock, Mock

import notifications.websocket.manager as manager_module
from notifications.websocket.manager import manager

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def clear_connections():
    # ensure clean state between tests
    manager.active_connections = {}
    yield
    manager.active_connections = {}


async def test_connect_accepts_and_registers_connection():
    ws = AsyncMock()
    await manager.connect("user1", ws)

    ws.accept.assert_awaited_once()
    assert "user1" in manager.active_connections
    assert manager.active_connections["user1"] == [ws]


def test_disconnect_removes_connection_and_cleans_user_entry():
    ws = Mock()
    manager.active_connections = {"user2": [ws]}

    manager.disconnect("user2", ws)

    assert "user2" not in manager.active_connections


async def test_multiple_connections_per_user_are_supported():
    ws1 = AsyncMock()
    ws2 = AsyncMock()

    await manager.connect("user3", ws1)
    await manager.connect("user3", ws2)

    assert "user3" in manager.active_connections
    assert manager.active_connections["user3"] == [ws1, ws2]


async def test_send_to_user_sends_json_to_all_user_connections():
    ws1 = AsyncMock()
    ws2 = AsyncMock()

    # register without calling accept (we only care about send_json)
    manager.active_connections = {"user4": [ws1, ws2]}

    message = {"msg": "hello"}
    await manager.send_to_user("user4", message)

    ws1.send_json.assert_awaited_once_with(message)
    ws2.send_json.assert_awaited_once_with(message)


async def test_send_to_user_noop_if_user_not_connected():
    # should not raise
    await manager.send_to_user("no_such_user", {"x": 1})
    # still empty
    assert manager.active_connections == {}
