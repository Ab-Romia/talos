import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import socketio

from backend.chat.cache import HotColdCache
from backend.chat.models import WSMessage, MessageRole


@pytest.fixture
def test_channel_ids() -> list[UUID]:
    """Generate multiple distinct test channel IDs."""
    return [uuid4() for _ in range(3)]


@pytest.fixture
def fresh_cache():
    """Provide a fresh cache instance for isolated cache tests."""
    return HotColdCache()


@pytest.fixture(scope="session")
def live_server():
    import threading
    import time
    import uvicorn
    from app import app

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=8765, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 15
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("Socket.IO test server stopped during startup")
        if time.monotonic() >= deadline:
            raise TimeoutError("Socket.IO test server did not start")
        time.sleep(0.05)

    yield "http://127.0.0.1:8765"
    server.should_exit = True


@pytest.fixture
def override_get_db(db_session, monkeypatch):
    """Override get_db for Socket.IO handlers."""
    from backend.chat import realtime

    def get_db_override():
        yield db_session

    monkeypatch.setattr(realtime, "get_db", get_db_override)


@pytest_asyncio.fixture
async def sio_client(live_server, override_get_db):
    clients: list["_ClientContext"] = []

    class _ClientContext:
        def __init__(self, namespace: str, connect_kwargs: dict):
            self._namespace = namespace
            self._connect_kwargs = connect_kwargs
            self._client = socketio.AsyncClient()
            self._connected = False
            self._queues: dict[str, asyncio.Queue] = {}

        async def _ensure_connected(self):
            if not self._connected:
                await self._client.connect(live_server, namespaces=[self._namespace], **self._connect_kwargs)
                self._connected = True
                clients.append(self)
            return self

        def _ensure_handler(self, event: str) -> asyncio.Queue:
            if event not in self._queues:
                queue: asyncio.Queue = asyncio.Queue()

                async def _handler(data):
                    await queue.put(data)

                self._client.on(event, _handler)
                self._queues[event] = queue
            return self._queues[event]

        @property
        def connected(self) -> bool:
            return self._client.connected

        async def disconnect(self) -> None:
            if self._client.connected:
                await self._client.disconnect()

        async def wait_for(self, event: str, timeout: float = 5.0):
            queue = self._ensure_handler(event)
            return await asyncio.wait_for(queue.get(), timeout=timeout)

        async def emit(self, event: str, data=None):
            await self._ensure_connected()
            await self._client.emit(event, data)

        async def call(self, event: str, data=None, timeout: float = 5.0):
            await self._ensure_connected()
            return await self._client.call(event, data, timeout=timeout)

        def __await__(self):
            return self._ensure_connected().__await__()

        async def __aenter__(self):
            return await self._ensure_connected()

        async def __aexit__(self, exc_type, exc, tb):
            await self.disconnect()

    def _factory(namespace="/", **connect_kwargs) -> _ClientContext:
        return _ClientContext(namespace, connect_kwargs)

    yield _factory

    for client in clients:
        if client.connected:
            await client.disconnect()


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
