# python
import pytest
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# module under test
import notifications.app.websocket as websocket_mod


def test_websocket_endpoint_calls_manager_connect_and_disconnect(monkeypatch):
    app = FastAPI()
    app.include_router(websocket_mod.router)

    # fake connect that accepts the websocket so the test client's handshake completes
    async def _fake_connect(user_id, websocket):
        await websocket.accept()

    connect_mock = AsyncMock(side_effect=_fake_connect)
    disconnect_mock = Mock()

    # Patch the manager used by the websocket endpoint
    monkeypatch.setattr("notifications.app.websocket.manager.connect", connect_mock)
    monkeypatch.setattr("notifications.app.websocket.manager.disconnect", disconnect_mock)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/test-user") as ws:
            # send a message so the server's receive_text() loop advances once
            ws.send_text("ping")
            # leaving the context manager will close the websocket and trigger disconnect on server

    # Assertions: connect awaited once with expected user id; disconnect called once
    connect_mock.assert_awaited_once()
    called_user_id = connect_mock.call_args[0][0]
    assert called_user_id == "test-user"
    assert disconnect_mock.called
    assert disconnect_mock.call_args[0][0] == "test-user"
