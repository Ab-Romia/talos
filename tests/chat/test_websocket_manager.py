"""
Socket.IO connection lifecycle and presence tests.
"""
import asyncio
from contextlib import AsyncExitStack
from uuid import UUID

import pytest

from backend.auth.permissions.model import Role, RolePermission
from backend.chat.models import WSMessage
from backend.chat.realtime import is_user_online, get_online_users as channel_online_users


class TestConnectionManager:
    """Socket.IO connection lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, sio_client, auth_tokens, test_user):
        async with sio_client(auth=auth_tokens(test_user)) as client:
            assert client.connected
            assert is_user_online(test_user.id)

        for _ in range(20):
            if not is_user_online(test_user.id):
                break
            await asyncio.sleep(0.05)

        assert not is_user_online(test_user.id)

    @pytest.mark.asyncio
    async def test_multiple_connections_same_user_keep_user_online(self, sio_client, auth_tokens, test_user):
        async with sio_client(auth=auth_tokens(test_user)) as first:
            async with sio_client(auth=auth_tokens(test_user)) as second:
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

        async with AsyncExitStack() as stack:
            clients = [
                await stack.enter_async_context(sio_client(auth=auth_tokens(user)))
                for user in users
            ]
            assert all(client.connected for client in clients)

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

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(sio_client(auth=auth_tokens(users[0])))
            await stack.enter_async_context(sio_client(auth=auth_tokens(users[1])))

            online = channel_online_users(test_channel.id, db_session)
            assert set(online) == {users[0].id, users[1].id}
            assert users[2].id not in online

    @pytest.mark.asyncio
    async def test_get_online_users_after_disconnect(self, sio_client, auth_tokens, test_users,
                                                     test_channel, test_workspace, db_session, get_perm):
        user_a, user_b = next(test_users), next(test_users)
        _grant_channel_access(db_session, test_workspace, test_channel, [user_a, user_b], get_perm)

        async with sio_client(auth=auth_tokens(user_a)) as client_a:
            async with sio_client(auth=auth_tokens(user_b)) as client_b:
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

        async with sio_client(auth=auth_tokens(user_a)) as client_a:
            wait_task = asyncio.create_task(client_a.wait_for("user_presence"))
            async with sio_client(auth=auth_tokens(user_b)) as client_b:
                presence = await wait_task
                assert presence["status"] == "user_online"
                assert UUID(presence["user_id"]) == user_b.id

    @pytest.mark.asyncio
    async def test_presence_event_on_last_disconnect(self, sio_client, auth_tokens, test_users,
                                                     test_channel, test_workspace, db_session, get_perm):
        user_a, user_b = next(test_users), next(test_users)
        _grant_channel_access(db_session, test_workspace, test_channel, [user_a, user_b], get_perm)

        async with sio_client(auth=auth_tokens(user_a)) as client_a:
            async with sio_client(auth=auth_tokens(user_b)) as client_b:
                await client_b.disconnect()
                presence = await client_a.wait_for("user_presence")
                assert presence["status"] == "user_offline"
                assert UUID(presence["user_id"]) == user_b.id

    @pytest.mark.asyncio
    async def test_message_broadcast_to_connected_recipient(self, sio_client, auth_tokens, test_users, test_channel,
                                                            test_workspace, db_session, get_perm):
        user_sender, user_recipient = next(test_users), next(test_users)
        _grant_channel_access(db_session, test_workspace, test_channel, [user_sender, user_recipient], get_perm)

        async with sio_client(auth=auth_tokens(user_sender)) as sender:
            async with sio_client(auth=auth_tokens(user_recipient)) as recipient:
                wait_task = asyncio.create_task(recipient.wait_for("message"))
                await asyncio.sleep(0)

                payload = WSMessage(
                    channel_id=test_channel.id,
                    sender_id=user_sender.id,
                    text="Hello recipient!",
                ).model_dump(mode="json")
                payload["workspace_id"] = str(test_workspace.id)

                await sender.call("message", payload)
                message = await wait_task

                assert message["text"] == "Hello recipient!"
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
