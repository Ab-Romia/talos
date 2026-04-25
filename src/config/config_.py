from datetime import timedelta

from arq.connections import RedisSettings
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource, YamlConfigSettingsSource


class OAuthClient(BaseModel):
    client_id: str
    client_secret: str
    api_base_url: str
    access_token_url: str
    authorize_url: str
    server_metadata_url: str = None
    client_kwargs: dict = {}


class AuthConfig(BaseModel):
    oauth_clients: dict[str, OAuthClient] = {}

    totp_valid_window: int = 1

    jwe_secret: bytes
    jwt_header: dict

    sudo_max_age: timedelta = timedelta(minutes=10)
    session_max_age: timedelta = timedelta(days=30)
    session_refresh_threshold: timedelta = timedelta(minutes=10)
    password_reset_token_expiry: timedelta = timedelta(hours=1)

    session_cookie_key: str = "user_session"

    permission_bitstring_length: int = 64

    model_config = SettingsConfigDict(
        val_json_bytes="base64"
    )


class MinIOConfig(BaseModel):
    internal_endpoint: str = "localhost:9000"
    external_endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    secure: bool = False
    bucket_name: str = "talos-uploads"


class FilesConfig(BaseModel):
    max_size: int = 50 * 1024 * 1024  # 50 MiB

    # Allowed MIME types for uploads
    allowed_mime_types: set[str] = {
        # Documents
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        # Images
        "image/png",
        "image/jpeg",
        "image/webp",
    }

    document_mime_types: set[str] = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
    }

    image_mime_types: set[str] = {
        "image/png",
        "image/jpeg",
        "image/webp",
    }

    thumbnail_size: tuple[int, int] = (300, 300)


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    database: int = 0
    password: str
    username: str

    @property
    def url(self) -> str:
        auth_part = f"{self.username}:{self.password}@" if self.username and self.password else ""
        return f"redis://{auth_part}{self.host}:{self.port}/{self.database}"

    def to_redis_settings(self) -> RedisSettings:
        return RedisSettings(**self.model_dump())


class Config(BaseSettings):
    app_name: str = "Talos"
    app_host: str
    app_port: int
    # Where the browser should land after OAuth (Vite default in dev)
    frontend_origin: str = "http://localhost:5173"
    # Path on the SPA (App.jsx redirects / → /chat; /chat is fine for a direct “home”)
    frontend_post_oauth_path: str = "/chat"
    # Must match the authorized redirect origin in Google/GitHub (e.g. http://localhost:8000).
    # If empty, defaults to http://{app_host}:{app_port} so local IdP configs keep working
    # without console changes.
    oauth_callback_base: str = ""

    database_url: str
    cache_backend: str = "memory://"

    auth: AuthConfig = None
    minio: MinIOConfig = MinIOConfig()
    redis: RedisConfig = None
    files: FilesConfig = FilesConfig()
    # When True (default), run document embedding/indexing inside the API process so a
    # separate `arq` worker is not required for local dev. Set False in production when
    # using dedicated worker processes.
    inline_file_processing: bool = True

    model_config = SettingsConfigDict(
        env_file='.env',
        env_nested_delimiter="__",
        extra="ignore",
        yaml_file="config/config.yaml"
    )

    @classmethod
    def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )
