from unittest.mock import Mock, AsyncMock, patch

import pytest
from fastapi import status

from backend.auth.oauth import OAuthUserInfo
from model.identity import IdentityProvider, Issuer, User


class TestOAuthUserInfo:
    def test_google_mapping(self):
        google_login_sample = {
            "userinfo": {
                "iss": "https://accounts.google.com",
                "azp": "996521833228-otv2206g3oig2ng54duta8scphs5mrvs.apps.googleusercontent.com",
                "aud": "996521833228-otv2206g3oig2ng54duta8scphs5mrvs.apps.googleusercontent.com",
                "sub": "REDACTED",
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
        }

        OAuthUserInfo.model_validate(google_login_sample["userinfo"])


class TestOAuthLogin:
    @patch("backend.auth.oauth.oauth")
    def test_oauth_login_redirects_to_provider(self, mock_oauth, client, db_session):
        mock_client = Mock()
        mock_client.authorize_redirect = AsyncMock(return_value=Mock(status_code=302))
        mock_oauth.create_client.return_value = mock_client

        response = client.get("/api/auth/oauth/google")

        assert mock_oauth.create_client.called
        assert mock_client.authorize_redirect.called

    def test_oauth_login_with_invalid_provider(
            self, client, db_session
    ):
        """Should reject login with unsupported provider."""
        response = client.get("/api/auth/oauth/invalid-provider")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestOAuthCallback:
    """Test OAuth callback handling."""

    @patch("backend.auth.oauth.oauth")
    def test_oauth_callback_creates_new_user(
            self, mock_oauth, client, db_session
    ):
        """Should create new user when OAuth account doesn't exist."""
        # Mock OAuth client
        mock_client = Mock()
        mock_token = {
            "userinfo": {
                "sub": "google-123",
                "email": "newuser@example.com",
                "name": "New User",
                "picture": "https://example.com/avatar.jpg",
            },
            "iss": "https://accounts.google.com",
        }
        mock_client.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_oauth.create_client.return_value = mock_client

        # Mock data mapping function
        def mock_mapper(token):
            return OAuthUserInfo(
                sub=token["userinfo"]["sub"],
                email=token["userinfo"]["email"],
                name=token["userinfo"]["name"],
                avatar_url=token["userinfo"]["picture"],
            )

        with patch("backend.auth.oauth._PROVIDERS") as mock_providers:
            mock_providers.__getitem__.return_value = {"data_mapping": mock_mapper}

            response = client.get("/api/auth/oauth/google/callback")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data

        # Verify user was created
        user = db_session.query(User).filter(
            User.primary_email == "newuser@example.com"
        ).first()
        assert user is not None
        assert user.name == "New User"

        # Verify identity provider was created
        identity = db_session.query(IdentityProvider).filter(
            IdentityProvider.user_id == user.id,
            IdentityProvider.issuer == Issuer.oauth,
        ).first()
        assert identity is not None
        assert identity.data["sub"] == "google-123"

    @patch("backend.auth.oauth.oauth")
    def test_oauth_callback_links_existing_user(
            self, mock_oauth, client, db_session, test_user
    ):
        """Should link OAuth account to existing user with same email."""
        # Mock OAuth client
        mock_client = Mock()
        mock_token = {
            "userinfo": {
                "sub": "google-456",
                "email": test_user.primary_email,
                "name": test_user.name,
            },
            "iss": "https://accounts.google.com",
        }
        mock_client.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_oauth.create_client.return_value = mock_client

        def mock_mapper(token):
            return OAuthUserInfo(
                sub=token["userinfo"]["sub"],
                email=token["userinfo"]["email"],
                name=token["userinfo"]["name"],
            )

        with patch("backend.auth.oauth._PROVIDERS") as mock_providers:
            mock_providers.__getitem__.return_value = {"data_mapping": mock_mapper}

            response = client.get("/api/auth/oauth/google/callback")

        assert response.status_code == status.HTTP_200_OK

        # Verify identity was linked to existing user
        identity = db_session.query(IdentityProvider).filter(
            IdentityProvider.user_id == test_user.id,
            IdentityProvider.issuer == Issuer.oauth,
        ).first()
        assert identity is not None
        assert identity.data["sub"] == "google-456"

    @patch("backend.auth.oauth.oauth")
    def test_oauth_callback_returns_existing_identity(
            self, mock_oauth, client, db_session, test_user
    ):
        """Should authenticate user when OAuth identity already exists."""
        # Create existing OAuth identity
        existing_identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.oauth,
            data={"sub": "google-789", "iss": "https://accounts.google.com"},
        )
        db_session.add(existing_identity)
        db_session.commit()

        # Mock OAuth client
        mock_client = Mock()
        mock_token = {
            "userinfo": {
                "sub": "google-789",
                "email": test_user.primary_email,
                "name": test_user.name,
            },
            "iss": "https://accounts.google.com",
        }
        mock_client.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_oauth.create_client.return_value = mock_client

        def mock_mapper(token):
            return OAuthUserInfo(
                sub=token["userinfo"]["sub"],
                email=token["userinfo"]["email"],
                name=token["userinfo"]["name"],
            )

        with patch("backend.auth.oauth._PROVIDERS") as mock_providers:
            mock_providers.__getitem__.return_value = {"data_mapping": mock_mapper}

            response = client.get("/api/auth/oauth/google/callback")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data

        # Verify no duplicate identity was created
        identity_count = db_session.query(IdentityProvider).filter(
            IdentityProvider.user_id == test_user.id,
            IdentityProvider.issuer == Issuer.oauth,
        ).count()
        assert identity_count == 1

    @patch("backend.auth.oauth.oauth")
    def test_oauth_callback_with_invalid_token(
            self, mock_oauth, client, db_session
    ):
        """Should reject callback when token is invalid."""
        mock_client = Mock()
        mock_client.authorize_access_token = AsyncMock(
            side_effect=Exception("Invalid token")
        )
        mock_oauth.create_client.return_value = mock_client

        response = client.get("/api/auth/oauth/google/callback")

        assert response.status_code in [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]

    def test_oauth_callback_with_invalid_provider(
            self, client, db_session
    ):
        """Should reject callback for invalid provider."""
        response = client.get("/api/auth/oauth/invalid-provider/callback")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("backend.auth.oauth.oauth")
    def test_oauth_callback_saves_avatar_url(
            self, mock_oauth, client, db_session
    ):
        """Should save avatar URL to user data."""
        mock_client = Mock()
        mock_token = {
            "userinfo": {
                "sub": "google-999",
                "email": "avatar@example.com",
                "name": "Avatar User",
                "picture": "https://example.com/avatar.jpg",
            },
            "iss": "https://accounts.google.com",
        }
        mock_client.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_oauth.create_client.return_value = mock_client

        def mock_mapper(token):
            return OAuthUserInfo(
                sub=token["userinfo"]["sub"],
                email=token["userinfo"]["email"],
                name=token["userinfo"]["name"],
                avatar_url=token["userinfo"]["picture"],
            )

        with patch("backend.auth.oauth._PROVIDERS") as mock_providers:
            mock_providers.__getitem__.return_value = {"data_mapping": mock_mapper}

            response = client.get("/api/auth/oauth/google/callback")

        assert response.status_code == status.HTTP_200_OK

        # Verify avatar URL was saved
        user = db_session.query(User).filter(
            User.primary_email == "avatar@example.com"
        ).first()
        assert user is not None
        assert "avatar_url" in user.data
        assert user.data["avatar_url"] == "https://example.com/avatar.jpg"


class TestProviderValidation:
    """Test OAuth provider validation."""

    def test_check_provider_validates_google(self):
        """Should accept google as valid provider."""
        from backend.auth.oauth import check_provider

        result = check_provider("google")
        assert result == "google"

    def test_check_provider_validates_github(self):
        """Should accept github as valid provider."""
        from backend.auth.oauth import check_provider

        result = check_provider("github")
        assert result == "github"

    def test_check_provider_rejects_invalid(self):
        """Should reject invalid provider."""
        from backend.auth.oauth import check_provider, invalid_provider_exception

        with pytest.raises(Exception):
            check_provider("invalid")
