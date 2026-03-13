import jwt.types
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource, YamlConfigSettingsSource


class OAuthClient(BaseModel):
    client_id: str
    client_secret: str
    api_base_url: str
    access_token_url: str
    authorize_url: str
    server_metadata_url: str = None
    client_kwargs: dict


class AuthConfig(BaseModel):
    oauth_clients: dict[str, OAuthClient]

    totp_valid_window: int = 1

    jwt_secret_key: bytes
    jwt_algorithm: str = "HS256"

    jwt_options: jwt.types.Options = None


class Config(BaseSettings):
    app_name: str = "Talos"
    app_host: str
    app_port: int

    database_url: str = ""

    auth: AuthConfig = None

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
