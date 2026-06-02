import uuid

import pytest
from fastapi import HTTPException

from auth.model import User
from files.dependencies import get_workspace_member, get_storage


@pytest.mark.integration
class TestGetWorkspaceMember:
    def test_valid(self, db_session, test_user, test_workspace):
        result = get_workspace_member(
            workspace_id=test_workspace.id,
            user=test_user,
            db=db_session,
        )
        assert result.id == test_workspace.id

    def test_not_found_404(self, db_session, test_user):
        with pytest.raises(HTTPException) as exc_info:
            get_workspace_member(
                workspace_id=uuid.uuid4(),
                user=test_user,
                db=db_session,
            )
        assert exc_info.value.status_code == 404

    def test_not_owner_403(self, db_session, test_workspace):
        other_user = User(
            id=uuid.uuid4(),
            username=f"other-{uuid.uuid4().hex[:8]}",
            primary_email=f"other_{uuid.uuid4().hex[:8]}@example.com",
            signup_complete=True,
            name="Other",
            data={},
        )
        db_session.add(other_user)
        db_session.flush()

        with pytest.raises(HTTPException) as exc_info:
            get_workspace_member(
                workspace_id=test_workspace.id,
                user=other_user,
                db=db_session,
            )
        assert exc_info.value.status_code == 403


@pytest.mark.integration
class TestGetStorage:
    def test_503_when_none(self):
        from unittest.mock import MagicMock
        request = MagicMock()
        request.app.state = MagicMock(spec=[])  # no minio_storage attr

        with pytest.raises(HTTPException) as exc_info:
            get_storage(request)
        assert exc_info.value.status_code == 503
