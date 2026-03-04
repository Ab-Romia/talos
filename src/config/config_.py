from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource


class AuthConfig(BaseSettings):
    google_client_id: str = ""
    google_client_secret: str = ""

    github_client_id: str = ""
    github_client_secret: str = ""

    totp_valid_window: int = 1

    jwt_secret_key: bytes = b""
    jwt_algorithm: str = "HS256"

    yaml_file: str = "config/auth.yaml"


class Config(BaseSettings):
    app_name: str = "Talos"
    app_host: str = "localhost"
    app_port: int = 8000

    auth: AuthConfig = AuthConfig()

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        extra="ignore",  # TODO: change to "forbid" in prod
    )

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings,
                                   env_settings, dotenv_settings, file_secret_settings):
        return (
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(settings_cls),
            init_settings,
        )
