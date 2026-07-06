"""AI-config endpoints: GET shape, PATCH upsert/clear, validation."""
import pytest
from sqlalchemy.exc import IntegrityError

from rag.ai_settings import AiConfigPatch, AiSettings


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(autouse=True)
def _cleanup_ai_settings(db_session, test_channel):
    """Tests share DB state — delete AiSettings rows for the test workspace
    after each test, mirroring the cleanup style in test_ai_settings.py."""
    ws = test_channel.workspace_id
    yield
    for row in db_session.query(AiSettings).filter_by(workspace_id=ws).all():
        db_session.delete(row)
    db_session.commit()


def test_get_returns_global_defaults_initially(client, test_channel, auth_token, path):
    r = client.get(f"/api/workspaces/{test_channel.workspace_id}/ai/config", headers=_h(auth_token))
    assert r.status_code == 200
    body = r.json()
    assert body["overrides"] == {}
    assert body["effective"]["use_reranking"] is True
    assert body["provenance"]["use_reranking"] == "global"


def test_patch_upserts_and_get_reflects(client, test_channel, auth_token):
    ws = test_channel.workspace_id
    r = client.patch(f"/api/workspaces/{ws}/ai/config",
                     json={"use_hyde": False, "retrieval_top_k": 9}, headers=_h(auth_token))
    assert r.status_code == 200
    assert r.json()["effective"]["retrieval_top_k"] == 9
    assert r.json()["provenance"]["retrieval_top_k"] == "workspace"

    # channel override wins over workspace
    r2 = client.patch(f"/api/channels/{test_channel.id}/ai/config",
                      json={"retrieval_top_k": 3}, headers=_h(auth_token))
    assert r2.status_code == 200
    assert r2.json()["effective"]["retrieval_top_k"] == 3
    assert r2.json()["provenance"]["retrieval_top_k"] == "channel"

    # null clears the channel override
    r3 = client.patch(f"/api/channels/{test_channel.id}/ai/config",
                      json={"retrieval_top_k": None}, headers=_h(auth_token))
    assert r3.json()["effective"]["retrieval_top_k"] == 9


def test_patch_rejects_blacklisted_and_out_of_bounds(client, test_channel, auth_token):
    ws = test_channel.workspace_id
    assert client.patch(f"/api/workspaces/{ws}/ai/config",
                        json={"openai_api_key": "x"}, headers=_h(auth_token)).status_code == 422
    assert client.patch(f"/api/workspaces/{ws}/ai/config",
                        json={"retrieval_top_k": 999}, headers=_h(auth_token)).status_code == 422
    assert client.patch(f"/api/workspaces/{ws}/ai/config",
                        json={"openai_model": "not-vetted"}, headers=_h(auth_token)).status_code == 422


def test_apply_patch_merges_into_existing_row(db_session, test_channel):
    """Upsert path: a pre-existing scope row is merged into, never duplicated."""
    from rag.settings_router import _apply_patch
    ws = test_channel.workspace_id
    db_session.add(AiSettings(workspace_id=ws, channel_id=None,
                              overrides={"retrieval_top_k": 9}))
    db_session.commit()

    _apply_patch(ws, None, AiConfigPatch(use_hyde=False))

    rows = db_session.query(AiSettings).filter_by(workspace_id=ws).all()
    assert len(rows) == 1
    assert rows[0].overrides == {"retrieval_top_k": 9, "use_hyde": False}


def test_apply_patch_retries_lost_first_insert_race(db_session, test_channel, monkeypatch):
    """Deterministic lost race: our first commit raises IntegrityError after a
    'concurrent winner' created the scope row; the retry must re-select the
    winner's row and merge into it (except-branch coverage)."""
    import database
    from rag.settings_router import _apply_patch

    ws = test_channel.workspace_id
    real_session_local = database.SessionLocal
    state = {"raced": False}

    def racing_session_local():
        db = real_session_local()
        real_commit = db.commit

        def commit():
            if not state["raced"]:
                state["raced"] = True
                # Drop our pending insert, let the "winner" commit its row,
                # then surface the unique-constraint failure we would have hit.
                db.rollback()
                with real_session_local() as winner:
                    winner.add(AiSettings(workspace_id=ws, channel_id=None,
                                          overrides={"use_reranking": False}))
                    winner.commit()
                raise IntegrityError("uq_ai_settings_ws_default", None, Exception("duplicate"))
            real_commit()

        db.commit = commit
        return db

    monkeypatch.setattr(database, "SessionLocal", racing_session_local)
    _apply_patch(ws, None, AiConfigPatch(use_hyde=False))
    monkeypatch.undo()

    assert state["raced"] is True
    rows = db_session.query(AiSettings).filter_by(workspace_id=ws).all()
    assert len(rows) == 1  # merged into the winner's row, no duplicate
    assert rows[0].overrides == {"use_reranking": False, "use_hyde": False}
