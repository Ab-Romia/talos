from unittest.mock import Mock, AsyncMock, patch

import pytest
from fastapi import status
from sqlalchemy import select

from auth.model import IdentityProvider, Issuer, User
from auth.oauth import OIDC, oauth_callback, oauth_login


class TestOIDC:
    def test_google(self):
        userinfo = {
            "iss": "https://accounts.google.com",
            "azp": "996521833228-otv2206g3oig2ng54duta8scphs5mrvs.apps.googleusercontent.com",
            "aud": "996521833228-otv2206g3oig2ng54duta8scphs5mrvs.apps.googleusercontent.com",
            "sub": "12345678",
            "email": "kyrollosyoussef02@gmail.com",
            "email_verified": True,
            "at_hash": "VKPOAvZA6vPQGPfTZYaTZg",
            "nonce": "n8UYdqo3fgJiupruhbyS",
            "name": "Kyrollos Youssef",
            "picture": "https://lh3.googleusercontent.com/a/ACg8ocJOvJZ1sN3ol8s7o_qeZsIhnojbrDtyCo_w88vs4wONYfrwDZU=s96-c",
            "given_name": "Kyrollos",
            "family_name": "Youssef",
            "iat": 1772899495,
            "exp": 1772903095
        }

        info = OIDC.model_validate(userinfo)

        assert info.sub == "12345678"
        assert info.email == "kyrollosyoussef02@gmail.com"
        assert info.email_verified is True
        assert info.iss == "https://accounts.google.com"
        assert info.name == "Kyrollos Youssef"
        assert info.picture == "https://lh3.googleusercontent.com/a/ACg8ocJOvJZ1sN3ol8s7o_qeZsIhnojbrDtyCo_w88vs4wONYfrwDZU=s96-c"

    def test_github(self):
        # GitHub /user API response — non-OIDC, uses `id`, no email_verified or iss
        userinfo = {
            "login": "k1rowashere",
            "id": 29287159,
            "node_id": "MDQ6VXNlcjI5Mjg3MTU5",
            "avatar_url": "https://avatars.githubusercontent.com/u/29287159?v=4",
            "gravatar_id": "",
            "url": "https://api.github.com/users/k1rowashere",
            "html_url": "https://github.com/k1rowashere",
            "followers_url": "https://api.github.com/users/k1rowashere/followers",
            "following_url": "https://api.github.com/users/k1rowashere/following{/other_user}",
            "gists_url": "https://api.github.com/users/k1rowashere/gists{/gist_id}",
            "starred_url": "https://api.github.com/users/k1rowashere/starred{/owner}{/repo}",
            "subscriptions_url": "https://api.github.com/users/k1rowashere/subscriptions",
            "organizations_url": "https://api.github.com/users/k1rowashere/orgs",
            "repos_url": "https://api.github.com/users/k1rowashere/repos",
            "events_url": "https://api.github.com/users/k1rowashere/events{/privacy}",
            "received_events_url": "https://api.github.com/users/k1rowashere/received_events",
            "type": "User",
            "user_view_type": "private",
            "site_admin": False,
            "name": "Kyrollos Youssef",
            "company": "Student",
            "blog": "",
            "location": None,
            "email": "kyrollosyoussef02@gmail.com",
            "hireable": None,
            "bio": "sup.",
            "twitter_username": None,
            "notification_email": "kyrollosyoussef02@gmail.com",
            "public_repos": 19,
            "public_gists": 0,
            "followers": 7,
            "following": 0,
            "created_at": "2017-06-08T18:48:16Z",
            "updated_at": "2026-03-06T05:19:50Z",
            "private_gists": 0,
            "total_private_repos": 6,
            "owned_private_repos": 6,
            "disk_usage": 52694,
            "collaborators": 3,
            "two_factor_authentication": True,
            "plan": {
                "name": "pro",
                "space": 976562499,
                "collaborators": 0,
                "private_repos": 9999
            }
        }

        info = OIDC.from_github(userinfo)

        assert info.sub == "29287159"
        assert info.email == "kyrollosyoussef02@gmail.com"
        assert info.email_verified is False
        assert info.iss == "https://github.com"
        assert info.name == "Kyrollos Youssef"
        assert info.picture == "https://avatars.githubusercontent.com/u/29287159?v=4"


class TestOAuthLogin:
    def test_google(self, client, path):
        response = client.get(path(oauth_login, provider="google"), follow_redirects=False)

        assert response.status_code == status.HTTP_302_FOUND
        location = response.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert "response_type=code" in location
        assert "scope=openid" in location
        assert "redirect_uri=" in location
        assert "state=" in location

    def test_github(self, client, path):
        response = client.get(path(oauth_login, provider="github"), follow_redirects=False)

        assert response.status_code == status.HTTP_302_FOUND
        location = response.headers["location"]
        assert location.startswith("https://github.com/login/oauth/authorize")
        assert "response_type=code" in location
        assert "scope=read" in location
        assert "redirect_uri=" in location
        assert "state=" in location

    def test_with_invalid_provider(self, client, path, db_session):
        response = client.get(path(oauth_login, provider="invalid-provider"))

        assert response.status_code == status.HTTP_404_NOT_FOUND


def make_userinfo(sub, email, name, iss="https://accounts.google.com", picture=None):
    info = {"sub": sub, "email": email, "email_verified": True, "iss": iss, "name": name}
    if picture:
        info["picture"] = picture
    return info


def setup_mock_oauth(mock_oauth, userinfo):
    mock_client = Mock()
    mock_client.authorize_access_token = AsyncMock(return_value={"userinfo": userinfo})
    mock_oauth.create_client.return_value = mock_client


def get_oauth_identity(db_session, user_id):
    return db_session.scalar(
        select(IdentityProvider).where(
            IdentityProvider.user_id == user_id,
            IdentityProvider.issuer == Issuer.oauth,
        )
    )


class TestOAuthCallback:
    @pytest.fixture(autouse=True)
    def setup_home_route(self, client):
        """Ensure a 'home' route exists for url_for calls in the application code."""
        # Check if 'home' is already defined (e.g. by other tests or actual app)
        if not any(route.name == "home" for route in client.app.routes):
            client.app.add_api_route("/dummy-home", lambda: None, name="home", methods=["GET"])

    @patch("auth.oauth.oauth")
    def test_creates_new_user(self, mock_oauth, client, path, db_session):
        userinfo = make_userinfo(
            sub="google-sub-creates-new-user",
            email="brand-new-oauth-user@example.com",
            name="Brand New User",
            picture="https://example.com/avatar.jpg",
        )
        setup_mock_oauth(mock_oauth, userinfo)

        response = client.get(path(oauth_callback, provider="google"), follow_redirects=False)

        assert response.status_code == status.HTTP_303_SEE_OTHER

        user = db_session.scalar(select(User).where(User.primary_email == userinfo["email"]))
        assert user is not None
        assert user.name == userinfo["name"]

        identity = get_oauth_identity(db_session, user.id)
        assert identity is not None
        assert identity.data["sub"] == userinfo["sub"]

    @patch("auth.oauth.oauth")
    def test_links_existing_user(self, mock_oauth, client, path, db_session, test_user):
        userinfo = make_userinfo(
            sub="google-sub-links-existing",
            email=test_user.primary_email,
            name=test_user.name,
        )
        setup_mock_oauth(mock_oauth, userinfo)

        response = client.get(path(oauth_callback, provider="google"),
                              follow_redirects=False,
                              headers={"Accept": "text/html"})

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert "oauth_handoff" in (response.headers.get("location") or "")

        identity = get_oauth_identity(db_session, test_user.id)
        assert identity is not None
        assert identity.data["sub"] == userinfo["sub"]

    @patch("auth.oauth.oauth")
    def test_returns_existing_identity(self, mock_oauth, client, path, db_session, test_user):
        existing_sub = "google-sub-existing-identity"
        db_session.add(IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.oauth,
            data={"sub": existing_sub, "iss": "https://accounts.google.com"},
        ))
        db_session.commit()

        userinfo = make_userinfo(
            sub=existing_sub,
            email=test_user.primary_email,
            name=test_user.name
        )
        setup_mock_oauth(mock_oauth, userinfo)

        response = client.get(path(oauth_callback, provider="google"),
                              follow_redirects=False,
                              headers={"Accept": "text/html"})

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert "oauth_handoff" in (response.headers.get("location") or "")

        identities = db_session.scalars(
            select(IdentityProvider).where(
                IdentityProvider.user_id == test_user.id,
                IdentityProvider.issuer == Issuer.oauth,
            )
        ).all()
        assert len(identities) == 1

    @patch("auth.oauth.oauth")
    def test_github_callback_creates_user(self, mock_oauth, client, path, db_session):
        # Mock OAuth client to return access token and GitHub user profile
        mock_client = AsyncMock()
        mock_client.authorize_access_token = AsyncMock(return_value={"access_token": "gh-token-123"})
        mock_response = Mock()
        mock_response.json.return_value = {
            "id": 987654,
            "email": "github-user@example.com",
            "name": "GitHub User",
            "avatar_url": "https://github.com/avatar.jpg",
        }
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_oauth.create_client.return_value = mock_client

        response = client.get(path(oauth_callback, provider="github"), follow_redirects=False)

        assert response.status_code == status.HTTP_303_SEE_OTHER

        mock_client.get.assert_called_once_with("/user", token={"access_token": "gh-token-123"})

        # Verify user created
        user = db_session.scalar(select(User).where(User.primary_email == "github-user@example.com"))
        assert user is not None
        assert user.name == "GitHub User"
        assert user.data["avatar_url"] == "https://github.com/avatar.jpg"
