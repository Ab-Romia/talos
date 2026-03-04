from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource, YamlConfigSettingsSource


# name="google",
# client_id=config().auth.google_client.id,
# client_secret=config().auth.google_client.secret,
# server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
# client_kwargs={"scope": "openid email profile"},

class OAuthClient(BaseModel):
    id: str
    secret: str


class AuthConfig(BaseModel):
    google_client: OAuthClient = None
    github_client: OAuthClient = None

    totp_valid_window: int = 1

    # ensure is 64 bytes
    jwt_secret_key: bytes
    jwt_algorithm: str = "HS256"


class Config(BaseSettings):
    app_name: str = "Talos"
    app_host: str = "localhost"
    app_port: int = 8000

    database_url: str = ""

    auth: AuthConfig = None

    model_config = SettingsConfigDict(
        env_file='.env',
        env_nested_delimiter="__",
        extra="ignore",  # TODO: change to "forbid" in prod
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
