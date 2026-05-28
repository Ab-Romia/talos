"""
Socket.IO connection lifecycle and presence tests.
"""
import asyncio
from contextlib import AsyncExitStack
from uuid import UUID

import pytest
import pytest_asyncio
import socketio

from backend.auth.permissions.model import Role, RolePermission
from backend.chat.model import MessageSchema
from backend.chat.realtime import is_user_online, get_channel_online as channel_online_users


@pytest.fixture(scope="session")
def live_server():
    import threading
    import time
    import uvicorn
    from app import app

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="error")
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


@pytest_asyncio.fixture
async def sio_client(live_server):
    async with AsyncExitStack() as stack:
        async def _factory(namespace="/", **connect_kwargs) -> socketio.AsyncClient:
            client = socketio.AsyncClient()
            await client.connect(live_server, namespaces=[namespace], **connect_kwargs)
            stack.push_async_callback(client.disconnect)
            return client

        yield _factory


async def wait_for(client: socketio.AsyncClient, event: str, timeout: float = 5.0):
    queue: asyncio.Queue = asyncio.Queue()
    client.on(event, lambda data: asyncio.ensure_future(queue.put(data)))
    return await asyncio.wait_for(queue.get(), timeout=timeout)


class TestConnectionManager:
    """Socket.IO connection lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, sio_client, auth_tokens, test_user):
        client = await sio_client(auth=auth_tokens(test_user))
        assert client.connected
        assert is_user_online(test_user.id)

        for _ in range(20):
            if not is_user_online(test_user.id):
                break
            await asyncio.sleep(0.05)

        await client.disconnect()
        assert not is_user_online(test_user.id)

    @pytest.mark.asyncio
    async def test_multiple_connections_same_user_keep_user_online(self, sio_client, auth_tokens, test_user):
        first = await sio_client(auth=auth_tokens(test_user))
        second = await sio_client(auth=auth_tokens(test_user))

        assert is_user_online(test_user.id)

        await first.disconnect()
        assert is_user_online(test_user.id)

        await second.disconnect()

        for _ in range(20):
            if not is_user_online(test_user.id):
                break
            await asyncio.sleep(0.05)

        assert not is_user_online(test_user.id)

    @pytest.mark.asyncio
    async def test_multiple_users_connected(self, sio_client, auth_tokens, test_users):
        users = [next(test_users) for _ in range(3)]

        clients = []
        for user in users:
            client = await sio_client(auth=auth_tokens(user))
            clients.append(client)
            assert client.connected

        online = [user.id for user in users if is_user_online(user.id)]
        assert len(online) == 3


class TestPresenceTracking:
    """Online presence detection."""

    def test_get_online_users_empty(self, test_channel, db_session):
        assert channel_online_users(test_channel.id, db_session) == []

    @pytest.mark.asyncio
    async def test_get_online_users_partial(self, sio_client, auth_tokens, test_users, test_channel,
                                            test_workspace, db_session, get_perm):
        users = [next(test_users) for _ in range(3)]
        _grant_channel_access(db_session, test_workspace, test_channel, users, get_perm)

        clients = []
        for user in users[:2]:
            client = await sio_client(auth=auth_tokens(user))
            clients.append(client)
            assert client.connected

    @pytest.mark.asyncio
    async def test_get_online_users_after_disconnect(self, sio_client, auth_tokens, test_users,
                                                     test_channel, test_workspace, db_session, get_perm):
        user_a, user_b = next(test_users), next(test_users)
        _grant_channel_access(db_session, test_workspace, test_channel, [user_a, user_b], get_perm)

        client_a = await sio_client(auth=auth_tokens(user_a))
        _client_b = await sio_client(auth=auth_tokens(user_b))

        assert set(channel_online_users(test_channel.id, db_session)) == {user_a.id, user_b.id}

        await client_a.disconnect()

        for _ in range(20):
            online = channel_online_users(test_channel.id, db_session)
            if online == [user_b.id]:
                break
            await asyncio.sleep(0.05)

        assert channel_online_users(test_channel.id, db_session) == [user_b.id]

    @pytest.mark.asyncio
    async def test_presence_event_on_second_user_connects(self, sio_client, auth_tokens, test_users,
                                                          test_channel, test_workspace, db_session, get_perm):
        user_a, user_b = next(test_users), next(test_users)
        _grant_channel_access(db_session, test_workspace, test_channel, [user_a, user_b], get_perm)

        client_a = await sio_client(auth=auth_tokens(user_a))

        wait_task = asyncio.create_task(wait_for(client_a, "user_presence"))
        _client_b = await sio_client(auth=auth_tokens(user_b))

        presence = await wait_task
        assert presence["status"] == "user_online"
        assert UUID(presence["user_id"]) == user_b.id

    @pytest.mark.asyncio
    async def test_presence_event_on_last_disconnect(self, sio_client, auth_tokens, test_users,
                                                     test_channel, test_workspace, db_session, get_perm):
        user_a, user_b = next(test_users), next(test_users)
        _grant_channel_access(db_session, test_workspace, test_channel, [user_a, user_b], get_perm)

        client_a = await sio_client(auth=auth_tokens(user_a))
        client_b = await sio_client(auth=auth_tokens(user_b))

        wait_task = asyncio.create_task(wait_for(client_a, "user_presence"))
        await client_b.disconnect()
        presence = await wait_task
        assert presence["status"] == "user_offline"
        assert UUID(presence["user_id"]) == user_b.id

    @pytest.mark.asyncio
    async def test_message_broadcast_to_connected_recipient(self, sio_client, auth_tokens, test_users, test_channel,
                                                            test_workspace, db_session, get_perm):
        user_sender, user_recipient = next(test_users), next(test_users)
        _grant_channel_access(db_session, test_workspace, test_channel, [user_sender, user_recipient], get_perm)

        sender = await sio_client(auth=auth_tokens(user_sender))
        recipient = await sio_client(auth=auth_tokens(user_recipient))

        wait_task = asyncio.create_task(wait_for(recipient, "message"))
        await asyncio.sleep(0)

        payload = MessageSchema(
            channel_id=test_channel.id,
            sender_id=user_sender.id,
            content="Hello recipient!",
        ).model_dump(mode="json")
        payload["workspace_id"] = str(test_workspace.id)

        await sender.call("message", payload)
        message = await wait_task

        assert message["content"] == "Hello recipient!"
        assert UUID(message["sender_id"]) == user_sender.id
        assert UUID(message["channel_id"]) == test_channel.id


def _grant_channel_access(db_session, workspace, channel, users, get_perm):
    workspace.members.extend(users)

    role = Role(name=f"presence_role_{channel.id.hex[:8]}", workspace_id=workspace.id, priority=1)
    for resource, action in (("channel", "view"), ("message", "send")):
        perm = get_perm(resource, action)
        role.permissions.append(RolePermission(permission_id=perm.id))

    db_session.add_all([workspace, role])
    db_session.flush()

    role.users.extend(users)
    db_session.commit()
