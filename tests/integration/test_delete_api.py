import uuid
from unittest.mock import patch

import pytest


@pytest.mark.integration
class TestDeleteAPI:
    def test_soft_delete_200(self, client, test_workspace, make_file):
        f = make_file(test_workspace.id)

        with patch("files.service.delete_file_chunks", create=True):
            resp = client.delete(f"/api/workspaces/{test_workspace.id}/files/{f.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(f.id)

    def test_soft_delete_404(self, client, test_workspace):
        resp = client.delete(f"/api/workspaces/{test_workspace.id}/files/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_deleted_excluded_from_list(self, client, test_workspace, make_file):
        f = make_file(test_workspace.id)

        with patch("files.service.delete_file_chunks", create=True):
            client.delete(f"/api/workspaces/{test_workspace.id}/files/{f.id}")

        resp = client.get(f"/api/workspaces/{test_workspace.id}/files")
        files = resp.json()["files"]
        file_ids = [file["id"] for file in files]
        assert str(f.id) not in file_ids
