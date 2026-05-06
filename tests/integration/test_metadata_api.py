import uuid

import pytest

from files.models import ProcessingStatus


@pytest.mark.integration
class TestMetadataAPI:
    def test_get_metadata_200(self, client, test_workspace, make_file):
        f = make_file(test_workspace.id)
        resp = client.get(f"/api/workspaces/{test_workspace.id}/files/{f.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(f.id)
        assert data["original_filename"] == f.original_filename

    def test_get_metadata_404(self, client, test_workspace):
        resp = client.get(f"/api/workspaces/{test_workspace.id}/files/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_status_fields(self, client, test_workspace, make_file):
        f = make_file(test_workspace.id, processing_status=ProcessingStatus.INDEXED, chunk_count=5)
        resp = client.get(f"/api/workspaces/{test_workspace.id}/files/{f.id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["processing_status"] == "indexed"
        assert data["chunk_count"] == 5

    def test_list_files_pagination(self, client, test_workspace, make_file):
        for i in range(25):
            make_file(test_workspace.id, original_filename=f"file_{i}.txt")

        resp = client.get(f"/api/workspaces/{test_workspace.id}/files?limit=20")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 20
        assert data["next_cursor"] is not None

    def test_list_files_second_page(self, client, test_workspace, make_file):
        for i in range(25):
            make_file(test_workspace.id, original_filename=f"page_{i}.txt")

        resp1 = client.get(f"/api/workspaces/{test_workspace.id}/files?limit=20")
        cursor = resp1.json()["next_cursor"]

        resp2 = client.get(f"/api/workspaces/{test_workspace.id}/files?limit=20&cursor={cursor}")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["files"]) == 5
        assert data2["next_cursor"] is None

    def test_list_files_filter_channel(self, client, test_workspace, test_channel, make_file):
        make_file(test_workspace.id, channel_id=test_channel.id, original_filename="in_chat.txt")
        make_file(test_workspace.id, channel_id=None, original_filename="no_chat.txt")

        resp = client.get(
            f"/api/workspaces/{test_workspace.id}/files?channel_id={test_channel.id}"
        )
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert len(files) == 1
        assert files[0]["original_filename"] == "in_chat.txt"

    def test_list_files_empty_workspace(self, client, test_workspace):
        resp = client.get(f"/api/workspaces/{test_workspace.id}/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["files"] == []
        assert data["next_cursor"] is None

    def test_thumbnail_returns_presigned_url(self, client, test_workspace, make_file):
        f = make_file(
            test_workspace.id,
            content_type="image/png",
            thumbnail_storage_key="workspaces/x/thumb.jpg",
        )
        resp = client.get(f"/api/workspaces/{test_workspace.id}/files/{f.id}/thumbnail")
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_id"] == str(f.id)
        assert data["thumbnail_url"].startswith("http")

    def test_thumbnail_404_when_not_generated(self, client, test_workspace, make_file):
        f = make_file(test_workspace.id, content_type="application/pdf")
        resp = client.get(f"/api/workspaces/{test_workspace.id}/files/{f.id}/thumbnail")
        assert resp.status_code == 404
