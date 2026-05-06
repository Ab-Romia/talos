import uuid

import pytest


@pytest.mark.integration
class TestAttachAPI:
    def test_attach_returns_200(self, client, test_workspace, test_channel, test_message, make_file):
        f = make_file(test_workspace.id)
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/channels/{test_channel.id}"
            f"/messages/{test_message.id}/files?file_id={f.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "attached"

    def test_attach_nonexistent_file_404(self, client, test_workspace, test_channel, test_message):
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/channels/{test_channel.id}"
            f"/messages/{test_message.id}/files?file_id={uuid.uuid4()}"
        )
        assert resp.status_code == 404

    def test_attach_idempotent(self, client, test_workspace, test_channel, test_message, make_file):
        f = make_file(test_workspace.id)
        url = (
            f"/api/workspaces/{test_workspace.id}/channels/{test_channel.id}"
            f"/messages/{test_message.id}/files?file_id={f.id}"
        )
        resp1 = client.post(url)
        resp2 = client.post(url)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
